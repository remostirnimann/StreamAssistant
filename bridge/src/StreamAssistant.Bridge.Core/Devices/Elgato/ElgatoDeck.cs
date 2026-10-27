namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// One Stream Deck on USB (any <see cref="ElgatoFamily"/>). Calls only queue work:
/// a writer task sends control reports in order and the newest image per key or
/// touch area, a reader thread turns input reports into events. A USB error marks
/// the deck failed; <see cref="ElgatoWatcher"/> then removes it and opens it again
/// when it is back.
/// </summary>
public sealed class ElgatoDeck : IControlDevice, IDisposable
{
    private static readonly TimeSpan BlinkStep = TimeSpan.FromMilliseconds(150);
    private static readonly TimeSpan CloseTimeout = TimeSpan.FromSeconds(1);

    private readonly IHidDevice _hid;
    private readonly ElgatoModel _model;
    private readonly TimeProvider _time;
    private readonly ILogger _logger;
    private readonly Lock _lock = new();
    private readonly Queue<byte[]> _features = new();
    // Newest reports per key (Key >= 0), touch area (TouchSlot), screen, button or dial, in the order they came
    private readonly List<Pending> _images = [];
    private readonly SemaphoreSlim _signal = new(0);
    private readonly CancellationTokenSource _stop = new();
    private readonly TaskCompletionSource _idle = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Task _writer = Task.CompletedTask;
    private Thread? _reader;
    private int _brightness = 100;
    private volatile bool _failed;
    private volatile bool _closing;

    /// <summary>Reports for one key or area; colour fills are feature reports.</summary>
    private sealed record Pending(Slot Slot, IReadOnlyList<byte[]> Reports, bool Feature);

    private const int TouchSlot = -1;
    private const int ScreenSlot = -2;
    private const int ButtonSlot = -100;
    private const int DialSlot = -200;

    private readonly record struct Slot(int Key, int X = 0, int Y = 0, int Width = 0, int Height = 0)
    {
        public bool Covers(Slot other) =>
            Key == TouchSlot && other.Key == TouchSlot && X <= other.X && Y <= other.Y && X + Width >= other.X + other.Width && Y + Height >= other.Y + other.Height;
    }

    private ElgatoDeck(IHidDevice hid, ElgatoModel model, DeviceInfo info, TimeProvider time, ILogger logger)
    {
        _hid = hid;
        _model = model;
        _time = time;
        _logger = logger;
        Info = info;
    }

    public DeviceInfo Info { get; }

    public bool Failed => _failed;

    public event Action<IControlDevice, DeviceInput>? Input;

    /// <summary>Raised once, from a driver thread, when the deck stopped working (unplugged).</summary>
    public event Action<ElgatoDeck>? Faulted;

    /// <summary>Read firmware and serial from an opened deck and start its reader and writer.</summary>
    public static ElgatoDeck Start(IHidDevice hid, ElgatoModel model, string? usbSerial, TimeProvider time, ILogger logger)
    {
        var serial = string.IsNullOrWhiteSpace(usbSerial) ? model.ReadSerial(hid) : usbSerial.Trim();
        var firmware = model.ReadFirmware(hid);
        if (serial.Length == 0)
        {
            throw new IOException("The deck reports no serial number");
        }
        var info = new DeviceInfo(
            Id: $"elgato-{serial}",
            Vendor: "Elgato",
            Model: model.Name,
            Name: model.Name,
            Serial: serial,
            Firmware: firmware.Length > 0 ? firmware : null,
            Virtual: false,
            Capabilities: model.Capabilities());
        var deck = new ElgatoDeck(hid, model, info, time, logger);
        deck._writer = Task.Run(deck.WriteLoopAsync);
        deck._reader = new Thread(deck.ReadLoop) { IsBackground = true, Name = $"{info.Id} input" };
        deck._reader.Start();
        return deck;
    }

    public Task SetBrightnessAsync(int percent, CancellationToken cancellationToken)
    {
        NeedDisplay();
        _brightness = Math.Clamp(percent, 0, 100);
        Queue(_model.BrightnessReport(_brightness));
        return Task.CompletedTask;
    }

