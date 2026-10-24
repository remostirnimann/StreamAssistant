using System.Buffers.Binary;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using StreamAssistant.Bridge.Devices.Simulated;
using StreamAssistant.Bridge.Devices.Virtual;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Tests;

/// <summary>An in-memory bridge with one simulated 5×3 deck and its own settings folder.</summary>
public sealed class TestBridge : WebApplicationFactory<Program>
{
    private readonly string _configDir = Path.Combine(Path.GetTempPath(), "sab-test-" + Guid.NewGuid().ToString("N"));

    public PairingService Pairing => Services.GetRequiredService<PairingService>();

    public Simulator Simulator => Services.GetRequiredService<Simulator>();

    public VirtualDevice Deck => Simulator.Devices[0];

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseSetting("config-dir", _configDir);
        builder.UseSetting("simulate", "5x3");
        builder.UseSetting("name", "Test bridge");
        builder.UseSetting("mdns", "false");
    }

    public async Task<TestClient> ConnectAsync()
    {
        var socket = await Server.CreateWebSocketClient().ConnectAsync(new Uri(Server.BaseAddress, "ws"), CancellationToken.None);
        return new TestClient(socket);
    }

    /// <summary>Pair a new client; returns it after welcome and devices, plus its token.</summary>
    public async Task<(TestClient Client, string Token)> PairAsync()
    {
        var client = await ConnectAsync();
        await client.SendAsync(new JsonObject { ["type"] = "pair", ["protocol"] = 1, ["client"] = "Test", ["code"] = Pairing.Code });
        var paired = await client.ReceiveAsync();
        Assert.Equal("paired", (string?)paired["type"]);
        Assert.Equal("welcome", (string?)(await client.ReceiveAsync())["type"]);
        Assert.Equal("devices", (string?)(await client.ReceiveAsync())["type"]);
        return (client, (string)paired["token"]!);
    }

    /// <summary>Connect with a token; returns the client after welcome and devices.</summary>
    public async Task<(TestClient Client, JsonObject Welcome, JsonObject Devices)> HelloAsync(string token)
    {
        var client = await ConnectAsync();
        await client.SendAsync(new JsonObject { ["type"] = "hello", ["protocol"] = 1, ["client"] = "Test", ["token"] = token });
        var welcome = await client.ReceiveAsync();
        Assert.Equal("welcome", (string?)welcome["type"]);
        var devices = await client.ReceiveAsync();
        Assert.Equal("devices", (string?)devices["type"]);
        return (client, welcome, devices);
    }

    public override async ValueTask DisposeAsync()
    {
        await base.DisposeAsync();
        try
        {
            Directory.Delete(_configDir, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}

public sealed class TestClient(WebSocket socket) : IAsyncDisposable
{
    public static readonly TimeSpan Timeout = TimeSpan.FromSeconds(5);

    public Task SendAsync(JsonObject message) =>
        socket.SendAsync(Encoding.UTF8.GetBytes(message.ToJsonString()), WebSocketMessageType.Text, true, CancellationToken.None);

    public Task SendBinaryAsync(JsonObject header, byte[] payload)
    {
        var json = Encoding.UTF8.GetBytes(header.ToJsonString());
        var frame = new byte[2 + json.Length + payload.Length];
        BinaryPrimitives.WriteUInt16BigEndian(frame, (ushort)json.Length);
        json.CopyTo(frame, 2);
        payload.CopyTo(frame, 2 + json.Length);
        return socket.SendAsync(frame, WebSocketMessageType.Binary, true, CancellationToken.None);
    }

    /// <summary>Next message; fails when none arrives in time or the connection closes.</summary>
    public async Task<JsonObject> ReceiveAsync() =>
        await TryReceiveAsync() ?? throw new Xunit.Sdk.XunitException("The bridge closed the connection");

    /// <summary>Next message, or null when the bridge closed the connection.</summary>
    public async Task<JsonObject?> TryReceiveAsync()
    {
        using var timeout = new CancellationTokenSource(Timeout);
        var buffer = new byte[64 * 1024];
        using var data = new MemoryStream();
        while (true)
        {
            var result = await socket.ReceiveAsync(buffer, timeout.Token);
            if (result.MessageType == WebSocketMessageType.Close)
            {
                return null;
            }
            data.Write(buffer, 0, result.Count);
            if (result.EndOfMessage)
            {
                return (JsonObject)JsonNode.Parse(data.ToArray())!;
            }
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (socket.State == WebSocketState.Open)
        {
            try
            {
                using var timeout = new CancellationTokenSource(Timeout);
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, null, timeout.Token);
            }
            catch (Exception err) when (err is OperationCanceledException or WebSocketException or IOException or ObjectDisposedException)
            {
            }
        }
        socket.Dispose();
    }
}
