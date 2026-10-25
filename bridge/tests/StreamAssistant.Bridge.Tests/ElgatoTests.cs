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

    public byte[] GetFeature(byte reportId)
    {
        var report = new byte[32];
        report[0] = reportId;
        var text = reportId == ElgatoModel.FirmwareReport ? "\0\0\0\01.01.000" : serial;
        Encoding.ASCII.GetBytes(text).CopyTo(report, 2);
        report[1] = (byte)text.Length;
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

    [Fact]
    public void Models_and_reports()
    {
        Assert.Equal("Stream Deck XL", ElgatoModel.Find(ElgatoModel.VendorId, 0x008F)!.Name);
        Assert.Null(ElgatoModel.Find(ElgatoModel.VendorId, 0x0063));
        Assert.Null(ElgatoModel.Find(0x1234, 0x0080));
        Assert.Equal(15, Mk2.KeyCount);

        var reports = ElgatoModel.ImageReports(4, new byte[2000]).ToList();
        Assert.Equal(2, reports.Count);
        Assert.All(reports, r => Assert.Equal(1024, r.Length));
        Assert.Equal([0x02, 0x07, 4, 0, 0xF8, 0x03, 0, 0], reports[0][..8]);
        Assert.Equal([0x02, 0x07, 4, 1, 0xD8, 0x03, 1, 0], reports[1][..8]);
        var empty = Assert.Single(ElgatoModel.ImageReports(0, []));
        Assert.Equal(1, empty[3]);

        Assert.Equal([0x03, 0x08, 100], ElgatoModel.BrightnessReport(150)[..3]);
        Assert.Equal(0, ElgatoModel.BrightnessReport(-5)[2]);
        Assert.Equal([0x03, 0x02], ElgatoModel.ResetReport()[..2]);
    }

    [Fact]
    public void Report_strings()
    {
        var firmware = new byte[32];
        firmware[1] = 12;
        Encoding.ASCII.GetBytes("1.01.000").CopyTo(firmware, 6);
        Assert.Equal("1.01.000", ElgatoModel.ParseFirmware(firmware));

        // A length that does not fit: read to the end, stop at the first zero, drop control characters
        var serial = new byte[32];
        serial[1] = 200;
        Encoding.ASCII.GetBytes("AL12\u0001K1").CopyTo(serial, 2);
        Assert.Equal("AL12K1", ElgatoModel.ParseSerial(serial));
        Assert.Equal("", ElgatoModel.ParseSerial([6]));
    }

    [Fact]
    public void Input_reports()
    {
        var report = new byte[512];
        report[0] = 0x01;
        report[4 + 2] = 1;
        var keys = Mk2.ParseKeys(report, 512)!;
        Assert.Equal(15, keys.Length);
        Assert.True(keys[2]);
        Assert.False(keys[0]);
        Assert.Null(Mk2.ParseKeys(report, 10));
        report[0] = 0x02;
        Assert.Null(Mk2.ParseKeys(report, 512));
    }

    [Fact]
    public void Images_are_scaled_and_turned()
    {
        // Red in the top left corner of an upright image ends up bottom right on the deck
        var png = Png(144, (x, y) => x < 72 && y < 72 ? ((byte)255, (byte)0, (byte)0) : ((byte)0, (byte)0, (byte)255));
        var key = ImageResult.FromMemory(KeyImages.ForKey(png, 72), ReadComponents.RedGreenBlue);
        Assert.Equal((72, 72), (key.Width, key.Height));
        Assert.True(PixelAt(key, 60, 60).R > 200);
        Assert.True(PixelAt(key, 10, 10).B > 200);

        var solid = ImageResult.FromMemory(KeyImages.Solid("#00ff00", 96), ReadComponents.RedGreenBlue);
        Assert.Equal(96, solid.Width);
        Assert.True(PixelAt(solid, 50, 50).G > 200);

        var broken = Assert.Throws<DeviceException>(() => KeyImages.ForKey(new byte[] { 1, 2, 3 }, 72));
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
        await WaitForAsync(() => hid.Writes.Select(r => r[2]).Distinct().Count() == 3 && hid.Features.Count == 1);
        Assert.Equal(40, hid.Features[0][2]);
        var red = ImageResult.FromMemory(Jpeg(hid.Writes, 5), ReadComponents.RedGreenBlue);
        Assert.True(PixelAt(red, 36, 36).R > 200);
        var cleared = ImageResult.FromMemory(Jpeg(hid.Writes, 14), ReadComponents.RedGreenBlue);
        Assert.True(PixelAt(cleared, 36, 36).R < 30);

        var wrongKey = await Assert.ThrowsAsync<DeviceException>(() => deck.SetKeyColorAsync(15, "#ffffff", CancellationToken.None));
        Assert.Equal("invalid_message", wrongKey.Code);

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
        await WaitForAsync(() => hid.Features.Count == 7);
        Assert.Equal([0, 40, 0, 40, 0, 40], hid.Features.Skip(1).Select(f => (int)f[2]));
    }

    [Fact]
    public async Task Reset_replaces_waiting_images_and_close_shows_the_logo()
    {
        var hid = new FakeHid();
        var deck = ElgatoDeck.Start(hid, ElgatoModel.All[2], "XL0001", TimeProvider.System, NullLogger.Instance);
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
        await deck.SetKeyColorAsync(0, "#ffffff", CancellationToken.None);
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
        usb.Plug("mini", productId: 0x0063);                    // Elgato, not supported yet
        var first = usb.Plug("port-1");
        await using var bridge = new TestBridge(services => services.AddSingleton<IHidBackend>(usb), usb: true);
        var manager = bridge.Services.GetRequiredService<DeviceManager>();
        await WaitForAsync(() => manager.Get("elgato-AL12K1A01234") is not null);
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;

        // The deck works through the protocol
        await client.SendAsync(new JsonObject { ["type"] = "set_key_color", ["device"] = "elgato-AL12K1A01234", ["key"] = 1, ["color"] = "#00ff00", ["id"] = 1 });
        Assert.True((bool)(await client.ReceiveAsync())["ok"]!);
        await WaitForAsync(() => first.Writes.Count > 0);
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