    public Task SetKeyImageAsync(int key, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        NeedDisplay();
        CheckKey(key);
        // Converted here, so a broken image is reported to the client
        var encoded = _model.EncodeKey(KeyImages.Fit(image, _model.KeySize, _model.ImageHeight));
        QueueImage(new Slot(key), _model.ImageReports(key, encoded).ToList());
        return Task.CompletedTask;
    }

    public Task SetKeyColorAsync(int key, string color, CancellationToken cancellationToken)
    {
        NeedDisplay();
        CheckKey(key);
        var (red, green, blue) = KeyImages.Rgb(color);
        // Newer decks fill a key with one small feature report; the first generation needs an image
        if (_model.ColorReport(key, red, green, blue) is { } fill)
        {
            QueueImage(new Slot(key), [fill], feature: true);
        }
        else
        {
            QueueImage(new Slot(key), _model.ImageReports(key, _model.EncodeKey(KeyImages.Solid(color, _model.KeySize, _model.ImageHeight))).ToList());
        }
        return Task.CompletedTask;
    }

    public Task ClearKeyAsync(int key, CancellationToken cancellationToken) => SetKeyColorAsync(key, "#000000", cancellationToken);

    public Task SetTouchImageAsync(int x, int y, int width, int height, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        if (!_model.HasTouch)
        {
            throw new DeviceException("unsupported", $"{Info.Name} has no touch display");
        }
        var jpeg = KeyImages.Jpeg(KeyImages.Decode(image, width, height), width, height);
        QueueImage(new Slot(TouchSlot, x, y, width, height), ElgatoModel.TouchReports(x, y, width, height, jpeg).ToList());
        return Task.CompletedTask;
    }

    public Task SetScreenImageAsync(string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        if (!_model.HasScreen)
        {
            throw new DeviceException("unsupported", $"{Info.Name} has no screen");
        }
        var jpeg = _model.EncodeScreen(KeyImages.Decode(image, _model.ScreenWidth, _model.ScreenHeight));
        QueueImage(new Slot(ScreenSlot), ElgatoModel.ScreenReports(jpeg).ToList());
        return Task.CompletedTask;
    }

    public Task SetButtonColorAsync(int button, string color, CancellationToken cancellationToken)
    {
        if (button < 0 || button >= _model.Buttons)
        {
            throw new DeviceException("unsupported", $"{Info.Name} has no button {button}");
        }
        var (red, green, blue) = KeyImages.Rgb(color);
        QueueImage(new Slot(ButtonSlot - button), [_model.ButtonColorReport(button, red, green, blue)], feature: true);
        return Task.CompletedTask;
    }

    public Task SetDialLedsAsync(int dial, string color, double level, CancellationToken cancellationToken)
    {
        if (_model.DialRing == 0 || dial < 0 || dial >= _model.Dials)
        {
            throw new DeviceException("unsupported", $"{Info.Name} has no LEDs on dial {dial}");
        }
        var (red, green, blue) = KeyImages.Rgb(color);
        QueueImage(new Slot(DialSlot - dial), _model.DialLedReports(dial, red, green, blue, level).ToList());
        return Task.CompletedTask;
    }

    public Task ResetAsync(CancellationToken cancellationToken)
    {
        CheckAlive();
        if (!_model.HasDisplay)
        {
            // The Pedal has nothing to show
            return Task.CompletedTask;
        }
        lock (_lock)
        {
            // The logo replaces everything still waiting
            _images.Clear();
            _features.Enqueue(_model.ResetReport());
        }
        _signal.Release();
        return Task.CompletedTask;
    }

    public Task IdentifyAsync(CancellationToken cancellationToken)
    {
        CheckAlive();
        if (_model.HasDisplay)
        {
            _ = BlinkAsync();
        }
        return Task.CompletedTask;
    }

    /// <summary>Optionally show the logo, wait (briefly) until the queue is sent, then release the device.</summary>
    public async Task CloseAsync(bool reset)
    {
        if (reset && !_failed)
        {
            await ResetAsync(CancellationToken.None);
        }
        _closing = true;
        _signal.Release();
        await Task.WhenAny(_idle.Task, Task.Delay(CloseTimeout, _time));
        Dispose();
    }

