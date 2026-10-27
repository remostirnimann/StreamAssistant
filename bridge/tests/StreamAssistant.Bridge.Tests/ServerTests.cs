using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Time.Testing;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;

namespace StreamAssistant.Bridge.Tests;

/// <summary>A device driver for tests: any capabilities, fails on demand.</summary>
internal sealed class StubDevice(DeviceInfo info) : IControlDevice
{
    public DeviceInfo Info { get; } = info;

    public Exception? Failure { get; set; }

    public List<string> Calls { get; } = [];

    public event Action<IControlDevice, DeviceInput>? Input;

    public void Raise(DeviceInput input) => Input?.Invoke(this, input);

    private Task Call(string name)
    {
        Calls.Add(name);
        return Failure is null ? Task.CompletedTask : Task.FromException(Failure);
    }

    public Task SetBrightnessAsync(int percent, CancellationToken cancellationToken) => Call("brightness");

    public Task SetKeyImageAsync(int key, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken) => Call("image");

    public Task SetKeyColorAsync(int key, string color, CancellationToken cancellationToken) => Call("color");

    public Task SetTouchImageAsync(int x, int y, int width, int height, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken) => Call("touch");

    public Task SetButtonColorAsync(int button, string color, CancellationToken cancellationToken) => Call("button");

    public Task SetScreenImageAsync(string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken) => Call("screen");

    public Task SetDialLedsAsync(int dial, string color, double level, CancellationToken cancellationToken) => Call("leds");

    public Task ClearKeyAsync(int key, CancellationToken cancellationToken) => Call("clear");

    public Task ResetAsync(CancellationToken cancellationToken) => Call("reset");

    public Task IdentifyAsync(CancellationToken cancellationToken) => Call("identify");

    public static StubDevice Create(string id, DeviceCapabilities capabilities) =>
        new(new DeviceInfo(id, "Test", "Stub", id, null, null, false, capabilities));
}

public sealed class ServerTests
{
    private static async Task<JsonObject> Command(TestClient client, JsonObject command)
    {
        command["id"] = 1;
        await client.SendAsync(command);
        return await client.ReceiveAsync();
    }

    [Fact]
    public async Task Capabilities_are_enforced_and_driver_failures_reported()
    {
        await using var bridge = new TestBridge();
        var manager = bridge.Services.GetRequiredService<DeviceManager>();
        var pads = StubDevice.Create("pads", new DeviceCapabilities(KeyGrid.ColorsOnly(8, 8), Brightness: false,
            new DialSet(2, Press: true), new TouchArea(800, 100)));
        var knob = StubDevice.Create("knob", new DeviceCapabilities(null, Brightness: true));
        manager.Add(pads);
        manager.Add(knob);
        manager.Add(StubDevice.Create("pads", new DeviceCapabilities(null, false))); // duplicate id: ignored
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        var noBrightness = await Command(client, new JsonObject { ["type"] = "set_brightness", ["device"] = "pads", ["percent"] = 5 });
        Assert.Equal("unsupported", (string?)noBrightness["error"]!["code"]);
        var noImages = await Command(client, new JsonObject { ["type"] = "set_key_image", ["device"] = "pads", ["key"] = 1, ["format"] = "jpeg" });
        Assert.Equal("unsupported", (string?)noImages["error"]!["code"]);
        var noKeys = await Command(client, new JsonObject { ["type"] = "clear_key", ["device"] = "knob", ["key"] = 0 });
        Assert.Equal("unsupported", (string?)noKeys["error"]!["code"]);
        var missingDevice = await Command(client, new JsonObject { ["type"] = "reset" });
        Assert.Equal("invalid_message", (string?)missingDevice["error"]!["code"]);
        var missingKey = await Command(client, new JsonObject { ["type"] = "clear_key", ["device"] = "pads" });
        Assert.Equal("invalid_message", (string?)missingKey["error"]!["code"]);
        Assert.True((bool)(await Command(client, new JsonObject { ["type"] = "set_key_color", ["device"] = "pads", ["key"] = 63, ["color"] = "#00ff00" }))["ok"]!);

        // The driver fails: the client is told, the session goes on
        pads.Failure = new DeviceException("device_error", "USB write failed");
        var failed = await Command(client, new JsonObject { ["type"] = "reset", ["device"] = "pads" });
        Assert.Equal("device_error", (string?)failed["error"]!["code"]);
        pads.Failure = new InvalidOperationException("bug in driver");
        failed = await Command(client, new JsonObject { ["type"] = "identify", ["device"] = "pads" });
        Assert.Equal("device_error", (string?)failed["error"]!["code"]);
        await client.SendAsync(new JsonObject { ["type"] = "identify", ["device"] = "pads" });
        var error = await client.ReceiveAsync();
        Assert.Equal("error", (string?)error["type"]);
        Assert.Equal("identify", (string?)error["request"]);

        // Dial and touch input and capabilities travel as JSON
        pads.Raise(new DialInput(1, -3));
        pads.Raise(new DialPressInput(0, true));
        Assert.Equal(-3, (int)(await client.ReceiveAsync())["delta"]!);
        Assert.Equal("dial_press", (string?)(await client.ReceiveAsync())["type"]);
        var caps = pads.Info.ToJson()["capabilities"]!;
        Assert.True((bool)caps["keys"]!["colors"]!);
        Assert.Equal(2, (int)caps["dials"]!["count"]!);
        Assert.Equal(800, (int)caps["touch"]!["width"]!);
        manager.Remove("nope");
    }

