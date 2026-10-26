namespace StreamAssistant.Bridge.Devices.Virtual;

/// <summary>
/// A deck that only exists in software: a virtual deck in the desktop window,
/// or a simulated deck for tests (--simulate). Whoever shows it listens to
/// <see cref="Changed"/> and <see cref="TouchChanged"/> and reports input with
/// <see cref="Press"/>, <see cref="Turn"/>, <see cref="PressDial"/>, <see cref="Touch"/>,
/// <see cref="PressButton"/> and <see cref="ReadTag"/>. Button colours, the screen
/// and dial LEDs count as a change of the whole device.
/// </summary>
public sealed class VirtualDevice(DeviceInfo info) : IControlDevice
{
    private readonly Lock _lock = new();
    private readonly Dictionary<int, KeyContent> _keys = [];
    private readonly List<TouchImage> _touch = [];
    private readonly Dictionary<int, string> _buttons = [];
    private readonly Dictionary<int, DialLeds> _dialLeds = [];
    private (string Format, byte[] Image)? _screen;

    /// <summary>What a dial's LEDs show.</summary>
    public sealed record DialLeds(string Color, double Level);

    /// <summary>What a key shows: an image or a colour.</summary>
    public sealed record KeyContent(string? Format, byte[]? Image, string? Color);

    /// <summary>An image on an area of the touch display.</summary>
    public sealed record TouchImage(int X, int Y, int Width, int Height, string Format, byte[] Image)
    {
        public bool Inside(TouchImage other) =>
            X >= other.X && Y >= other.Y && X + Width <= other.X + other.Width && Y + Height <= other.Y + other.Height;
    }

    public DeviceInfo Info { get; } = info;

    public int Brightness { get; private set; } = 100;

    public event Action<IControlDevice, DeviceInput>? Input;

    /// <summary>Raised after every display change; the argument is the key, or null for the whole device.</summary>
    public event Action<VirtualDevice, int?>? Changed;

    public event Action<VirtualDevice>? Identified;

    /// <summary>Raised after an image was put on the touch display.</summary>
    public event Action<VirtualDevice, TouchImage>? TouchChanged;

    /// <summary>The images on the touch display, oldest first (later ones are drawn on top).</summary>
    public IReadOnlyList<TouchImage> TouchImages
    {
        get
        {
            lock (_lock)
            {
                return [.. _touch];
            }
        }
    }

    public string? GetButtonColor(int button)
    {
        lock (_lock)
        {
            return _buttons.GetValueOrDefault(button);
        }
    }

    public DialLeds? GetDialLeds(int dial)
    {
        lock (_lock)
        {
            return _dialLeds.GetValueOrDefault(dial);
        }
    }

    public (string Format, byte[] Image)? Screen
    {
        get
        {
            lock (_lock)
            {
                return _screen;
            }
        }
    }

    public void PressButton(int button, bool pressed)
    {
        if (Info.Capabilities.Buttons is { } buttons && button >= 0 && button < buttons.Count)
        {
            Input?.Invoke(this, new ButtonInput(button, pressed));
        }
    }

    public void ReadTag(string id)
    {
        if (Info.Capabilities.Nfc && !string.IsNullOrWhiteSpace(id))
        {
            Input?.Invoke(this, new NfcInput(id.Trim()));
        }
    }

    public Task SetButtonColorAsync(int button, string color, CancellationToken cancellationToken) =>
        ChangeExtras(() => _buttons[button] = color);

    public Task SetScreenImageAsync(string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken) =>
        ChangeExtras(() => _screen = (format, image.ToArray()));

    public Task SetDialLedsAsync(int dial, string color, double level, CancellationToken cancellationToken) =>
        ChangeExtras(() => _dialLeds[dial] = new DialLeds(color, level));

    private Task ChangeExtras(Action change)
    {
        lock (_lock)
        {
            change();
        }
        Changed?.Invoke(this, null);
        return Task.CompletedTask;
    }

    public KeyContent? GetKey(int key)
    {
        lock (_lock)
        {
            return _keys.GetValueOrDefault(key);
        }
    }

    public void Press(int key, bool pressed)
    {
        if (Info.Capabilities.Keys is { } grid && key >= 0 && key < grid.Count)
        {
            Input?.Invoke(this, new KeyInput(key, pressed));
        }
    }

    public void Turn(int dial, int delta)
    {
        if (Info.Capabilities.Dials is { } dials && dial >= 0 && dial < dials.Count && delta != 0)
        {
            Input?.Invoke(this, new DialInput(dial, delta));
        }
    }

    public void PressDial(int dial, bool pressed)
    {
        if (Info.Capabilities.Dials is { Press: true } dials && dial >= 0 && dial < dials.Count)
        {
            Input?.Invoke(this, new DialPressInput(dial, pressed));
        }
    }

    /// <summary>Report a touch; points outside the display are moved onto its edge.</summary>
    public void Touch(string kind, int x, int y, int? x2 = null, int? y2 = null)
    {
        if (Info.Capabilities.Touch is not { } touch || kind is not (TouchInput.Tap or TouchInput.Hold or TouchInput.Swipe))
        {
            return;
        }
        int X(int value) => Math.Clamp(value, 0, touch.Width - 1);
        int Y(int value) => Math.Clamp(value, 0, touch.Height - 1);
        Input?.Invoke(this, kind == TouchInput.Swipe
            ? new TouchInput(kind, X(x), Y(y), X(x2 ?? x), Y(y2 ?? y))
            : new TouchInput(kind, X(x), Y(y)));
    }

    public Task SetTouchImageAsync(int x, int y, int width, int height, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        var content = new TouchImage(x, y, width, height, format, image.ToArray());
        lock (_lock)
        {
            // Images it covers completely are gone for good
            _touch.RemoveAll(old => old.Inside(content));
            _touch.Add(content);
        }
        TouchChanged?.Invoke(this, content);
        return Task.CompletedTask;
    }

    public Task SetBrightnessAsync(int percent, CancellationToken cancellationToken)
    {
        Brightness = percent;
        Changed?.Invoke(this, null);
        return Task.CompletedTask;
    }

    public Task SetKeyImageAsync(int key, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken)
    {
        SetKey(key, new KeyContent(format, image.ToArray(), null));
        return Task.CompletedTask;
    }

    public Task SetKeyColorAsync(int key, string color, CancellationToken cancellationToken)
    {
        SetKey(key, new KeyContent(null, null, color));
        return Task.CompletedTask;
    }

    public Task ClearKeyAsync(int key, CancellationToken cancellationToken)
    {
        SetKey(key, null);
        return Task.CompletedTask;
    }

    public Task ResetAsync(CancellationToken cancellationToken)
    {
        lock (_lock)
        {
            _keys.Clear();
            _touch.Clear();
            _buttons.Clear();
            _dialLeds.Clear();
            _screen = null;
        }
        Changed?.Invoke(this, null);
        return Task.CompletedTask;
    }

    public Task IdentifyAsync(CancellationToken cancellationToken)
    {
        Identified?.Invoke(this);
        return Task.CompletedTask;
    }

    private void SetKey(int key, KeyContent? content)
    {
        lock (_lock)
        {
            if (content is null)
            {
                _keys.Remove(key);
            }
            else
            {
                _keys[key] = content;
            }
        }
        Changed?.Invoke(this, key);
    }
}