    public void Dispose()
    {
        _closing = true;
        if (_stop.IsCancellationRequested)
        {
            return;
        }
        _stop.Cancel();
        // Ends a blocking read
        _hid.Dispose();
        // _stop and _signal stay undisposed: late calls (blinking, the session) may still touch them
        _writer.Wait(CloseTimeout);
    }

    private void NeedDisplay()
    {
        if (!_model.HasDisplay)
        {
            throw new DeviceException("unsupported", $"{Info.Name} has no display");
        }
    }

    private void CheckKey(int key)
    {
        if (key < 0 || key >= _model.KeyCount)
        {
            throw new DeviceException("invalid_message", $"Key {key} does not exist");
        }
    }

    /// <summary>Replace what waits for this key or area (and touch areas it covers); feature reports go out as such.</summary>
    private void QueueImage(Slot slot, IReadOnlyList<byte[]> reports, bool feature = false)
    {
        CheckAlive();
        lock (_lock)
        {
            _images.RemoveAll(pending => pending.Slot == slot || slot.Covers(pending.Slot));
            _images.Add(new Pending(slot, reports, feature));
        }
        _signal.Release();
    }

    private void Queue(byte[] feature)
    {
        CheckAlive();
        lock (_lock)
        {
            _features.Enqueue(feature);
        }
        _signal.Release();
    }

    private void CheckAlive()
    {
        if (_failed || _stop.IsCancellationRequested)
        {
            throw new DeviceException("device_error", $"{Info.Name} is disconnected");
        }
    }

    private async Task BlinkAsync()
    {
        try
        {
            for (var i = 0; i < 3; i++)
            {
                Queue(_model.BrightnessReport(0));
                await Task.Delay(BlinkStep, _time, _stop.Token);
                Queue(_model.BrightnessReport(_brightness));
                await Task.Delay(BlinkStep, _time, _stop.Token);
            }
        }
        catch (Exception err) when (err is OperationCanceledException or ObjectDisposedException or DeviceException)
        {
            // Unplugged or closed while blinking
        }
    }

    private async Task WriteLoopAsync()
    {
        try
        {
            while (true)
            {
                if (!TakeWork(out var work))
                {
                    if (_closing)
                    {
                        break;
                    }
                    await _signal.WaitAsync(_stop.Token);
                    continue;
                }
                work();
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception err) when (err is IOException or ObjectDisposedException or InvalidOperationException or TimeoutException)
        {
            Fail(err);
        }
        _idle.TrySetResult();
    }

    /// <summary>Control reports first (in order), then the oldest pending image.</summary>
    private bool TakeWork(out Action work)
    {
        lock (_lock)
        {
            if (_features.TryDequeue(out var feature))
            {
                work = () => _hid.SetFeature(feature);
                return true;
            }
            if (_images.Count > 0)
            {
                var pending = _images[0];
                _images.RemoveAt(0);
                work = () =>
                {
                    foreach (var report in pending.Reports)
                    {
                        if (pending.Feature)
                        {
                            _hid.SetFeature(report);
                        }
                        else
                        {
                            _hid.Write(report);
                        }
                    }
                };
                return true;
            }
        }
        work = () => { };
        return false;
    }

    private void ReadLoop()
    {
        var buffer = new byte[Math.Max(_hid.InputReportLength, 512)];
        var parser = new ElgatoModel.InputParser(_model);
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var length = _hid.Read(buffer);
                foreach (var input in parser.Parse(buffer, length))
                {
                    Input?.Invoke(this, input);
                }
            }
        }
        catch (Exception err) when (err is IOException or ObjectDisposedException or InvalidOperationException or TimeoutException)
        {
            if (!_stop.IsCancellationRequested)
            {
                Fail(err);
            }
        }
    }

    private void Fail(Exception err)
    {
        lock (_lock)
        {
            if (_failed)
            {
                return;
            }
            _failed = true;
        }
        _logger.LogInformation("{Name} ({Id}) stopped responding: {Message}", Info.Name, Info.Id, err.Message);
        Faulted?.Invoke(this);
    }
}
