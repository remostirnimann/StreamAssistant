using System.Buffers.Binary;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Discovery;

/// <summary>
/// Announces the bridge as _stream-assistant._tcp via mDNS / DNS-SD
/// (protocol section 2) and answers queries for it. Minimal responder: IPv4,
/// no probing (the instance and host names contain the bridge id, so they are
/// unique). The records and packets are built by <see cref="MdnsService"/>.
/// </summary>
public sealed class MdnsAdvertiser(BridgeServer server, BridgeOptions options, ILogger<MdnsAdvertiser> logger) : BackgroundService
{
    public const string ServiceType = MdnsService.ServiceType;
    private static readonly IPAddress MdnsGroup = IPAddress.Parse("224.0.0.251");

    private UdpClient? _udp;
    private MdnsService? _service;

    /// <summary>mDNS port; tests use another one.</summary>
    public int Port { get; init; } = 5353;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.Mdns)
        {
            return;
        }
        _service = new MdnsService(server.Id, server.Name, options.Port, BridgeServer.Version, BridgeServer.ProtocolVersion);
        try
        {
            _udp = Open(Port);
        }
        catch (SocketException err)
        {
            logger.LogWarning("mDNS not available ({Error}); add the bridge in Home Assistant by its address", err.Message);
            return;
        }
        logger.LogInformation("Announcing {Instance} via mDNS", _service.InstanceName);
        try
        {
            // Two announcements, as RFC 6762 asks for
            await AnnounceAsync(ttlScale: 1);
            await Task.Delay(TimeSpan.FromSeconds(1), stoppingToken);
            await AnnounceAsync(ttlScale: 1);

            while (!stoppingToken.IsCancellationRequested)
            {
                UdpReceiveResult received;
                try
                {
                    received = await _udp.ReceiveAsync(stoppingToken);
                }
                catch (SocketException err) when (err.SocketErrorCode == SocketError.ConnectionReset)
                {
                    // Windows reports an unreachable unicast receiver on the next receive; not fatal
                    continue;
                }
                if (!_service.IsQueryForUs(received.Buffer))
                {
                    continue;
                }
                var response = _service.BuildResponse(1, MdnsService.PickAddresses(LocalAddresses(), received.RemoteEndPoint.Address));
                await _udp.SendAsync(response, new IPEndPoint(MdnsGroup, Port), stoppingToken);
                if (received.RemoteEndPoint.Port != Port)
                {
                    // Legacy unicast query (RFC 6762 section 6.7): answer the sender directly
                    BinaryPrimitives.WriteUInt16BigEndian(response, BinaryPrimitives.ReadUInt16BigEndian(received.Buffer));
                    await _udp.SendAsync(response, received.RemoteEndPoint, stoppingToken);
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

    private static UdpClient Open(int port)
    {
        var udp = new UdpClient(AddressFamily.InterNetwork);
        udp.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
        udp.Client.Bind(new IPEndPoint(IPAddress.Any, port));
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
        if (_udp is not null && _service is not null)
        {
            await _udp.SendAsync(_service.BuildResponse(ttlScale, MdnsService.PickAddresses(LocalAddresses(), null)), new IPEndPoint(MdnsGroup, Port));
        }
    }

    // Container, VM and VPN adapters: their addresses are not reachable from the LAN
    private static readonly string[] VirtualAdapterPrefixes =
        ["docker", "br-", "veth", "hassio", "virbr", "vEthernet", "vmnet", "VirtualBox", "VMware", "Hyper-V", "WSL", "tailscale", "zt", "wg", "tun", "tap"];

    /// <summary>IPv4 addresses (with mask) of real network adapters; all adapters if none looks real.</summary>
    public static List<(IPAddress Address, IPAddress Mask)> LocalAddresses()
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
}