    [Fact]
    public async Task Keys_without_display_only_report_presses()
    {
        await using var bridge = new TestBridge();
        var pedal = StubDevice.Create("pedal", new DeviceCapabilities(KeyGrid.Pedals(3, 1), Brightness: false));
        bridge.Services.GetRequiredService<DeviceManager>().Add(pedal);
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        foreach (var command in new[]
        {
            new JsonObject { ["type"] = "set_key_color", ["device"] = "pedal", ["key"] = 0, ["color"] = "#ffffff" },
            new JsonObject { ["type"] = "clear_key", ["device"] = "pedal", ["key"] = 0 },
        })
        {
            var refused = await Command(client, command);
            Assert.Equal("unsupported", (string?)refused["error"]!["code"]);
            Assert.Contains("no display", (string?)refused["error"]!["message"]);
        }
        await client.SendBinaryAsync(new JsonObject { ["type"] = "set_key_image", ["device"] = "pedal", ["key"] = 0, ["format"] = "png", ["id"] = 1 }, [1]);
        Assert.Contains("no display", (string?)(await client.ReceiveAsync())["error"]!["message"]);
        Assert.Empty(pedal.Calls);
    }

    [Fact]
    public async Task Malformed_messages()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        await client.SendRawAsync(Encoding.UTF8.GetBytes("[1,2]"), WebSocketMessageType.Text);
        Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["code"]);
        await client.SendRawAsync([0, 50, 1], WebSocketMessageType.Binary);
        Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["code"]);
        await client.SendRawAsync([7], WebSocketMessageType.Binary);
        Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["code"]);
    }

    [Theory]
    [InlineData("""{"type":"teleport","protocol":1}""")]
    [InlineData("not json")]
    public async Task Handshake_needs_hello_or_pair(string first)
    {
        await using var bridge = new TestBridge();
        await using var client = await bridge.ConnectAsync();
        await client.SendRawAsync(Encoding.UTF8.GetBytes(first), WebSocketMessageType.Text);
        Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["code"]);
        Assert.Null(await client.TryReceiveAsync());
    }

    [Fact]
    public async Task Binary_handshake_is_refused()
    {
        await using var bridge = new TestBridge();
        await using var client = await bridge.ConnectAsync();
        await client.SendRawAsync([1, 2, 3], WebSocketMessageType.Binary);
        Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["code"]);
    }

    [Fact]
    public async Task Devices_reset_when_the_client_stays_away()
    {
        var time = new FakeTimeProvider(DateTimeOffset.UtcNow);
        await using var bridge = new TestBridge(services => services.AddSingleton<TimeProvider>(time));
        var (client, token) = await bridge.PairAsync();
        await client.SendAsync(new JsonObject { ["type"] = "set_key_color", ["device"] = "sim-1", ["key"] = 1, ["color"] = "#010203", ["id"] = 1 });
        await client.ReceiveAsync();
        await client.DisposeAsync();
        await WaitForAsync(() => bridge.Services.GetRequiredService<Protocol.BridgeServer>().ActiveClient is null);

        // Back within 30 s: nothing is reset
        time.Advance(TimeSpan.FromSeconds(20));
        var (again, _, _) = await bridge.HelloAsync(token);
        time.Advance(TimeSpan.FromSeconds(20));
        Assert.NotNull(bridge.Deck.GetKey(1));
        await again.DisposeAsync();
        await WaitForAsync(() => bridge.Services.GetRequiredService<Protocol.BridgeServer>().ActiveClient is null);

        // Away for good: the idle screen comes back
        time.Advance(TimeSpan.FromSeconds(31));
        await WaitForAsync(() => bridge.Deck.GetKey(1) is null);
    }

    private static async Task WaitForAsync(Func<bool> condition)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (!condition())
        {
            await Task.Delay(20, timeout.Token);
        }
    }

    [Fact]
    public async Task Revoked_clients_must_pair_again()
    {
        await using var bridge = new TestBridge();
        var (client, token) = await bridge.PairAsync();
        await client.DisposeAsync();
        bridge.Pairing.RevokeAll();
        Assert.Equal(0, bridge.Pairing.PairedClients);
        await using var refused = await bridge.ConnectAsync();
        await refused.SendAsync(new JsonObject { ["type"] = "hello", ["protocol"] = 1, ["token"] = token });
        Assert.Equal("unauthorized", (string?)(await refused.ReceiveAsync())["code"]);
    }

    [Fact]
    public void Options_from_configuration()
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["simulate"] = "5x3, 8x4:2, plus, Pedal",
            ["port"] = "6000",
        }).Build();
        var options = BridgeOptions.From(config);
        Assert.Equal([new SimulatedDeck(5, 3), new SimulatedDeck(8, 4, 2)], options.Simulate.Take(2));
        Assert.Equal(("Stream Deck +", 4, 120), (options.Simulate[2].Like!.Name, options.Simulate[2].Dials, options.Simulate[2].KeySize));
        Assert.Equal(("Stream Deck Pedal", 0), (options.Simulate[3].Like!.Name, options.Simulate[3].KeySize));
        Assert.Equal(6000, options.Port);
        Assert.True(options.Mdns);
        Assert.EndsWith("stream-assistant-bridge", options.ConfigDir);

        var invalid = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["simulate"] = "5x" }).Build();
        Assert.Throws<ArgumentException>(() => BridgeOptions.From(invalid));
    }

    [Fact]
    public void Broken_settings_are_kept_aside()
    {
        var dir = Path.Combine(Path.GetTempPath(), "sab-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "bridge.json"), "{ not json");
        var options = new BridgeOptions(0, dir, null, [], Mdns: false);
        using (var store = new SettingsStore(options, NullLogger<SettingsStore>.Instance))
        {
            Assert.Equal(16, store.Settings.Id.Length);
            Assert.True(File.Exists(Path.Combine(dir, "bridge.json.broken")));
        }
        Directory.Delete(dir, recursive: true);
    }
}
