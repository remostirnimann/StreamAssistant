using System.Buffers.Binary;
using System.Net;
using System.Net.Sockets;
using System.Text;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Discovery;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Tests;

public sealed class DiscoveryTests
{
    private static readonly MdnsService Service = new("0123456789abcdef", "Office.PC", 5390, "1.2.3", 1);

    /// <summary>A standard mDNS query with one question.</summary>
    private static byte[] Query(string name, ushort type, ushort id = 0)
    {
        using var packet = new MemoryStream();
        var header = new byte[12];
        BinaryPrimitives.WriteUInt16BigEndian(header, id);
        BinaryPrimitives.WriteUInt16BigEndian(header.AsSpan(4), 1);
        packet.Write(header);
        packet.Write(MdnsService.Name(name));
        var tail = new byte[4];
        BinaryPrimitives.WriteUInt16BigEndian(tail, type);
        BinaryPrimitives.WriteUInt16BigEndian(tail.AsSpan(2), 1);
        packet.Write(tail);
        return packet.ToArray();
    }

    private sealed record Answer(string Name, ushort Type, int Ttl, byte[] Data);

    private static List<Answer> Parse(byte[] packet)
    {
        Assert.Equal(0x8400, BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(2)));
        var count = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(6));
        var offset = 12;
        var answers = new List<Answer>();
        for (var i = 0; i < count; i++)
        {
            var name = MdnsService.ReadName(packet, ref offset);
            var type = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(offset));
            var ttl = BinaryPrimitives.ReadInt32BigEndian(packet.AsSpan(offset + 4));
            var length = BinaryPrimitives.ReadUInt16BigEndian(packet.AsSpan(offset + 8));
            answers.Add(new Answer(name, type, ttl, packet.AsSpan(offset + 10, length).ToArray()));
            offset += 10 + length;
        }
        return answers;
    }

    [Fact]
    public void Names_are_unique_and_safe()
    {
        Assert.Equal("Office-PC (012345)._stream-assistant._tcp.local", Service.InstanceName);
        Assert.Equal("sab-0123456789abcdef.local", Service.HostName);
        Assert.Contains("proto=1", Service.Txt);
        var longName = new MdnsService("ab", new string('x', 80), 1, "v", 1);
        Assert.StartsWith(new string('x', 50) + " (ab).", longName.InstanceName);
    }

    [Theory]
    [InlineData(MdnsService.ServiceType, MdnsService.TypePtr, true)]
    [InlineData(MdnsService.ServicesMeta, MdnsService.TypeAny, true)]
    [InlineData("Office-PC (012345)._stream-assistant._tcp.local", MdnsService.TypeSrv, true)]
    [InlineData("SAB-0123456789ABCDEF.local", MdnsService.TypeA, true)]
    [InlineData("_other._tcp.local", MdnsService.TypePtr, false)]
    [InlineData(MdnsService.ServiceType, MdnsService.TypeA, false)]
    public void Answers_only_its_own_questions(string name, ushort type, bool expected) =>
        Assert.Equal(expected, Service.IsQueryForUs(Query(name, type)));

    [Fact]
    public void Ignores_responses_and_garbage()
    {
        var response = Query(MdnsService.ServiceType, MdnsService.TypePtr);
        response[2] = 0x84;
        Assert.False(Service.IsQueryForUs(response));
        Assert.False(Service.IsQueryForUs([1, 2, 3]));
        // A question whose name points to itself (compression loop) and one cut short
        Assert.False(Service.IsQueryForUs([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0xC0, 12, 0, 12, 0, 1]));
        Assert.False(Service.IsQueryForUs([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 9, (byte)'x']));
    }

    [Fact]
    public void Compressed_names_are_read()
    {
        // "a.local" followed by a pointer back to it
        byte[] packet = [1, (byte)'a', 5, .. "local"u8, 0, 0xC0, 0];
        var offset = 9;
        Assert.Equal("a.local", MdnsService.ReadName(packet, ref offset));
        Assert.Equal(11, offset);
    }

    [Fact]
    public void Response_has_all_records()
    {
        var answers = Parse(Service.BuildResponse(1, [IPAddress.Parse("192.168.1.10"), IPAddress.Parse("10.0.0.5")]));
        Assert.Equal(6, answers.Count);
        var srv = answers.Single(a => a.Type == MdnsService.TypeSrv);
        Assert.Equal(5390, BinaryPrimitives.ReadUInt16BigEndian(srv.Data.AsSpan(4)));
        var txt = Encoding.UTF8.GetString(answers.Single(a => a.Type == MdnsService.TypeTxt).Data);
        Assert.Contains("id=0123456789abcdef", txt);
        Assert.Equal(["192.168.1.10", "10.0.0.5"], answers.Where(a => a.Type == MdnsService.TypeA).Select(a => new IPAddress(a.Data).ToString()));
        // Goodbye: TTL 0
        Assert.All(Parse(Service.BuildResponse(0, [])), a => Assert.Equal(0, a.Ttl));
    }

    [Fact]
    public void Picks_the_address_in_the_askers_network()
    {
        (IPAddress, IPAddress)[] local =
        [
            (IPAddress.Parse("172.30.32.1"), IPAddress.Parse("255.255.254.0")),
            (IPAddress.Parse("192.168.1.10"), IPAddress.Parse("255.255.255.0")),
        ];
        Assert.Equal([IPAddress.Parse("192.168.1.10")], MdnsService.PickAddresses(local, IPAddress.Parse("192.168.1.77")));
        Assert.Equal([IPAddress.Parse("192.168.1.10")], MdnsService.PickAddresses(local, IPAddress.Parse("192.168.1.77").MapToIPv6()));
        Assert.Equal(2, MdnsService.PickAddresses(local, IPAddress.Parse("8.8.8.8")).Count);
        Assert.Equal(2, MdnsService.PickAddresses(local, null).Count);
    }

    [Fact]
    public async Task Advertiser_answers_a_unicast_query()
    {
        await using var bridge = new TestBridge();
        _ = bridge.Server;
        var server = bridge.Services.GetRequiredService<BridgeServer>();
        var options = new BridgeOptions(5390, bridge.ConfigDir, "Test bridge", [], Mdns: true);
        var advertiser = new MdnsAdvertiser(server, options, NullLogger<MdnsAdvertiser>.Instance) { Port = 15353 + Random.Shared.Next(1000) };
        await advertiser.StartAsync(CancellationToken.None);
        try
        {
            using var client = new UdpClient(new IPEndPoint(IPAddress.Loopback, 0));
            var query = Query(MdnsService.ServiceType, MdnsService.TypePtr, id: 0x4242);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            UdpReceiveResult answer;
            while (true)
            {
                // The advertiser starts in the background: ask until it answers
                await client.SendAsync(query, new IPEndPoint(IPAddress.Loopback, advertiser.Port), timeout.Token);
                var receive = client.ReceiveAsync(timeout.Token).AsTask();
                if (await Task.WhenAny(receive, Task.Delay(500, timeout.Token)) != receive)
                {
                    continue;
                }
                try
                {
                    answer = await receive;
                    break;
                }
                catch (SocketException err) when (err.SocketErrorCode == SocketError.ConnectionReset)
                {
                    // Windows: the query reached the port before the advertiser listened
                }
            }
            Assert.Equal(0x4242, BinaryPrimitives.ReadUInt16BigEndian(answer.Buffer));
            Assert.Contains(Parse(answer.Buffer), a => a.Type == MdnsService.TypePtr && a.Name == MdnsService.ServiceType);
        }
        finally
        {
            await advertiser.StopAsync(CancellationToken.None);
        }
    }

    [Fact]
    public async Task Advertiser_does_nothing_when_disabled()
    {
        await using var bridge = new TestBridge();
        _ = bridge.Server;
        var options = new BridgeOptions(5390, bridge.ConfigDir, null, [], Mdns: false);
        var advertiser = new MdnsAdvertiser(bridge.Services.GetRequiredService<BridgeServer>(), options, NullLogger<MdnsAdvertiser>.Instance);
        await advertiser.StartAsync(CancellationToken.None);
        await advertiser.StopAsync(CancellationToken.None);
        Assert.DoesNotContain(MdnsAdvertiser.LocalAddresses(), a => IPAddress.IsLoopback(a.Address));
    }
}
