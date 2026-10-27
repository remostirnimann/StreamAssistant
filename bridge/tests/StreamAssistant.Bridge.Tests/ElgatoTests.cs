using System.Collections.Concurrent;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using StbImageSharp;
using StbImageWriteSharp;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Devices.Elgato;
using ReadComponents = StbImageSharp.ColorComponents;
using WriteComponents = StbImageWriteSharp.ColorComponents;

namespace StreamAssistant.Bridge.Tests;

/// <summary>A Gen2 deck on a pretend USB port: records reports, plays back input.</summary>
internal sealed class FakeHid(string serial = "AL12K1A01234") : IHidDevice
{
    private readonly BlockingCollection<byte[]?> _input = [];
    private readonly Lock _lock = new();
    private readonly List<byte[]> _writes = [];
    private readonly List<byte[]> _features = [];

    public Exception? WriteFailure { get; set; }

    public bool Disposed { get; private set; }

    public int InputReportLength => 512;

    public List<byte[]> Writes
    {
        get
        {
            lock (_lock)
            {
                return [.. _writes];
            }
        }
    }

    public List<byte[]> Features
    {
        get
        {
            lock (_lock)
            {
                return [.. _features];
            }
        }
    }

    /// <summary>Key states as the deck reports them.</summary>
    public void Keys(params int[] pressed)
    {
        var report = new byte[512];
        report[0] = 0x01;
        foreach (var key in pressed)
        {
            report[4 + key] = 1;
        }
        _input.Add(report);
    }

    public void Send(byte[] report) => _input.Add(report);

    /// <summary>The cable is pulled: the next read fails.</summary>
    public void Unplug() => _input.Add(null);

    public void Write(byte[] report)
    {
        if (WriteFailure is { } failure)
        {
            throw failure;
        }
        lock (_lock)
        {
            _writes.Add(report);
        }
    }

    public void SetFeature(byte[] report)
    {
        lock (_lock)
        {
            _features.Add(report);
        }
    }

    /// <summary>Firmware in report 0xA1 (Mini); null: the report fails.</summary>
    public string? MiniFirmware { get; set; }

    public byte[] GetFeature(byte reportId)
    {
        var report = new byte[32];
        report[0] = reportId;
        switch (reportId)
        {
            case 0x05 or 0x06:
                // Gen2: length in byte 1, firmware from byte 6, serial from byte 2
                var text = reportId == 0x05 ? "\0\0\0\01.01.000" : serial;
                Encoding.ASCII.GetBytes(text).CopyTo(report, 2);
                report[1] = (byte)text.Length;
                break;
            case 0xA1 when MiniFirmware is null:
                throw new IOException("Report not supported");
            case 0x03 or 0x04 or 0xA1:
                // First generation: text from byte 5
                Encoding.ASCII.GetBytes(reportId switch { 0x03 => serial, 0x04 => "1.0.170133", _ => MiniFirmware! }).CopyTo(report, 5);
                break;
        }
        return report;
    }

    public int Read(byte[] buffer)
    {
        try
        {
            var report = _input.Take() ?? throw new IOException("Device disconnected");
            report.CopyTo(buffer, 0);
            return report.Length;
        }
        catch (InvalidOperationException)
        {
            throw new ObjectDisposedException(nameof(FakeHid));
        }
    }

    public void Dispose()
    {
        Disposed = true;
        _input.CompleteAdding();
    }
}

/// <summary>The USB bus: devices can be plugged in and out, listing and opening can fail.</summary>
internal sealed class FakeHidBackend : IHidBackend
{
    private readonly Lock _lock = new();
    private readonly Dictionary<string, (HidDeviceEntry Entry, FakeHid Device)> _devices = [];

    public event Action? Changed;

    public Exception? ListFailure { get; set; }

    public Exception? OpenFailure { get; set; }

    public int OpenAttempts { get; private set; }

    public int ListCalls { get; private set; }

