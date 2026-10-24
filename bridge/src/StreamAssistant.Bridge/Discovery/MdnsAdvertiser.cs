using System.Buffers.Binary;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Discovery;

/// <summary>
/// Announces the bridge as _stream-assistant._tcp via mDNS / DNS-SD
/// (protocol section 2) and answers queries for it. Minimal responder: IPv4,
/// no probing (the instance and host names contain the bridge id, so they are unique).
/// </summary>
public sealed class MdnsAdvertiser(BridgeServer server, BridgeOptions options, ILogger<MdnsAdvertiser> logger) : BackgroundService
{
    public const string ServiceType = "_stream-assistant._tcp.local";
    private const string ServicesMeta = "_services._dns-sd._udp.local";
    private const int MdnsPort = 5353;
    private static readonly IPAddress MdnsGroup = IPAddress.Parse("224.0.0.251");

    private const ushort TypeA = 1;
    private const ushort TypePtr = 12;
    private const ushort TypeTxt = 16;
    private const ushort TypeSrv = 33;
    private const ushort TypeAny = 255;
    private const ushort ClassIn = 1;
    private const ushort CacheFlush = 0x8000;

    private UdpClient? _udp;

    private string InstanceName => $"{Label(server.Name)} ({server.Id[..6]}).{ServiceType}";

