using System.Text.Json.Nodes;

namespace StreamAssistant.Bridge.Tests;

public sealed class HandshakeTests
{
    [Fact]
    public async Task Unpaired_client_is_refused()
    {
        await using var bridge = new TestBridge();
        await using var client = await bridge.ConnectAsync();
        await client.SendAsync(new JsonObject { ["type"] = "hello", ["protocol"] = 1, ["client"] = "Test" });

        var error = await client.ReceiveAsync();
        Assert.Equal("error", (string?)error["type"]);
        Assert.Equal("unauthorized", (string?)error["code"]);
        Assert.Null(await client.TryReceiveAsync());
    }

    [Fact]
    public async Task Unknown_protocol_version_lists_supported_versions()
    {
        await using var bridge = new TestBridge();
        await using var client = await bridge.ConnectAsync();
        await client.SendAsync(new JsonObject { ["type"] = "hello", ["protocol"] = 2, ["client"] = "Test" });

        var error = await client.ReceiveAsync();
        Assert.Equal("unsupported_protocol", (string?)error["code"]);
        Assert.Equal(1, (int)error["supported"]![0]!);
    }

    [Fact]
    public async Task Wrong_pairing_code_is_refused_and_lockout_follows()
    {
        await using var bridge = new TestBridge();
        var wrong = bridge.Pairing.Code == "000000" ? "111111" : "000000";
        for (var attempt = 0; attempt < 5; attempt++)
        {
            await using var client = await bridge.ConnectAsync();
            await client.SendAsync(new JsonObject { ["type"] = "pair", ["protocol"] = 1, ["client"] = "Test", ["code"] = wrong });
            Assert.Equal("invalid_code", (string?)(await client.ReceiveAsync())["code"]);
        }

        // Locked: even the right code is refused now
        await using var locked = await bridge.ConnectAsync();
        await locked.SendAsync(new JsonObject { ["type"] = "pair", ["protocol"] = 1, ["client"] = "Test", ["code"] = bridge.Pairing.Code });
        Assert.Equal("invalid_code", (string?)(await locked.ReceiveAsync())["code"]);
    }

    [Fact]
    public async Task Pairing_gives_a_token_that_works_later()
    {
        await using var bridge = new TestBridge();
        var codeBefore = bridge.Pairing.Code;
        var (first, token) = await bridge.PairAsync();
        await first.DisposeAsync();
        Assert.NotEqual(codeBefore, bridge.Pairing.Code);

        var (client, welcome, devices) = await bridge.HelloAsync(token);
        await using var _ = client;
        Assert.Equal(1, (int)welcome["protocol"]!);
        Assert.Equal("Test bridge", (string?)welcome["bridge"]!["name"]);
        Assert.Contains("key_images", welcome["features"]!.AsArray().Select(f => (string?)f));

        var deck = devices["devices"]!.AsArray().Single()!;
        Assert.Equal("sim-1", (string?)deck["id"]);
        Assert.True((bool)deck["virtual"]!);
        Assert.Equal(5, (int)deck["capabilities"]!["keys"]!["cols"]!);
        Assert.Equal(3, (int)deck["capabilities"]!["keys"]!["rows"]!);
        Assert.Equal(72, (int)deck["capabilities"]!["keys"]!["image"]!["width"]!);
    }

    [Fact]
    public async Task Second_client_replaces_the_first()
    {
        await using var bridge = new TestBridge();
        var (first, token) = await bridge.PairAsync();
        await using var _ = first;
        var (second, _, _) = await bridge.HelloAsync(token);
        await using var __ = second;

        var error = await first.ReceiveAsync();
        Assert.Equal("replaced", (string?)error["code"]);
        Assert.Null(await first.TryReceiveAsync());
    }
}

public sealed class CommandTests
{
    private static readonly byte[] Jpeg = [0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3, 0xFF, 0xD9];