    public FakeHid Plug(string path, int productId = 0x0080, string? usbSerial = "AL12K1A01234", int vendorId = ElgatoModel.VendorId)
    {
        var device = new FakeHid(usbSerial ?? "FEATURE-SERIAL");
        lock (_lock)
        {
            _devices[path] = (new HidDeviceEntry(path, vendorId, productId, usbSerial), device);
        }
        Changed?.Invoke();
        return device;
    }

    /// <summary>The same port with a fresh device (after the old one failed).</summary>
    public FakeHid Replug(string path)
    {
        lock (_lock)
        {
            var entry = _devices[path].Entry;
            var device = new FakeHid(entry.Serial ?? "FEATURE-SERIAL");
            _devices[path] = (entry, device);
            return device;
        }
    }

    public void Unplug(string path)
    {
        lock (_lock)
        {
            _devices.Remove(path);
        }
        Changed?.Invoke();
    }

    public void Poke() => Changed?.Invoke();

    public IReadOnlyList<HidDeviceEntry> List(int vendorId)
    {
        ListCalls++;
        if (ListFailure is { } failure)
        {
            throw failure;
        }
        lock (_lock)
        {
            return _devices.Values.Select(d => d.Entry).Where(e => e.VendorId == vendorId).ToList();
        }
    }

    public IHidDevice Open(string path)
    {
        OpenAttempts++;
        if (OpenFailure is { } failure)
        {
            throw failure;
        }
        lock (_lock)
        {
            return _devices.TryGetValue(path, out var device) ? device.Device : throw new IOException("gone");
        }
    }
}

public sealed class ElgatoTests
{
    private static readonly ElgatoModel Mk2 = ElgatoModel.All[0];

