using System.Security.Cryptography;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Devices.Virtual;

/// <summary>
/// Virtual decks of the desktop app: created by the user, stored in
/// bridge.json, offered to Home Assistant like real decks.
/// </summary>
public sealed class VirtualDecks(SettingsStore store, DeviceManager manager, ILogger<VirtualDecks> logger)
{
    public const int MaxCols = 12;
    public const int MaxRows = 8;

    /// <summary>Rendered by Home Assistant at this size; sharp on high-DPI screens.</summary>
    public const int KeySize = 144;

    private readonly Lock _lock = new();
    private readonly List<VirtualDevice> _decks = [];

    /// <summary>Raised after a deck was added or removed.</summary>
    public event Action? Changed;

    public IReadOnlyList<VirtualDevice> Decks
    {
        get
        {
            lock (_lock)
            {
                return [.. _decks];
            }
        }
    }

    /// <summary>Attach the stored decks.</summary>
    public void Start()
    {
        foreach (var settings in store.Settings.VirtualDecks)
        {
            Attach(Create(settings));
        }
    }

    public VirtualDevice Add(string name, int cols, int rows)
    {
        if (cols is < 1 or > MaxCols || rows is < 1 or > MaxRows)
        {
            throw new ArgumentOutOfRangeException(nameof(cols), $"Grid must be 1-{MaxCols} x 1-{MaxRows}");
        }
        var settings = new VirtualDeckSettings
        {
            Id = "virtual-" + Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(4)),
            Name = string.IsNullOrWhiteSpace(name) ? $"Virtual deck {cols}×{rows}" : name.Trim(),
            Cols = cols,
            Rows = rows,
        };
        store.Update(s => s.VirtualDecks.Add(settings));
        var device = Create(settings);
        Attach(device);
        logger.LogInformation("Virtual deck added: {Name} ({Cols}×{Rows})", settings.Name, cols, rows);
        Changed?.Invoke();
        return device;
    }

    public void Remove(string id)
    {
        lock (_lock)
        {
            if (_decks.RemoveAll(d => d.Info.Id == id) == 0)
            {
                return;
            }
        }
        manager.Remove(id);
        store.Update(s => s.VirtualDecks.RemoveAll(d => d.Id == id));
        logger.LogInformation("Virtual deck removed: {Id}", id);
        Changed?.Invoke();
    }

    private static VirtualDevice Create(VirtualDeckSettings settings) => new(new DeviceInfo(
        Id: settings.Id,
        Vendor: "Stream Assistant",
        Model: $"Virtual deck {settings.Cols}×{settings.Rows}",
        Name: settings.Name,
        Serial: settings.Id,
        Firmware: BridgeServer.Version,
        Virtual: true,
        Capabilities: new DeviceCapabilities(KeyGrid.Images(settings.Cols, settings.Rows, KeySize), Brightness: true)));

    private void Attach(VirtualDevice device)
    {
        lock (_lock)
        {
            _decks.Add(device);
        }
        manager.Add(device);
    }
}
