namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// One Gen2 Stream Deck on USB. Calls only queue work: a writer task sends
/// control reports in order and the newest image per key, a reader thread
/// turns input reports into key events. A USB error marks the deck failed;
/// <see cref="ElgatoWatcher"/> then removes it and opens it again when it is back.
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
    private readonly Dictionary<int, byte[]> _images = [];
    private readonly SemaphoreSlim _signal = new(0);
    private readonly CancellationTokenSource _stop = new();
    private readonly TaskCompletionSource _idle = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private Task _writer = Task.CompletedTask;
    private Thread? _reader;
    private int _brightness = 100;
    private volatile bool _failed;
    private volatile bool _closing;

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
        var serial = string.IsNullOrWhiteSpace(usbSerial) ? ElgatoModel.ParseSerial(hid.GetFeature(ElgatoModel.SerialReport)) : usbSerial.Trim();
        var firmware = ElgatoModel.ParseFirmware(hid.GetFeature(ElgatoModel.FirmwareReport));
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
            Capabilities: new DeviceCapabilities(KeyGrid.Images(model.Cols, model.Rows, model.KeySize, "jpeg", "png"), Brightness: true));
        var deck = new ElgatoDeck(hid, model, info, time, logger);
        deck._writer = Task.Run(deck.WriteLoopAsync);
        deck._reader = new Thread(deck.ReadLoop) { IsBackground = true, Name = $"{info.Id} input" };
        deck._reader.Start();
        return deck;
    }

    public Task SetBrightnessAsync(int percent, CancellationToken cancellationToken)
    {
        _brightness = Math.Clamp(percent, 0, 100);
        Queue(ElgatoModel.BrightnessReport(_brightness));
        return Task.CompletedTask;
    }

    public Task SetKeyImageAsync(int key, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        // Converted here, so a broken image is reported to the client
        QueueImage(key, KeyImages.ForKey(image, _model.KeySize));
        return Task.CompletedTask;
    }

    public Task SetKeyColorAsync(int key, string color, CancellationToken cancellationToken)
    {
        QueueImage(key, KeyImages.Solid(color, _model.KeySize));
        return Task.CompletedTask;
    }

    public Task ClearKeyAsync(int key, CancellationToken cancellationToken)
    {
        QueueImage(key, KeyImages.Solid("#000000", _model.KeySize));
        return Task.CompletedTask;
    }

    public Task ResetAsync(CancellationToken cancellationToken)
    {
        CheckAlive();
        lock (_lock)
        {
            // The logo replaces everything still waiting
            _images.Clear();
            _features.Enqueue(ElgatoModel.ResetReport());
        }
        _signal.Release();
        return Task.CompletedTask;
    }

    public Task IdentifyAsync(CancellationToken cancellationToken)
    {
        CheckAlive();
        _ = BlinkAsync();
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

    private void QueueImage(int key, byte[] jpeg)
    {
        CheckAlive();
        if (key < 0 || key >= _model.KeyCount)
        {
            throw new DeviceException("invalid_message", $"Key {key} does not exist");
        }
        lock (_lock)
        {
            _images[key] = jpeg;
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
                Queue(ElgatoModel.BrightnessReport(0));
                await Task.Delay(BlinkStep, _time, _stop.Token);
                Queue(ElgatoModel.BrightnessReport(_brightness));
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

    /// <summary>Control reports first (in order), then one pending image.</summary>
    private bool TakeWork(out Action work)
    {
        lock (_lock)
        {
            if (_features.TryDequeue(out var feature))
            {
                work = () => _hid.SetFeature(feature);
                return true;
            }
            foreach (var (key, jpeg) in _images)
            {
                _images.Remove(key);
                work = () =>
                {
                    foreach (var report in ElgatoModel.ImageReports(key, jpeg))
                    {
                        _hid.Write(report);
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
        var pressed = new bool[_model.KeyCount];
        try
        {
            while (!_stop.IsCancellationRequested)
            {
                var length = _hid.Read(buffer);
                if (_model.ParseKeys(buffer, length) is not { } keys)
                {
                    continue;
                }
                for (var key = 0; key < keys.Length; key++)
                {
                    if (keys[key] != pressed[key])
                    {
                        pressed[key] = keys[key];
                        Input?.Invoke(this, new KeyInput(key, keys[key]));
                    }
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