    private static async Task WaitForAsync(Func<bool> condition)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        while (!condition())
        {
            await Task.Delay(10, timeout.Token);
        }
    }

    private static byte[] Png(int size, Func<int, int, (byte R, byte G, byte B)> pixel)
    {
        var data = new byte[size * size * 3];
        for (var y = 0; y < size; y++)
        {
            for (var x = 0; x < size; x++)
            {
                var (r, g, b) = pixel(x, y);
                var i = ((y * size) + x) * 3;
                (data[i], data[i + 1], data[i + 2]) = (r, g, b);
            }
        }
        using var output = new MemoryStream();
        new ImageWriter().WritePng(data, size, size, WriteComponents.RedGreenBlue, output);
        return output.ToArray();
    }

    private static (byte R, byte G, byte B) PixelAt(ImageResult image, int x, int y)
    {
        var i = ((y * image.Width) + x) * 3;
        return (image.Data[i], image.Data[i + 1], image.Data[i + 2]);
    }

    /// <summary>The JPEG a key received, put together from its output reports.</summary>
    private static byte[] Jpeg(IEnumerable<byte[]> reports, int key)
    {
        var data = new List<byte>();
        foreach (var report in reports.Where(r => r[2] == key))
        {
            var length = report[4] | (report[5] << 8);
            data.AddRange(report.AsSpan(8, length).ToArray());
        }
        return [.. data];
    }

    private static ElgatoModel Model(string name) => ElgatoModel.All.Single(m => m.Name == name);

    /// <summary>A Stream Deck + input report: type, then the payload from byte 4.</summary>
    private static byte[] PlusReport(byte type, params byte[] payload)
    {
        var report = new byte[512];
        report[0] = 0x01;
        report[1] = type;
        payload.CopyTo(report, 4);
        return report;
    }

    [Fact]
    public void Models_and_reports()
    {
        Assert.Equal("Stream Deck XL", ElgatoModel.Find(ElgatoModel.VendorId, 0x008F)!.Name);
        Assert.Equal("Stream Deck Mini", ElgatoModel.Find(ElgatoModel.VendorId, 0x0063)!.Name);
        Assert.Null(ElgatoModel.Find(ElgatoModel.VendorId, 0x00C6)); // + XL: not supported
        Assert.Null(ElgatoModel.Find(0x1234, 0x0080));
        Assert.Equal(15, Mk2.KeyCount);

        var reports = Mk2.ImageReports(4, new byte[2000]).ToList();
        Assert.Equal(2, reports.Count);
        Assert.All(reports, r => Assert.Equal(1024, r.Length));
        Assert.Equal([0x02, 0x07, 4, 0, 0xF8, 0x03, 0, 0], reports[0][..8]);
        Assert.Equal([0x02, 0x07, 4, 1, 0xD8, 0x03, 1, 0], reports[1][..8]);
        var empty = Assert.Single(Mk2.ImageReports(0, []));
        Assert.Equal(1, empty[3]);

        Assert.Equal([0x03, 0x08, 100], Mk2.BrightnessReport(150)[..3]);
        Assert.Equal(0, Mk2.BrightnessReport(-5)[2]);
        Assert.Equal([0x03, 0x02], Mk2.ResetReport()[..2]);
        Assert.Equal([0x03, 0x06, 7, 1, 2, 3], Mk2.ColorReport(7, 1, 2, 3));

        // First generation: other feature reports, no colour fill
        var mini = Model("Stream Deck Mini");
        Assert.Equal([0x05, 0x55, 0xAA, 0xD1, 0x01, 30], mini.BrightnessReport(30)[..6]);
        Assert.Equal(17, mini.BrightnessReport(30).Length);
        Assert.Equal([0x0B, 0x63], mini.ResetReport()[..2]);
        Assert.Null(mini.ColorReport(0, 1, 2, 3));

        // Mini: 1024-byte packets with a 16-byte header, key + 1, parts from 0
        var miniReports = mini.ImageReports(2, new byte[2000]).ToList();
        Assert.Equal(2, miniReports.Count);
        Assert.Equal([0x02, 0x01, 0, 0, 0, 3], miniReports[0][..6]);
        Assert.Equal([0x02, 0x01, 1, 0, 1, 3], miniReports[1][..6]);

        // First Stream Deck: two 8191-byte packets, halves of the image, parts 1 and 2, keys from the right
        var original = Model("Stream Deck");
        var halves = original.ImageReports(0, [.. Enumerable.Repeat((byte)7, 100), .. Enumerable.Repeat((byte)9, 100)]).ToList();
        Assert.Equal(2, halves.Count);
        Assert.All(halves, r => Assert.Equal(8191, r.Length));
        Assert.Equal([0x02, 0x01, 1, 0, 0, 5], halves[0][..6]);
        Assert.Equal([0x02, 0x01, 2, 0, 1, 5], halves[1][..6]);
        Assert.Equal((7, 9), (halves[0][16], halves[1][16]));
        Assert.Equal([4, 3, 2, 1, 0, 9, 8], Enumerable.Range(0, 7).Select(original.HidKey));

        // Touch strip: 16-byte header with the area
        var touch = Assert.Single(ElgatoModel.TouchReports(200, 0, 200, 100, new byte[500]));
        Assert.Equal([0x02, 0x0C, 200, 0, 0, 0, 200, 0, 100, 0, 1, 0, 0, 0xF4, 0x01], touch[..15]);
    }

    [Fact]
    public void Capabilities_per_model()
    {
        var plus = Model("Stream Deck +").Capabilities();
        Assert.Equal((4, 2, 120), (plus.Keys!.Cols, plus.Keys.Rows, plus.Keys.ImageWidth));
        Assert.Equal(4, plus.Dials!.Count);
        Assert.Equal((800, 100), (plus.Touch!.Width, plus.Touch.Height));

        var pedal = Model("Stream Deck Pedal").Capabilities();
        Assert.True(pedal.Keys!.InputOnly);
        Assert.False(pedal.Brightness);
        var json = new DeviceInfo("p", "Elgato", "Pedal", "Pedal", null, null, false, pedal).ToJson()["capabilities"]!;
        Assert.Null(json["keys"]!["image"]);
        Assert.Null(json["keys"]!["colors"]);
        Assert.Null(json["brightness"]);
    }

    [Fact]
    public void Report_strings()
    {
        var firmware = new byte[32];
        firmware[1] = 12;
        Encoding.ASCII.GetBytes("1.01.000").CopyTo(firmware, 6);
        Assert.Equal("1.01.000", ElgatoModel.ReportString(firmware, 6));

        // A length that does not fit: read to the end, stop at the first zero, drop control characters
        var serial = new byte[32];
        serial[1] = 200;
        Encoding.ASCII.GetBytes("AL12\u0001K1").CopyTo(serial, 2);
        Assert.Equal("AL12K1", ElgatoModel.ReportString(serial, 2));
        Assert.Equal("", ElgatoModel.ReportString([6], 2));

        var gen1 = new byte[17];
        Encoding.ASCII.GetBytes("BL1234\u0001X").CopyTo(gen1, 5);
        Assert.Equal("BL1234", ElgatoModel.PrintableFrom(gen1, 5));
        Assert.Equal("", ElgatoModel.PrintableFrom([3], 5));
    }

    [Fact]
    public void Input_reports()
    {
        var mk2 = new ElgatoModel.InputParser(Mk2);
        var report = new byte[512];
        report[0] = 0x01;
        report[4 + 2] = 1;
        Assert.Equal([new KeyInput(2, true)], mk2.Parse(report, 512));
        Assert.Empty(mk2.Parse(report, 512)); // no change
        Assert.Empty(mk2.Parse(report, 10)); // too short
        Assert.Empty(mk2.Parse([0x02, 0], 2)); // another report

        // First Stream Deck: keys from byte 1, counted from the right
        var original = new ElgatoModel.InputParser(Model("Stream Deck"));
        var v1 = new byte[17];
        v1[0] = 0x01;
        v1[1] = 1;
        Assert.Equal([new KeyInput(4, true)], original.Parse(v1, 17));

        // Pedal: keys from byte 4, whatever byte 1 says
        var pedal = new ElgatoModel.InputParser(Model("Stream Deck Pedal"));
        var pedals = new byte[512];
        pedals[0] = 0x01;
        pedals[1] = 0x09;
        pedals[5] = 1;
        Assert.Equal([new KeyInput(1, true)], pedal.Parse(pedals, 512));

        // Stream Deck +: touch and dials
        var plus = new ElgatoModel.InputParser(Model("Stream Deck +"));
        Assert.Equal([new TouchInput(TouchInput.Tap, 250, 40)], plus.Parse(PlusReport(0x02, 1, 0, 250, 0, 40, 0), 512));
        Assert.Equal([new TouchInput(TouchInput.Hold, 10, 5)], plus.Parse(PlusReport(0x02, 2, 0, 10, 0, 5, 0), 512));
        Assert.Equal(
            [new TouchInput(TouchInput.Swipe, 700, 50, 100, 52)],
            plus.Parse(PlusReport(0x02, 3, 0, 0xBC, 0x02, 50, 0, 100, 0, 52, 0), 512));
        Assert.Empty(plus.Parse(PlusReport(0x02, 9), 512));
        Assert.Empty(plus.Parse(PlusReport(0x02), 10));
        Assert.Equal([new DialInput(1, 2), new DialInput(3, -1)], plus.Parse(PlusReport(0x03, 0x01, 0, 2, 0, 0xFF), 512));
        Assert.Equal([new DialPressInput(2, true)], plus.Parse(PlusReport(0x03, 0x00, 0, 0, 1, 0), 512));
        Assert.Equal([new DialPressInput(2, false)], plus.Parse(PlusReport(0x03, 0x00, 0, 0, 0, 0), 512));
        Assert.Empty(plus.Parse(PlusReport(0x03), 6));
        Assert.Empty(plus.Parse(PlusReport(0x04, 1, 2), 512)); // NFC: not on this model
        Assert.Empty(mk2.Parse(PlusReport(0x03, 0x01, 1), 512)); // no dials on an MK.2
    }

    [Fact]
    public void Images_are_scaled_and_turned()
    {
        // Red in the top left corner of an upright image ends up bottom right on a Gen2 deck
        var png = Png(144, (x, y) => x < 72 && y < 72 ? ((byte)255, (byte)0, (byte)0) : ((byte)0, (byte)0, (byte)255));
        var key = ImageResult.FromMemory(Mk2.EncodeKey(KeyImages.Decode(png, 72, 72)), ReadComponents.RedGreenBlue);
        Assert.Equal((72, 72), (key.Width, key.Height));
        Assert.True(PixelAt(key, 60, 60).R > 200);
        Assert.True(PixelAt(key, 10, 10).B > 200);

        // The + shows it upright
        var plus = ImageResult.FromMemory(Model("Stream Deck +").EncodeKey(KeyImages.Decode(png, 120, 120)), ReadComponents.RedGreenBlue);
        Assert.True(PixelAt(plus, 10, 10).R > 200);

        // First generation: BMP, the first Stream Deck mirrored, the Mini turned
        var corner = Png(80, (x, y) => x < 10 && y < 10 ? ((byte)255, (byte)0, (byte)0) : ((byte)0, (byte)0, (byte)0));
        var original = Model("Stream Deck").EncodeKey(KeyImages.Decode(corner, 72, 72));
        Assert.Equal((byte)'B', original[0]);
        Assert.Equal(54 + (72 * 72 * 3), original.Length);
        // Rows as stored: the red corner moved to the right end of the first row (blue, green, red)
        Assert.Equal(255, original[54 + (71 * 3) + 2]);
        var mini = Model("Stream Deck Mini").EncodeKey(KeyImages.Decode(corner, 80, 80));
        Assert.Equal(54 + (80 * 80 * 3), mini.Length);
        // Turned and flipped: the corner is at the start of the last row
        Assert.Equal(255, mini[54 + (79 * 80 * 3) + 2]);
        Assert.Equal(80, ImageResult.FromMemory(mini, ReadComponents.RedGreenBlue).Width);

        var solid = KeyImages.Solid("#00ff00", 4, 2);
        Assert.Equal([0, 255, 0], solid[..3]);
        Assert.Equal(24, solid.Length);

        var broken = Assert.Throws<DeviceException>(() => KeyImages.Decode(new byte[] { 1, 2, 3 }, 72, 72));
        Assert.Equal("invalid_message", broken.Code);
    }

    [Fact]
    public async Task Deck_sends_images_brightness_and_reports_keys()
    {
        var hid = new FakeHid();
        using var deck = ElgatoDeck.Start(hid, Mk2, usbSerial: null, TimeProvider.System, NullLogger.Instance);
        Assert.Equal("elgato-AL12K1A01234", deck.Info.Id);
        Assert.Equal("1.01.000", deck.Info.Firmware);
        Assert.Equal(["jpeg", "png"], deck.Info.Capabilities.Keys!.Formats);

        var inputs = new ConcurrentQueue<DeviceInput>();
        deck.Input += (_, input) => inputs.Enqueue(input);

        await deck.SetBrightnessAsync(40, CancellationToken.None);
        await deck.SetKeyImageAsync(3, "png", Png(72, (_, _) => (255, 255, 255)), CancellationToken.None);
        await deck.SetKeyColorAsync(5, "#ff0000", CancellationToken.None);
        await deck.ClearKeyAsync(14, CancellationToken.None);
        await WaitForAsync(() => hid.Writes.Count > 0 && hid.Features.Count == 3);
        Assert.All(hid.Writes, r => Assert.Equal(3, r[2]));
        Assert.Equal(40, hid.Features[0][2]);
        // Colours are filled with a feature report, no image needed
        Assert.Equal([0x03, 0x06, 5, 255, 0, 0], hid.Features[1]);
        Assert.Equal([0x03, 0x06, 14, 0, 0, 0], hid.Features[2]);
        var white = ImageResult.FromMemory(Jpeg(hid.Writes, 3), ReadComponents.RedGreenBlue);
        Assert.True(PixelAt(white, 36, 36).R > 200);

        var wrongKey = await Assert.ThrowsAsync<DeviceException>(() => deck.SetKeyColorAsync(15, "#ffffff", CancellationToken.None));
        Assert.Equal("invalid_message", wrongKey.Code);
        var noTouch = await Assert.ThrowsAsync<DeviceException>(() => deck.SetTouchImageAsync(0, 0, 10, 10, "png", Png(10, (_, _) => (0, 0, 0)), CancellationToken.None));
        Assert.Equal("unsupported", noTouch.Code);

        // Only changes become events; other reports are ignored
        hid.Keys(2);
        hid.Keys(2, 7);
        hid.Send([0x02, 0, 0]);
        hid.Keys();
        await WaitForAsync(() => inputs.Count == 4);
        Assert.Equal(
            [new KeyInput(2, true), new KeyInput(7, true), new KeyInput(2, false), new KeyInput(7, false)],
            inputs.Cast<KeyInput>().ToArray());

        await deck.IdentifyAsync(CancellationToken.None);
        await WaitForAsync(() => hid.Features.Count == 9);
        Assert.Equal([0, 40, 0, 40, 0, 40], hid.Features.Skip(3).Select(f => (int)f[2]));
    }

    [Fact]
    public async Task Plus_draws_the_touch_strip_and_reports_dials()
    {
        var hid = new FakeHid("PLUS01");
        using var deck = ElgatoDeck.Start(hid, Model("Stream Deck +"), "PLUS01", TimeProvider.System, NullLogger.Instance);
        var inputs = new ConcurrentQueue<DeviceInput>();
        deck.Input += (_, input) => inputs.Enqueue(input);

        // A full strip, then a segment on top: both are sent, in that order
        await deck.SetTouchImageAsync(0, 0, 800, 100, "png", Png(80, (_, _) => (0, 0, 255)), CancellationToken.None);
        await deck.SetTouchImageAsync(200, 0, 200, 100, "png", Png(20, (_, _) => (255, 0, 0)), CancellationToken.None);
        await WaitForAsync(() => hid.Writes.Count(r => r[10] == 1) == 2);
        var areas = hid.Writes.Where(r => r[10] == 1).Select(r => r[2] | (r[3] << 8)).ToList();
        Assert.Equal([0, 200], areas);
        var first = hid.Writes[0];
        Assert.Equal((0x02, 0x0C, 800 & 0xFF, 800 >> 8), (first[0], first[1], first[6], first[7]));

        hid.Send(PlusReport(0x03, 0x01, 1, 0, 0, 0));
        hid.Send(PlusReport(0x02, 1, 0, 30, 1, 50, 0));
        await WaitForAsync(() => inputs.Count == 2);
        Assert.Equal([new DialInput(0, 1), new TouchInput(TouchInput.Tap, 286, 50)], inputs.ToArray());
    }

    [Fact]
    public async Task First_generation_decks_get_bitmaps()
    {
        var hid = new FakeHid("BL0001") { MiniFirmware = "3.00.000" };
        using (var mini = ElgatoDeck.Start(hid, Model("Stream Deck Mini"), usbSerial: null, TimeProvider.System, NullLogger.Instance))
        {
            Assert.Equal(("elgato-BL0001", "3.00.000"), (mini.Info.Id, mini.Info.Firmware));
            await mini.SetKeyColorAsync(1, "#0000ff", CancellationToken.None);
            await mini.SetBrightnessAsync(50, CancellationToken.None);
            await WaitForAsync(() => hid.Writes.Count > 0 && hid.Writes[^1][4] == 1 && hid.Features.Count == 1);
            Assert.Equal(2, hid.Writes[0][5]);
            Assert.Equal((byte)'B', hid.Writes[0][16]);
            Assert.Equal([0x05, 0x55, 0xAA, 0xD1, 0x01, 50], hid.Features[0][..6]);
        }

        // The first Stream Deck: firmware from report 0x04, keys counted from the right
        var v1 = new FakeHid("CL0001");
        using var original = ElgatoDeck.Start(v1, Model("Stream Deck"), null, TimeProvider.System, NullLogger.Instance);
        Assert.Equal("1.0.170133", original.Info.Firmware);
        await original.ClearKeyAsync(0, CancellationToken.None);
        await WaitForAsync(() => v1.Writes.Count == 2);
        Assert.All(v1.Writes, r => Assert.Equal(5, r[5]));

        // A Mini without report 0xA1 falls back to 0x04
        var older = new FakeHid("BL0002");
        using var oldMini = ElgatoDeck.Start(older, Model("Stream Deck Mini"), null, TimeProvider.System, NullLogger.Instance);
        Assert.Equal("1.0.170133", oldMini.Info.Firmware);
    }

    [Fact]
    public async Task Pedal_only_reports_presses()
    {
        var hid = new FakeHid("PD0001");
        using var pedal = ElgatoDeck.Start(hid, Model("Stream Deck Pedal"), "PD0001", TimeProvider.System, NullLogger.Instance);
        foreach (var call in new Func<Task>[]
        {
            () => pedal.SetBrightnessAsync(10, CancellationToken.None),
            () => pedal.SetKeyColorAsync(0, "#ffffff", CancellationToken.None),
            () => pedal.SetKeyImageAsync(0, "png", new byte[] { 1 }, CancellationToken.None),
        })
        {
            Assert.Equal("unsupported", (await Assert.ThrowsAsync<DeviceException>(call)).Code);
        }
        // Nothing to show, nothing to blink: quietly done
        await pedal.ResetAsync(CancellationToken.None);
        await pedal.IdentifyAsync(CancellationToken.None);
        Assert.Empty(hid.Features);

        var inputs = new ConcurrentQueue<DeviceInput>();
        pedal.Input += (_, input) => inputs.Enqueue(input);
        hid.Keys(2);
        await WaitForAsync(() => inputs.Count == 1);
        Assert.Equal(new KeyInput(2, true), inputs.Single());
    }

    [Fact]
    public async Task Reset_replaces_waiting_images_and_close_shows_the_logo()
    {
        var hid = new FakeHid();
        var deck = ElgatoDeck.Start(hid, Model("Stream Deck XL"), "XL0001", TimeProvider.System, NullLogger.Instance);
        Assert.Equal("elgato-XL0001", deck.Info.Id);
        Assert.Equal(96, deck.Info.Capabilities.Keys!.ImageWidth);
        await deck.ResetAsync(CancellationToken.None);
        await deck.CloseAsync(reset: true);
        Assert.True(hid.Disposed);
        Assert.All(hid.Features, f => Assert.Equal([0x03, 0x02], f[..2]));
        Assert.NotEmpty(hid.Features);
        var closed = await Assert.ThrowsAsync<DeviceException>(() => deck.SetBrightnessAsync(10, CancellationToken.None));
        Assert.Equal("device_error", closed.Code);
        deck.Dispose(); // twice is fine
    }

    [Fact]
    public async Task Unplugged_deck_fails_once()
    {
        var hid = new FakeHid();
        using var deck = ElgatoDeck.Start(hid, Mk2, "AL1", TimeProvider.System, NullLogger.Instance);
        var faults = 0;
        deck.Faulted += _ => Interlocked.Increment(ref faults);
        hid.Unplug();
        // Faulted follows right after Failed, on the reader thread
        await WaitForAsync(() => Volatile.Read(ref faults) == 1);
        Assert.True(deck.Failed);
        var failed = await Assert.ThrowsAsync<DeviceException>(() => deck.ResetAsync(CancellationToken.None));
        Assert.Equal("device_error", failed.Code);
        await Assert.ThrowsAsync<DeviceException>(() => deck.IdentifyAsync(CancellationToken.None));
        await deck.CloseAsync(reset: true); // no reset on a failed deck
        Assert.Empty(hid.Features);
    }

    [Fact]
    public async Task Write_errors_fail_the_deck()
    {
        var hid = new FakeHid { WriteFailure = new IOException("USB write failed") };
        using var deck = ElgatoDeck.Start(hid, Mk2, "AL1", TimeProvider.System, NullLogger.Instance);
        await deck.SetKeyImageAsync(0, "png", Png(72, (_, _) => (255, 255, 255)), CancellationToken.None);
        await WaitForAsync(() => deck.Failed);
    }

    [Fact]
    public void Deck_without_serial_is_refused()
    {
        var hid = new FakeHid(serial: "");
        Assert.Throws<IOException>(() => ElgatoDeck.Start(hid, Mk2, " ", TimeProvider.System, NullLogger.Instance));
    }

    [Fact]
    public async Task Watcher_follows_plugging_and_failures()
    {
        var usb = new FakeHidBackend();
        usb.Plug("other", productId: 0x0080, vendorId: 0x1234); // another vendor
        usb.Plug("plus-xl", productId: 0x00C6);                 // Elgato, not supported yet
        var first = usb.Plug("port-1");
        await using var bridge = new TestBridge(services => services.AddSingleton<IHidBackend>(usb), usb: true);
        var manager = bridge.Services.GetRequiredService<DeviceManager>();
        await WaitForAsync(() => manager.Get("elgato-AL12K1A01234") is not null);
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        // The deck works through the protocol
        await client.SendAsync(new JsonObject { ["type"] = "set_key_color", ["device"] = "elgato-AL12K1A01234", ["key"] = 1, ["color"] = "#00ff00", ["id"] = 1 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        await WaitForAsync(() => first.Features.Count > 0);
        first.Keys(4);
        Assert.Equal(4, (int)(await client.ReceiveAsync())["key"]!);

        // A second deck, read serial from the feature report
        usb.Plug("port-2", productId: 0x006C, usbSerial: null);
        Assert.Equal("device_added", (string?)(await client.ReceiveAsync())["type"]);
        Assert.NotNull(manager.Get("elgato-FEATURE-SERIAL"));

        // Unplugged: gone from the inventory
        usb.Unplug("port-2");
        var removed = await client.ReceiveAsync();
        Assert.Equal(("device_removed", "elgato-FEATURE-SERIAL"), ((string?)removed["type"], (string?)removed["device"]));

        // A USB error: removed, then opened again on the same port
        var second = usb.Replug("port-1");
        first.Unplug();
        Assert.Equal("device_removed", (string?)(await client.ReceiveAsync())["type"]);
        Assert.Equal("device_added", (string?)(await client.ReceiveAsync())["type"]);
        Assert.True(first.Disposed);

        // Listing fails for a while: nothing changes, nothing crashes
        usb.ListFailure = new DllNotFoundException("libudev.so.1");
        var calls = usb.ListCalls;
        usb.Poke();
        await WaitForAsync(() => usb.ListCalls > calls);
        usb.Poke();
        await WaitForAsync(() => usb.ListCalls > calls + 1);
        usb.ListFailure = null;
        usb.Poke();
        Assert.NotNull(manager.Get("elgato-AL12K1A01234"));

        // Shutting down shows the logo
        await bridge.DisposeAsync();
        Assert.True(second.Disposed);
        Assert.Contains(second.Features, f => f[0] == 0x03 && f[1] == 0x02);
    }

    [Fact]
    public async Task Watcher_retries_decks_it_cannot_open()
    {
        var usb = new FakeHidBackend { OpenFailure = new IOException("in use") };
        usb.Plug("port-1");
        await using var bridge = new TestBridge(services => services.AddSingleton<IHidBackend>(usb), usb: true);
        var manager = bridge.Services.GetRequiredService<DeviceManager>();
        await WaitForAsync(() => usb.OpenAttempts >= 1);
        var attempts = usb.OpenAttempts;
        usb.Poke();
        await WaitForAsync(() => usb.OpenAttempts > attempts);
        Assert.DoesNotContain(manager.All, d => !d.Info.Virtual);

        // The Elgato app was closed
        usb.OpenFailure = null;
        usb.Poke();
        await WaitForAsync(() => manager.Get("elgato-AL12K1A01234") is not null);
    }
}
