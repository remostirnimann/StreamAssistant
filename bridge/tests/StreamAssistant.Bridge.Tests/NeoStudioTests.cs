using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Logging.Abstractions;
using StbImageSharp;
using StbImageWriteSharp;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Devices.Elgato;
using ReadComponents = StbImageSharp.ColorComponents;
using WriteComponents = StbImageWriteSharp.ColorComponents;

namespace StreamAssistant.Bridge.Tests;

/// <summary>Stream Deck Neo (page buttons, info screen) and Studio (wide keys, LED rings, NFC).</summary>
public sealed class NeoStudioTests
{
    private static readonly ElgatoModel Neo = ElgatoModel.ByAlias("neo")!;
    private static readonly ElgatoModel Studio = ElgatoModel.ByAlias("studio")!;

    private static async Task WaitForAsync(Func<bool> condition)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (!condition())
        {
            await Task.Delay(10, timeout.Token);
        }
    }

    private static byte[] Png(int width, int height, byte red, byte green, byte blue)
    {
        var data = new byte[width * height * 3];
        for (var i = 0; i < data.Length; i += 3)
        {
            (data[i], data[i + 1], data[i + 2]) = (red, green, blue);
        }
        using var output = new MemoryStream();
        new ImageWriter().WritePng(data, width, height, WriteComponents.RedGreenBlue, output);
        return output.ToArray();
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

    [Fact]
    public void Capabilities_and_reports()
    {
        Assert.Equal(Neo, ElgatoModel.Find(ElgatoModel.VendorId, 0x009A));
        Assert.Equal(Studio, ElgatoModel.Find(ElgatoModel.VendorId, 0x00AA));
        Assert.Null(ElgatoModel.ByAlias("nope"));

        var neo = new DeviceInfo("n", "Elgato", "Neo", "Neo", null, null, false, Neo.Capabilities()).ToJson()["capabilities"]!;
        Assert.Equal(2, (int)neo["buttons"]!["count"]!);
        Assert.True((bool)neo["buttons"]!["colors"]!);
        Assert.Equal((248, 58), ((int)neo["screen"]!["width"]!, (int)neo["screen"]!["height"]!));
        Assert.Null(neo["nfc"]);

        var studio = new DeviceInfo("s", "Elgato", "Studio", "Studio", null, null, false, Studio.Capabilities()).ToJson()["capabilities"]!;
        Assert.Equal((144, 112), ((int)studio["keys"]!["image"]!["width"]!, (int)studio["keys"]!["image"]!["height"]!));
        Assert.Equal(24, (int)studio["dials"]!["ring"]!);
        Assert.True((bool)studio["nfc"]!);
        Assert.Null(studio["touch"]);

        // Neo: page buttons follow the 8 keys; the screen has its own 8-byte header
        Assert.Equal([0x03, 0x06, 9, 1, 2, 3], Neo.ButtonColorReport(1, 1, 2, 3));
        var screen = ElgatoModel.ScreenReports(new byte[1500]).ToList();
        Assert.Equal(2, screen.Count);
        Assert.Equal([0x02, 0x0B, 0, 0, 0xF8, 0x03, 0, 0], screen[0][..8]);
        Assert.Equal([0x02, 0x0B, 0, 1, 0xE4, 0x01, 1, 0], screen[1][..8]);

        // Studio: centre colour, then the ring with the lit share; the right ring starts half a turn on
        var left = Studio.DialLedReports(0, 255, 0, 0, 0.25).ToList();
        Assert.Equal([0x02, 0x10, 0, 255, 0, 0], left[0][..6]);
        Assert.Equal([0x02, 0x0F, 0], left[1][..3]);
        Assert.Equal(6, Enumerable.Range(0, 24).Count(led => left[1][3 + (led * 3)] == 255));
        Assert.Equal(255, left[1][3]);
        var right = Studio.DialLedReports(1, 255, 0, 0, 0.25).ToList()[1];
        Assert.Equal(0, right[3]);
        Assert.Equal(255, right[3 + (12 * 3)]);
        Assert.All(Studio.DialLedReports(0, 9, 9, 9, 5).ToList()[1].Skip(3).Take(72), b => Assert.Equal(9, b));
    }

    [Fact]
    public void Inputs()
    {
        var neo = new ElgatoModel.InputParser(Neo);
        var report = new byte[512];
        report[0] = 0x01;
        report[4 + 3] = 1;
        report[4 + 9] = 1;
        Assert.Equal([new KeyInput(3, true), new ButtonInput(1, true)], neo.Parse(report, 512));
        report[4 + 9] = 0;
        Assert.Equal([new ButtonInput(1, false)], neo.Parse(report, 512));

        var studio = new ElgatoModel.InputParser(Studio);
        var tag = new byte[512];
        tag[0] = 0x01;
        tag[1] = 0x04;
        tag[2] = 10;
        Encoding.ASCII.GetBytes("04A2B3C4D5").CopyTo(tag, 4);
        Assert.Equal([new NfcInput("04A2B3C4D5")], studio.Parse(tag, 512));
        Assert.Empty(studio.Parse(tag, 8)); // cut short
        tag[2] = 0;
        Assert.Empty(studio.Parse(tag, 512)); // empty
        tag[2] = 2;
        tag[4] = 0;
        tag[5] = 0;
        Assert.Empty(studio.Parse(tag, 512)); // only zeros
        Assert.Empty(neo.Parse(tag, 512)); // no NFC on the Neo
    }

    [Fact]
    public void Square_images_get_borders_on_wide_keys()
    {
        var fitted = KeyImages.Fit(Png(72, 72, 255, 0, 0), 144, 112);
        Assert.Equal(144 * 112 * 3, fitted.Length);
        Assert.Equal(0, fitted[(56 * 144 * 3) + 3]); // left border
        Assert.Equal(255, fitted[((56 * 144) + 72) * 3]); // centre
        // Same shape: just scaled
        Assert.Equal(96 * 96 * 3, KeyImages.Fit(Png(48, 48, 1, 2, 3), 96, 96).Length);
    }

    [Fact]
    public async Task Neo_lights_buttons_and_shows_the_screen()
    {
        var hid = new FakeHid("NEO001");
        using var deck = ElgatoDeck.Start(hid, Neo, "NEO001", TimeProvider.System, NullLogger.Instance);
        await deck.SetButtonColorAsync(0, "#ffffff", CancellationToken.None);
        await deck.SetScreenImageAsync("png", Png(248, 58, 0, 0, 255), CancellationToken.None);
        await WaitForAsync(() => hid.Features.Count == 1 && hid.Writes.Any(r => r[3] == 1));
        Assert.Equal([0x03, 0x06, 8, 255, 255, 255], hid.Features[0]);
        Assert.All(hid.Writes, r => Assert.Equal((0x02, 0x0B), (r[0], r[1])));

        foreach (var call in new Func<Task>[]
        {
            () => deck.SetButtonColorAsync(2, "#ffffff", CancellationToken.None),
            () => deck.SetDialLedsAsync(0, "#ffffff", 1, CancellationToken.None),
        })
        {
            Assert.Equal("unsupported", (await Assert.ThrowsAsync<DeviceException>(call)).Code);
        }

        var inputs = new ConcurrentQueue<DeviceInput>();
        deck.Input += (_, input) => inputs.Enqueue(input);
        var press = new byte[512];
        press[0] = 0x01;
        press[4 + 8] = 1;
        hid.Send(press);
        await WaitForAsync(() => inputs.Count == 1);
        Assert.Equal(new ButtonInput(0, true), inputs.Single());
    }

    [Fact]
    public async Task Studio_draws_wide_keys_and_lights_dials()
    {
        var hid = new FakeHid("STU001");
        using var deck = ElgatoDeck.Start(hid, Studio, "STU001", TimeProvider.System, NullLogger.Instance);
        await deck.SetKeyImageAsync(31, "png", Png(112, 112, 0, 255, 0), CancellationToken.None);
        await WaitForAsync(() => hid.Writes.Any(r => r[1] == 0x07 && r[3] == 1));
        var jpeg = hid.Writes.Where(r => r[1] == 0x07).SelectMany(r => r.AsSpan(8, r[4] | (r[5] << 8)).ToArray()).ToArray();
        var image = ImageResult.FromMemory(jpeg, ReadComponents.RedGreenBlue);
        Assert.Equal((144, 112), (image.Width, image.Height));

        await deck.SetDialLedsAsync(1, "#00ff00", 0.5, CancellationToken.None);
        await WaitForAsync(() => hid.Writes.Any(r => r[1] == 0x0F));
        Assert.Contains(hid.Writes, r => r[1] == 0x10 && r[2] == 1 && r[4] == 255);

        Assert.Equal("unsupported", (await Assert.ThrowsAsync<DeviceException>(() => deck.SetScreenImageAsync("png", Png(2, 2, 0, 0, 0), CancellationToken.None))).Code);
        Assert.Equal("unsupported", (await Assert.ThrowsAsync<DeviceException>(() => deck.SetDialLedsAsync(2, "#ffffff", 1, CancellationToken.None))).Code);
    }

    [Fact]
    public async Task Protocol_commands_for_buttons_screen_and_leds()
    {
        await using var bridge = new TestBridge(simulate: "neo,studio");
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        var neo = bridge.Simulator.Devices[0];
        var studio = bridge.Simulator.Devices[1];

        async Task<JsonObject> Command(JsonObject command)
        {
            command["id"] = 1;
            await client.SendAsync(command);
            return await client.ReceiveAsync();
        }

        Assert.True((bool)(await Command(new JsonObject { ["type"] = "set_button_color", ["device"] = "sim-1", ["button"] = 1, ["color"] = "#FF0000" }))["ok"]!);
        Assert.Equal("#ff0000", neo.GetButtonColor(1));
        Assert.True((bool)(await Command(new JsonObject { ["type"] = "set_dial_leds", ["device"] = "sim-2", ["dial"] = 0, ["color"] = "#00ff00", ["level"] = 0.5 }))["ok"]!);
        Assert.Equal(new Devices.Virtual.VirtualDevice.DialLeds("#00ff00", 0.5), studio.GetDialLeds(0));
        Assert.True((bool)(await Command(new JsonObject { ["type"] = "set_dial_leds", ["device"] = "sim-2", ["dial"] = 1, ["color"] = "#0000ff" }))["ok"]!);
        Assert.Equal(1.0, studio.GetDialLeds(1)!.Level);
        await client.SendBinaryAsync(new JsonObject { ["type"] = "set_screen_image", ["device"] = "sim-1", ["format"] = "png", ["id"] = 2 }, [1, 2]);
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        Assert.Equal("png", neo.Screen!.Value.Format);

        foreach (var (command, code) in new (JsonObject, string)[]
        {
            (new JsonObject { ["type"] = "set_button_color", ["device"] = "sim-2", ["button"] = 0, ["color"] = "#ffffff" }, "unsupported"),
            (new JsonObject { ["type"] = "set_button_color", ["device"] = "sim-1", ["button"] = 0, ["color"] = "red" }, "invalid_message"),
            (new JsonObject { ["type"] = "set_dial_leds", ["device"] = "sim-1", ["dial"] = 0, ["color"] = "#ffffff" }, "unsupported"),
            (new JsonObject { ["type"] = "set_dial_leds", ["device"] = "sim-2", ["dial"] = 0, ["color"] = "#ffffff", ["level"] = 2 }, "invalid_message"),
            (new JsonObject { ["type"] = "set_dial_leds", ["device"] = "sim-2", ["dial"] = 0, ["color"] = "#ffffff", ["level"] = "half" }, "invalid_message"),
            (new JsonObject { ["type"] = "set_screen_image", ["device"] = "sim-2", ["format"] = "png" }, "unsupported"),
            (new JsonObject { ["type"] = "set_screen_image", ["device"] = "sim-1", ["format"] = "bmp" }, "invalid_message"),
            (new JsonObject { ["type"] = "set_screen_image", ["device"] = "sim-1", ["format"] = "png" }, "invalid_message"),
        })
        {
            Assert.Equal(code, (string?)(await Command(command))["error"]!["code"]);
        }

        // Reset clears everything
        await neo.ResetAsync(CancellationToken.None);
        Assert.Null(neo.GetButtonColor(1));
        Assert.Null(neo.Screen);
    }

    [Fact]
    public async Task Simulator_page_presses_buttons_and_reads_tags()
    {
        await using var bridge = new TestBridge(simulate: "neo,studio");
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        var socket = await bridge.Server.CreateWebSocketClient().ConnectAsync(new Uri(bridge.Server.BaseAddress, "sim/ws"), CancellationToken.None);
        var devices = (await NextAsync(socket, "state"))["devices"]!;
        Assert.Equal(2, devices[0]!["buttons"]!.AsArray().Count);
        Assert.Equal(248, (int)devices[0]!["screen"]!["width"]!);
        Assert.True((bool)devices[1]!["nfc"]!);
        Assert.Equal(2, devices[1]!["dial_leds"]!.AsArray().Count);

        await bridge.Simulator.Devices[0].SetButtonColorAsync(0, "#ffffff", CancellationToken.None);
        Assert.Equal("#ffffff", (string?)(await NextAsync(socket, "device"))["buttons"]![0]);

        async Task Send(string text) => await socket.SendAsync(Encoding.UTF8.GetBytes(text), WebSocketMessageType.Text, true, CancellationToken.None);
        await Send("""{"type":"button","device":"sim-1","button":1,"pressed":true}""");
        var button = await client.ReceiveAsync();
        Assert.Equal(("button", 1, true), ((string?)button["type"], (int)button["button"]!, (bool)button["pressed"]!));
        await Send("""{"type":"button","device":"sim-1","button":5,"pressed":true}""");   // no such button
        await Send("""{"type":"nfc","device":"sim-1","id":"04A2"}""");                      // the Neo has no reader
        await Send("""{"type":"nfc","device":"sim-2","id":"  "}""");                        // empty
        await Send("""{"type":"nfc","device":"sim-2","id":" 04A2B3C4D5 "}""");
        var tag = await client.ReceiveAsync();
        Assert.Equal(("nfc", "04A2B3C4D5"), ((string?)tag["type"], (string?)tag["id"]));

        await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, null, CancellationToken.None);
    }
}
