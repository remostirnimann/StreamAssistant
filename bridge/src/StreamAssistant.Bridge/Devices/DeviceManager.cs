using System.Collections.Concurrent;

namespace StreamAssistant.Bridge.Devices;

/// <summary>The devices currently attached. Drivers add and remove them (hot-plug).</summary>
public sealed class DeviceManager(ILogger<DeviceManager> logger)
{
    private readonly ConcurrentDictionary<string, IControlDevice> _devices = new();

    public event Action<IControlDevice>? Added;
    public event Action<string>? Removed;
    public event Action<IControlDevice, DeviceInput>? Input;

    public IReadOnlyList<IControlDevice> All => _devices.Values.OrderBy(d => d.Info.Id, StringComparer.Ordinal).ToList();

    public IControlDevice? Get(string id) => _devices.GetValueOrDefault(id);

    public void Add(IControlDevice device)
    {
        if (!_devices.TryAdd(device.Info.Id, device))
        {
            logger.LogWarning("Device {Id} is already attached, ignoring the second one", device.Info.Id);
            return;
        }
        device.Input += OnInput;
        logger.LogInformation("Device attached: {Name} ({Id})", device.Info.Name, device.Info.Id);
        Added?.Invoke(device);
    }

    public void Remove(string id)
    {
        if (!_devices.TryRemove(id, out var device))
        {
            return;
        }
        device.Input -= OnInput;
        logger.LogInformation("Device detached: {Name} ({Id})", device.Info.Name, id);
        Removed?.Invoke(id);
    }

    private void OnInput(IControlDevice device, DeviceInput input) => Input?.Invoke(device, input);
}