    private string HostName => $"sab-{server.Id}.local";

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.Mdns)
        {
            return;
        }
        try
        {
            _udp = Open();
        }
        catch (SocketException err)
        {
            logger.LogWarning("mDNS not available ({Error}); add the bridge in Home Assistant by its address", err.Message);
            return;
        }
        logger.LogInformation("Announcing {Instance} via mDNS", InstanceName);
        try
        {
            // Two announcements, as RFC 6762 asks for
            await AnnounceAsync(ttlScale: 1);
            await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken);
            await AnnounceAsync(ttlScale: 1);

            while (!stoppingToken.IsCancellationRequested)
            {
                var received = await _udp.ReceiveAsync(stoppingToken);
                if (IsQueryForUs(received.Buffer))
                {
                    // Answer with the address in the asker's network, so it gets one it can reach
                    var response = BuildResponse(ttlScale: 1, received.RemoteEndPoint.Address);
                    await _udp.SendAsync(response, new IPEndPoint(MdnsGroup, MdnsPort), stoppingToken);
                    if (received.RemoteEndPoint.Port != MdnsPort)
                    {
                        // Legacy unicast query (RFC 6762 section 6.7): answer the sender directly
                        BinaryPrimitives.WriteUInt16BigEndian(response, BinaryPrimitives.ReadUInt16BigEndian(received.Buffer));
                        await _udp.SendAsync(response, received.RemoteEndPoint, stoppingToken);
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (SocketException err)
        {
            logger.LogWarning("mDNS stopped: {Error}", err.Message);
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        if (_udp is not null)
        {
            try
            {
                // Goodbye: TTL 0 removes the bridge from caches right away
                await AnnounceAsync(ttlScale: 0);
            }
            catch (SocketException)
            {
            }
        }
        await base.StopAsync(cancellationToken);
        _udp?.Dispose();
    }

    private static UdpClient Open()
    {
        var udp = new UdpClient(AddressFamily.InterNetwork);
        udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
        udp.Client.Bind(new IPEndPoint(IPAddress.Any, MdnsPort));
        foreach (var (address, _) in LocalAddresses())
        {
            try
            {
                udp.JoinMulticastGroup(MdnsGroup, address);
            }
            catch (SocketException)
            {
                // Interface without multicast; the others still work
            }
        }
        udp.MulticastLoopback = true;
        return udp;
    }

    private async Task AnnounceAsync(int ttlScale)
    {
        if (_udp is not null)
        {
            await _udp.SendAsync(BuildResponse(ttlScale, asker: null), new IPEndPoint(MdnsGroup, MdnsPort));
        }
    }

    // Container, VM and VPN adapters: their addresses are not reachable from the LAN
    private static readonly string[] VirtualAdapterPrefixes =
        ["docker", "br-", "veth", "hassio", "virbr", "vEthernet", "vmnet", "VirtualBox", "VMware", "Hyper-V", "WSL", "tailscale", "zt", "wg", "tun", "tap"];

    /// <summary>IPv4 addresses (with mask) of real network adapters; all adapters if none looks real.</summary>
    private static List<(IPAddress Address, IPAddress Mask)> LocalAddresses()
    {
        var interfaces = NetworkInterface.GetAllNetworkInterfaces()
            .Where(n => n.OperationalStatus == OperationalStatus.Up
                && n.NetworkInterfaceType is not (NetworkInterfaceType.Loopback or NetworkInterfaceType.Tunnel or NetworkInterfaceType.Ppp))
            .ToList();
        static bool IsVirtual(NetworkInterface n) => VirtualAdapterPrefixes.Any(prefix =>
            n.Name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) || n.Description.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
        var real = interfaces.Where(n => !IsVirtual(n)).ToList();
        return (real.Count > 0 ? real : interfaces)
            .SelectMany(n => n.GetIPProperties().UnicastAddresses)
            .Where(a => a.Address.AddressFamily == AddressFamily.InterNetwork && !IPAddress.IsLoopback(a.Address))
            .Select(a => (a.Address, a.IPv4Mask))
            .DistinctBy(a => a.Address)
            .ToList();
    }

    private static bool SameSubnet(IPAddress a, IPAddress b, IPAddress mask)
    {
        var x = a.GetAddressBytes();
        var y = b.GetAddressBytes();
        var m = mask.GetAddressBytes();
        return x.Length == 4 && y.Length == 4 && Enumerable.Range(0, 4).All(i => (x[i] & m[i]) == (y[i] & m[i]));
    }

    // Packets

    private bool IsQueryForUs(byte[] packet)
    {
        try
        {
            if (packet.Length < 12 || (packet[2] & 0x80) != 0)
            {
                return false; // too short or a response
            }
            var questions = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(4));
            var offset = 12;
            for (var i = 0; i < questions; i++)
            {
                var name = ReadName(packet, ref offset);
                var type = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(offset));
                offset += 4;
                if (Matches(name, type))
                {
                    return true;
                }
            }
        }
        catch (Exception err) when (err is IndexOutOfRangeException or ArgumentOutOfRangeException or InvalidDataException)
        {
            // Malformed packet from the network
        }
        return false;
    }

    private bool Matches(string name, ushort type)
    {
        bool Is(string other) => string.Equals(name, other, StringComparison.OrdinalIgnoreCase);
        return (Is(ServiceType) && type is TypePtr or TypeAny)
            || (Is(ServicesMeta) && type is TypePtr or TypeAny)
            || (Is(InstanceName) && type is TypeSrv or TypeTxt or TypeAny)
            || (Is(HostName) && type is TypeA or TypeAny);
    }

    private byte[] BuildResponse(int ttlScale, IPAddress? asker)
    {
        var all = LocalAddresses();
        if (asker?.IsIPv4MappedToIPv6 == true)
        {
            asker = asker.MapToIPv4();
        }
        var near = asker is null ? [] : all.Where(a => SameSubnet(a.Address, asker, a.Mask)).Select(a => a.Address).ToList();
        var addresses = near.Count > 0 ? near : all.Select(a => a.Address).ToList();
        var records = new List<byte[]>
        {
            Record(ServicesMeta, TypePtr, ClassIn, 4500 * ttlScale, Name(ServiceType)),
            Record(ServiceType, TypePtr, ClassIn, 4500 * ttlScale, Name(InstanceName)),
            Record(InstanceName, TypeSrv, ClassIn | CacheFlush, 120 * ttlScale, Srv()),
            Record(InstanceName, TypeTxt, ClassIn | CacheFlush, 4500 * ttlScale, Txt()),
        };
        records.AddRange(addresses.Select(a => Record(HostName, TypeA, ClassIn | CacheFlush, 120 * ttlScale, a.GetAddressBytes())));

        using var packet = new MemoryStream();
        Span<byte> header = stackalloc byte[12];
        BinaryPrimitives.WriteUInt16BigEndian(header[2..], 0x8400); // response, authoritative
        BinaryPrimitives.WriteUInt16BigEndian(header[6..], (ushort)records.Count);
        packet.Write(header);
        foreach (var record in records)
        {
            packet.Write(record);
        }
        return packet.ToArray();
    }

    private byte[] Srv()
    {
        var target = Name(HostName);
        var data = new byte[6 + target.Length];
        BinaryPrimitives.WriteUInt16BigEndian(data.AsSpan(4), (ushort)options.Port);
        target.CopyTo(data, 6);
        return data;
    }

    private byte[] Txt()
    {
        using var data = new MemoryStream();
        foreach (var entry in new[]
                 {
                     $"id={server.Id}", $"name={server.Name}", $"version={BridgeServer.Version}",
                     $"proto={BridgeServer.ProtocolVersion}", "path=/ws",
                 })
        {
            var bytes = Encoding.UTF8.GetBytes(entry);
            var length = Math.Min(bytes.Length, 255);
            data.WriteByte((byte)length);
            data.Write(bytes, 0, length);
        }
        return data.ToArray();
    }

    private static byte[] Record(string name, ushort type, int @class, int ttl, byte[] data)
    {
        var encoded = Name(name);
        var record = new byte[encoded.Length + 10 + data.Length];
        encoded.CopyTo(record, 0);
        var span = record.AsSpan(encoded.Length);
        BinaryPrimitives.WriteUInt16BigEndian(span, type);
        BinaryPrimitives.WriteUInt16BigEndian(span[2..], (ushort)@class);
        BinaryPrimitives.WriteInt32BigEndian(span[4..], ttl);
        BinaryPrimitives.WriteUInt16BigEndian(span[8..], (ushort)data.Length);
        data.CopyTo(span[10..]);
        return record;
    }

    /// <summary>DNS name: the instance label may contain dots, so it is split off first.</summary>
    private static byte[] Name(string name)
    {
        var labels = new List<string>();
        var service = name.IndexOf("._", StringComparison.Ordinal);
        if (service > 0 && name.EndsWith(ServiceType, StringComparison.Ordinal) && name != ServiceType)
        {
            labels.Add(name[..service]);
            name = name[(service + 1)..];
        }
        labels.AddRange(name.Split('.'));
        using var data = new MemoryStream();
        foreach (var label in labels)
        {
            var bytes = Encoding.UTF8.GetBytes(label);
            data.WriteByte((byte)Math.Min(bytes.Length, 63));
            data.Write(bytes, 0, Math.Min(bytes.Length, 63));
        }
        data.WriteByte(0);
        return data.ToArray();
    }

    private static string ReadName(byte[] packet, ref int offset)
    {
        var labels = new List<string>();
        var position = offset;
        var jumped = false;
        for (var hops = 0; hops < 32; hops++)
        {
            var length = packet[position];
            if (length == 0)
            {
                if (!jumped)
                {
                    offset = position + 1;
                }
                return string.Join('.', labels);
            }
            if ((length & 0xC0) == 0xC0)
            {
                var pointer = ((length & 0x3F) << 8) | packet[position + 1];
                if (!jumped)
                {
                    offset = position + 2;
                }
                jumped = true;
                position = pointer;
                continue;
            }
            labels.Add(Encoding.UTF8.GetString(packet, position + 1, length));
            position += 1 + length;
        }
        throw new InvalidDataException("Name compression loop");
    }

    /// <summary>Instance label: at most 50 characters, no dots (they would split the label).</summary>
    private static string Label(string name)
    {
        var clean = name.Replace('.', '-').Trim();
        return clean.Length > 50 ? clean[..50] : clean;
    }
}
