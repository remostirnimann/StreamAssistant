namespace StreamAssistant.Bridge.Devices.Virtual;

/// <summary>
/// A deck that only exists in software: a virtual deck in the desktop window,
/// or a simulated deck for tests (--simulate). Whoever shows it listens to
/// <see cref="Changed"/> and reports presses with <see cref="Press"/>.
/// </summary>
public sealed class VirtualDevice(DeviceInfo info) : IControlDevice
{
    private readonly Lock _lock = new();
    private readonly Dictionary<int, KeyContent> _keys = [];

    /// <summary>What a key shows: an image or a colour.</summary>
    public sealed record KeyContent(string? Format, byte[]? Image, string? Color);

    public DeviceInfo Info { get; } = info;

    public int Brightness { get; private set; } = 100;

    public event Action<IControlDevice, DeviceInput>? Input;

    /// <summary>Raised after every display change; the argument is the key, or null for the whole device.</summary>
    public event Action<VirtualDevice, int?>? Changed;

    public event Action<VirtualDevice>? Identified;

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
