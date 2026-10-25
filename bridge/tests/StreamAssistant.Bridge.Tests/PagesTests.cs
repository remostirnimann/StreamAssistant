using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;

namespace StreamAssistant.Bridge.Tests;

/// <summary>The local status page, the simulator page and its WebSocket.</summary>
public sealed class PagesTests
{
    [Fact]
    public async Task Status_page_and_api()
    {
        await using var bridge = new TestBridge();
        using var http = bridge.CreateClient();
        var page = await http.GetStringAsync("/", TestContext.Current.CancellationToken);
        Assert.Contains("Stream Assistant Bridge", page);
        var status = JsonNode.Parse(await http.GetStringAsync("/api/status", TestContext.Current.CancellationToken))!;
        Assert.Equal("Test bridge", (string?)status["bridge"]!["name"]);
        // Test requests count as local: the code is shown
        Assert.Equal(bridge.Pairing.Code, (string?)status["pairing_code"]);
        Assert.Equal("sim-1", (string?)status["devices"]![0]!["id"]);
        Assert.Null((string?)status["client"]);
        Assert.Contains("Simulator", await http.GetStringAsync("/sim", TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task WebSocket_endpoints_need_a_websocket()
    {
        await using var bridge = new TestBridge();
        using var http = bridge.CreateClient();
        Assert.Equal(HttpStatusCode.UpgradeRequired, (await http.GetAsync("/ws", TestContext.Current.CancellationToken)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await http.GetAsync("/sim/ws", TestContext.Current.CancellationToken)).StatusCode);
    }

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

    [Fact]
    public async Task Simulator_page_shows_and_drives_the_deck()
    {
        await using var bridge = new TestBridge();
        var socket = await bridge.Server.CreateWebSocketClient().ConnectAsync(new Uri(bridge.Server.BaseAddress, "sim/ws"), CancellationToken.None);
        var state = await NextAsync(socket, "state");
        var device = state["devices"]![0]!;
        Assert.Equal(5, (int)device["cols"]!);
        Assert.True((bool)device["plugged"]!);

        // Changes from Home Assistant show up on the page
        await bridge.Deck.SetKeyColorAsync(1, "#ff0000", CancellationToken.None);
        Assert.Equal("#ff0000", (string?)(await NextAsync(socket, "key"))["content"]!["color"]);
        await bridge.Deck.SetKeyImageAsync(2, "jpeg", new byte[] { 1, 2, 3 }, CancellationToken.None);
        Assert.StartsWith("data:image/jpeg;base64,", (string?)(await NextAsync(socket, "key"))["content"]!["image"]);
        await bridge.Deck.SetBrightnessAsync(20, CancellationToken.None);
        var updated = await NextAsync(socket, "device");
        Assert.Equal(20, (int)updated["brightness"]!);
        Assert.Equal("#ff0000", (string?)updated["keys"]!["1"]!["color"]);
        await bridge.Deck.IdentifyAsync(CancellationToken.None);
        await NextAsync(socket, "identify");

        // Presses from the page reach the deck; garbage is ignored
        var presses = new List<bool>();
        bridge.Deck.Input += (_, input) => presses.Add(((Devices.KeyInput)input).Pressed);
        await SendAsync(socket, "not json");
        await SendAsync(socket, """{"type":"press","device":"nope","key":1,"pressed":true}""");
        await SendAsync(socket, """{"type":"press","device":"sim-1","key":"x","pressed":true}""");
        await SendAsync(socket, """{"type":"press","device":"sim-1","key":1,"pressed":true}""");
        await SendAsync(socket, """{"type":"plug","device":"sim-1","plugged":false}""");
        Assert.False((bool)(await NextAsync(socket, "device"))["plugged"]!);
        // Unplugged decks ignore presses
        await SendAsync(socket, """{"type":"press","device":"sim-1","key":2,"pressed":true}""");
        await SendAsync(socket, """{"type":"plug","device":"sim-1","plugged":true}""");
        Assert.True((bool)(await NextAsync(socket, "device"))["plugged"]!);
        Assert.Equal([true], presses);

        await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, null, CancellationToken.None);
    }
}
