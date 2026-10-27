using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Tests;

/// <summary>Dials and touch strips: capabilities, touch images and input, simulated like a Stream Deck +.</summary>
public sealed class DialTouchTests
{
    private static async Task<JsonObject> NextAsync(WebSocket socket, string type)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var buffer = new byte[1024 * 1024];
        while (true)
        {
            var result = await socket.ReceiveAsync(buffer, timeout.Token);
            var message = (JsonObject)JsonNode.Parse(buffer.AsSpan(0, result.Count))!;
            if ((string?)message["type"] == type)
            {
                return message;
            }
        }
    }

    private static Task SendAsync(WebSocket socket, string text) =>
        socket.SendAsync(Encoding.UTF8.GetBytes(text), WebSocketMessageType.Text, true, CancellationToken.None);

    private static JsonObject TouchHeader(int x, int y, int width, int height, string format = "jpeg") => new()
    {
        ["type"] = "set_touch_image",
        ["device"] = "sim-1",
        ["x"] = x,
        ["y"] = y,
        ["width"] = width,
        ["height"] = height,
        ["format"] = format,
        ["id"] = 1,
    };

    [Theory]
    [InlineData("4x2:9")]
    [InlineData("4x2:0")]
    [InlineData("4x2:1:2")]
    [InlineData("plux")]
    public void Simulated_decks_are_checked(string text) =>
        Assert.Throws<ArgumentException>(() => SimulatedDeck.Parse(text));

    [Fact]
    public async Task Plus_reports_dials_and_touch_and_takes_touch_images()
    {
        await using var bridge = new TestBridge(simulate: "plus");
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        var caps = bridge.Deck.Info.ToJson()["capabilities"]!;
        Assert.Equal(120, (int)caps["keys"]!["image"]!["width"]!);
        Assert.Equal(4, (int)caps["dials"]!["count"]!);
        Assert.Equal(800, (int)caps["touch"]!["width"]!);

        await client.SendBinaryAsync(TouchHeader(200, 0, 200, 100), [1, 2, 3]);
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        await client.SendBinaryAsync(TouchHeader(0, 0, 800, 100, "png"), [4]);
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        await client.SendBinaryAsync(TouchHeader(400, 0, 200, 100), [5]);
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        // The full strip covered the first image
        Assert.Equal([(0, 800), (400, 200)], bridge.Deck.TouchImages.Select(i => (i.X, i.Width)));

        foreach (var (header, payload) in new[]
        {
            (TouchHeader(700, 0, 200, 100), new byte[] { 1 }),  // wider than the strip
            (TouchHeader(0, 0, 200, 100, "bmp"), new byte[] { 1 }),
            (TouchHeader(0, 0, 200, 100), Array.Empty<byte>()),
        })
        {
            await client.SendBinaryAsync(header, payload);
            Assert.Equal("invalid_message", (string?)(await client.ReceiveAsync())["error"]!["code"]);
        }

        await bridge.Deck.ResetAsync(CancellationToken.None);
        Assert.Empty(bridge.Deck.TouchImages);
    }

    [Fact]
    public async Task Touch_images_need_a_touch_display()
    {
        await using var bridge = new TestBridge();
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        await client.SendBinaryAsync(TouchHeader(0, 0, 10, 10), [1]);
        Assert.Equal("unsupported", (string?)(await client.ReceiveAsync())["error"]!["code"]);
    }

    [Fact]
    public async Task Simulator_page_turns_pushes_and_touches()
    {
        await using var bridge = new TestBridge(simulate: "4x2:2");
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        var socket = await bridge.Server.CreateWebSocketClient().ConnectAsync(new Uri(bridge.Server.BaseAddress, "sim/ws"), CancellationToken.None);
        var device = (await NextAsync(socket, "state"))["devices"]![0]!;
        Assert.Equal(2, (int)device["dials"]!);
        Assert.Equal(400, (int)device["touch"]!["width"]!);

        // Touch images show up on the page
        await bridge.Deck.SetTouchImageAsync(0, 0, 200, 100, "jpeg", new byte[] { 1 }, CancellationToken.None);
        Assert.Equal(200, (int)(await NextAsync(socket, "touch"))["image"]!["width"]!);
        Assert.Single(bridge.Deck.TouchImages);

        await SendAsync(socket, """{"type":"turn","device":"sim-1","dial":1,"delta":-2}""");
        var turned = await client.ReceiveAsync();
        Assert.Equal(("dial", 1, -2), ((string?)turned["type"], (int)turned["dial"]!, (int)turned["delta"]!));
        await SendAsync(socket, """{"type":"turn","device":"sim-1","dial":5,"delta":1}""");  // no such dial
        await SendAsync(socket, """{"type":"dial_press","device":"sim-1","dial":0,"pressed":true}""");
        Assert.True((bool)(await client.ReceiveAsync())["pressed"]!);
        await SendAsync(socket, """{"type":"touch","device":"sim-1","kind":"tap","x":250,"y":40}""");
        var tap = await client.ReceiveAsync();
        Assert.Equal(("touch", "tap", 250, 40), ((string?)tap["type"], (string?)tap["kind"], (int)tap["x"]!, (int)tap["y"]!));
        Assert.Null(tap["x2"]);
        await SendAsync(socket, """{"type":"touch","device":"sim-1","kind":"pinch","x":1,"y":1}""");  // unknown kind
        await SendAsync(socket, """{"type":"touch","device":"sim-1","kind":"swipe","x":10,"y":50,"x2":900,"y2":50}""");
        var swipe = await client.ReceiveAsync();
        Assert.Equal(("swipe", 399), ((string?)swipe["kind"], (int)swipe["x2"]!));

        await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, null, CancellationToken.None);
    }
}
