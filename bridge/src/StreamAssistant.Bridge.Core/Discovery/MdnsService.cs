using System.Buffers.Binary;
using System.Net;
using System.Text;

namespace StreamAssistant.Bridge.Discovery;

/// <summary>
/// The DNS-SD records of one bridge (protocol section 2) and the packet code
/// to answer mDNS queries for them. No sockets: see <see cref="MdnsAdvertiser"/>.
/// </summary>
public sealed class MdnsService(string id, string name, int port, string version, int protocol)
{
    public const string ServiceType = "_stream-assistant._tcp.local";
    public const string ServicesMeta = "_services._dns-sd._udp.local";

    public const ushort TypeA = 1;
    public const ushort TypePtr = 12;
    public const ushort TypeTxt = 16;
    public const ushort TypeSrv = 33;
    public const ushort TypeAny = 255;
    private const ushort ClassIn = 1;
    private const ushort CacheFlush = 0x8000;

    /// <summary>Unique through the bridge id, so no probing is needed.</summary>
    public string InstanceName { get; } = $"{Label(name)} ({id[..Math.Min(6, id.Length)]}).{ServiceType}";

    public string HostName { get; } = $"sab-{id}.local";

    public IReadOnlyList<string> Txt { get; } =
        [$"id={id}", $"name={name}", $"version={version}", $"proto={protocol}", "path=/ws"];

    /// <summary>True for a query that asks for any of our records. Malformed packets are not.</summary>
    public bool IsQueryForUs(byte[] packet)
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
                var question = ReadName(packet, ref offset);
                var type = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(offset));
                offset += 4;
                if (Matches(question, type))
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

    /// <summary>
    /// All records in one response. <paramref name="ttlScale"/> 0 is the goodbye
    /// that removes the bridge from caches.
    /// </summary>
    public byte[] BuildResponse(int ttlScale, IReadOnlyList<IPAddress> addresses)
    {
        var records = new List<byte[]>
        {
            Record(ServicesMeta, TypePtr, ClassIn, 4500 * ttlScale, Name(ServiceType)),
            Record(ServiceType, TypePtr, ClassIn, 4500 * ttlScale, Name(InstanceName)),
            Record(InstanceName, TypeSrv, ClassIn | CacheFlush, 120 * ttlScale, Srv()),
            Record(InstanceName, TypeTxt, ClassIn | CacheFlush, 4500 * ttlScale, TxtData()),
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

    /// <summary>
    /// The addresses in the asker's network, so it gets one it can reach;
    /// all addresses for announcements or when none matches.
    /// </summary>
    public static IReadOnlyList<IPAddress> PickAddresses(IReadOnlyList<(IPAddress Address, IPAddress Mask)> local, IPAddress? asker)
    {
        if (asker?.IsIPv4MappedToIPv6 == true)
        {
            asker = asker.MapToIPv4();
        }
        var near = asker is null ? [] : local.Where(a => SameSubnet(a.Address, asker, a.Mask)).Select(a => a.Address).ToList();
        return near.Count > 0 ? near : local.Select(a => a.Address).ToList();
    }

    /// <summary>Reads a (possibly compressed) DNS name; advances <paramref name="offset"/> past it.</summary>
    public static string ReadName(byte[] packet, ref int offset)
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

    /// <summary>DNS name: the instance label may contain dots, so it is split off first.</summary>
    public static byte[] Name(string name)
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

    private bool Matches(string question, ushort type)
    {
        bool Is(string other) => string.Equals(question, other, StringComparison.OrdinalIgnoreCase);
        return (Is(ServiceType) && type is TypePtr or TypeAny)
            || (Is(ServicesMeta) && type is TypePtr or TypeAny)
            || (Is(InstanceName) && type is TypeSrv or TypeTxt or TypeAny)
            || (Is(HostName) && type is TypeA or TypeAny);
    }

    private byte[] Srv()
    {
        var target = Name(HostName);
        var data = new byte[6 + target.Length];
        BinaryPrimitives.WriteUInt16BigEndian(data.AsSpan(4), (ushort)port);
        target.CopyTo(data, 6);
        return data;
    }

    private byte[] TxtData()
    {
        using var data = new MemoryStream();
        foreach (var entry in Txt)
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

    private static bool SameSubnet(IPAddress a, IPAddress b, IPAddress mask)
    {
        var x = a.GetAddressBytes();
        var y = b.GetAddressBytes();
        var m = mask.GetAddressBytes();
        return x.Length == 4 && y.Length == 4 && m.Length == 4 && Enumerable.Range(0, 4).All(i => (x[i] & m[i]) == (y[i] & m[i]));
    }

    /// <summary>Instance label: at most 50 characters, no dots (they would split the label).</summary>
    private static string Label(string name)
    {
        var clean = name.Replace('.', '-').Trim();
        return clean.Length > 50 ? clean[..50] : clean;
    }
}