    [Fact]
    public async Task Key_image_reaches_the_deck()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        await client.SendBinaryAsync(new JsonObject { ["type"] = "set_key_image", ["device"] = "sim-1", ["key"] = 7, ["format"] = "jpeg", ["id"] = 1 }, Jpeg);
        var result = await client.ReceiveAsync();
        Assert.Equal("result", (string?)result["type"]);
        Assert.True((bool)result["ok"]!);
        Assert.Equal(Jpeg, bridge.Deck.GetKey(7)!.Image);
        Assert.Equal("jpeg", bridge.Deck.GetKey(7)!.Format);
    }

    [Fact]
    public async Task Brightness_color_clear_and_reset()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        await client.SendAsync(new JsonObject { ["type"] = "set_brightness", ["device"] = "sim-1", ["percent"] = 42, ["id"] = 1 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        Assert.Equal(42, bridge.Deck.Brightness);

        await client.SendAsync(new JsonObject { ["type"] = "set_key_color", ["device"] = "sim-1", ["key"] = 2, ["color"] = "#FF8800", ["id"] = 2 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        Assert.Equal("#ff8800", bridge.Deck.GetKey(2)!.Color);

        await client.SendAsync(new JsonObject { ["type"] = "clear_key", ["device"] = "sim-1", ["key"] = 2, ["id"] = 3 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        Assert.Null(bridge.Deck.GetKey(2));

        await client.SendAsync(new JsonObject { ["type"] = "set_key_color", ["device"] = "sim-1", ["key"] = 4, ["color"] = "#000000" });
        await client.SendAsync(new JsonObject { ["type"] = "reset", ["device"] = "sim-1", ["id"] = 4 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        Assert.Null(bridge.Deck.GetKey(4));
    }

    [Theory]
    [InlineData("""{"type":"set_brightness","device":"nope","percent":10,"id":9}""", "unknown_device")]
    [InlineData("""{"type":"set_brightness","device":"sim-1","percent":101,"id":9}""", "invalid_message")]
    [InlineData("""{"type":"set_key_color","device":"sim-1","key":15,"color":"#000000","id":9}""", "invalid_message")]
    [InlineData("""{"type":"set_key_color","device":"sim-1","key":1,"color":"red","id":9}""", "invalid_message")]
    [InlineData("""{"type":"set_key_image","device":"sim-1","key":1,"format":"jpeg","id":9}""", "invalid_message")]
    [InlineData("""{"type":"teleport","device":"sim-1","id":9}""", "invalid_message")]
    public async Task Bad_commands_get_an_error_result(string command, string code)
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        await client.SendAsync((JsonObject)JsonNode.Parse(command)!);
        var result = await client.ReceiveAsync();
        Assert.Equal("result", (string?)result["type"]);
        Assert.Equal(9, (int)result["id"]!);
        Assert.False((bool)result["ok"]!);
        Assert.Equal(code, (string?)result["error"]!["code"]);
    }

    [Fact]
    public async Task Failure_without_id_is_reported_as_error_and_session_continues()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        await client.SendAsync(new JsonObject { ["type"] = "teleport" });
        var error = await client.ReceiveAsync();
        Assert.Equal("error", (string?)error["type"]);
        Assert.Equal("invalid_message", (string?)error["code"]);
        Assert.Equal("teleport", (string?)error["request"]);

        await client.SendAsync(new JsonObject { ["type"] = "identify", ["device"] = "sim-1", ["id"] = 5 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
    }
}

public sealed class EventTests
{
    [Fact]
    public async Task Key_presses_are_reported()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        bridge.Deck.Press(3, true);
        bridge.Deck.Press(3, false);

        var down = await client.ReceiveAsync();
        Assert.Equal("key", (string?)down["type"]);
        Assert.Equal("sim-1", (string?)down["device"]);
        Assert.Equal(3, (int)down["key"]!);
        Assert.True((bool)down["pressed"]!);
        Assert.False((bool)(await client.ReceiveAsync())["pressed"]!);
    }

    [Fact]
    public async Task Unplug_and_replug_keep_the_device_id()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        bridge.Simulator.SetPlugged("sim-1", false);
        var removed = await client.ReceiveAsync();
        Assert.Equal("device_removed", (string?)removed["type"]);
        Assert.Equal("sim-1", (string?)removed["device"]);

        // Unplugged devices take no commands
        await client.SendAsync(new JsonObject { ["type"] = "set_brightness", ["device"] = "sim-1", ["percent"] = 10, ["id"] = 1 });
        Assert.Equal("unknown_device", (string?)(await client.ReceiveAsync())["error"]!["code"]);

        bridge.Simulator.SetPlugged("sim-1", true);
        var added = await client.ReceiveAsync();
        Assert.Equal("device_added", (string?)added["type"]);
        Assert.Equal("sim-1", (string?)added["device"]!["id"]);
    }
}
