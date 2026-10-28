using System.Security.Cryptography;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using StreamAssistant.Bridge.Devices.Elgato;

namespace StreamAssistant.Bridge.Configuration;

/// <summary>
/// A simulated deck: keys, and dials with a touch strip above them (200×100 pixels
/// per dial), or shaped like an Elgato model (<see cref="Like"/>, e.g. "neo").
/// </summary>
public sealed record SimulatedDeck(int Cols, int Rows, int Dials = 0, int KeySize = 72, ElgatoModel? Like = null)
{
    public const int SegmentWidth = 200;
    public const int StripHeight = 100;

    /// <summary>"5x3", "4x2:4" (with 4 dials) or an Elgato model: mk2, xl, plus, mini, original, pedal, neo, studio.</summary>
    public static SimulatedDeck Parse(string text)
    {
        if (ElgatoModel.ByAlias(text) is { } model)
        {
            return new SimulatedDeck(model.Cols, model.Rows, model.Dials, model.KeySize, model);
        }
        var parts = text.Split(':');
        var size = parts[0].Split('x');
        var dials = 0;
        if (parts.Length > 2 || size.Length != 2 || !int.TryParse(size[0], out var cols) || !int.TryParse(size[1], out var rows)
            || cols is < 1 or > 16 || rows is < 1 or > 16 || (parts.Length == 2 && (!int.TryParse(parts[1], out dials) || dials is < 1 or > 8)))
        {
            throw new ArgumentException($"--simulate expects decks like 5x3, 4x2:4 or neo, got '{text}'");
        }
        return new SimulatedDeck(cols, rows, dials);
    }
}

/// <summary>How the bridge was installed, which decides how it updates itself.</summary>
public enum InstallKind
{
    /// <summary>Unpacked by hand or by the install script: files are replaced in place.</summary>
    Archive,

    /// <summary>Windows installer (service): the new installer does the update.</summary>
    Msi,
}

/// <summary>Command line / environment options (read through IConfiguration).</summary>
public sealed record BridgeOptions(
    int Port,
    string ConfigDir,
    string? Name,
    IReadOnlyList<SimulatedDeck> Simulate,
    bool Mdns,
    bool Usb = true,
    string UpdateUrl = BridgeOptions.DefaultUpdateUrl,
    InstallKind Install = InstallKind.Archive,
    bool Service = false,
    int WaitForLock = 0,
    bool AllowPublic = false)
{
    public const int DefaultPort = 5390;

    /// <summary>Release files: {UpdateUrl}/v{version}/{file}.</summary>
    public const string DefaultUpdateUrl = "https://github.com/remostirnimann/StreamAssistant/releases/download";

    // --port 5390 --config-dir <dir> --name "Office PC" --simulate 5x3,4x2:4,plus,neo --mdns false --usb false
    // Set by installers: --service true (a service manager restarts the bridge), --install-kind msi;
    // after a self-update: --wait-for-lock 30; for tests: --update-url <base url>
    // --allow-public true: also accept connections from public addresses (not intended, see docs/terms.md)
    public static BridgeOptions From(IConfiguration config)
    {
        var simulate = (config["simulate"] ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(SimulatedDeck.Parse)
            .ToList();
        var configDir = config["config-dir"];
        if (string.IsNullOrWhiteSpace(configDir))
        {
            configDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData, Environment.SpecialFolderOption.Create),
                "stream-assistant-bridge");
        }
        return new BridgeOptions(
            config.GetValue("port", DefaultPort),
            configDir,
            config["name"],
            simulate,
            config.GetValue("mdns", true),
            config.GetValue("usb", true),
            config["update-url"]?.TrimEnd('/') ?? DefaultUpdateUrl,
            string.Equals(config["install-kind"], "msi", StringComparison.OrdinalIgnoreCase) ? InstallKind.Msi : InstallKind.Archive,
            config.GetValue("service", false),
            Math.Clamp(config.GetValue("wait-for-lock", 0), 0, 300),
            config.GetValue("allow-public", false));
    }
}

public sealed class PairedClient
{
    public string Name { get; set; } = "";

    /// <summary>SHA-256 of the token (hex); the token itself is never stored.</summary>
    public string TokenHash { get; set; } = "";

    public DateTimeOffset Paired { get; set; }
}

/// <summary>A virtual deck of the desktop app.</summary>
public sealed class VirtualDeckSettings
{
    public string Id { get; set; } = "";

    public string Name { get; set; } = "";

    public int Cols { get; set; } = 5;

    public int Rows { get; set; } = 3;

    /// <summary>Dials below the keys, each with its part of a touch strip.</summary>
    public int Dials { get; set; }
}

/// <summary>Persistent state in bridge.json.</summary>
public sealed class BridgeSettings
{
    /// <summary>Stable bridge id, generated once.</summary>
    public string Id { get; set; } = "";

    public string? Name { get; set; }

    public List<PairedClient> Clients { get; set; } = [];

    public List<VirtualDeckSettings> VirtualDecks { get; set; } = [];
}

[JsonSerializable(typeof(BridgeSettings))]
[JsonSourceGenerationOptions(WriteIndented = true, PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower)]
internal sealed partial class SettingsJsonContext : JsonSerializerContext
{
    /// <summary>Keeps umlauts readable in bridge.json (it is a file people look at).</summary>
    /// Created on first use: the generated Default is not ready while static fields initialize.
    public static SettingsJsonContext Readable => _readable ??= new(new JsonSerializerOptions(Default.Options)
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    });

    private static SettingsJsonContext? _readable;
}

/// <summary>A second bridge with the same settings (and so the same id) is running.</summary>
public sealed class AlreadyRunningException(string configDir)
    : Exception($"Another bridge is already running with the settings in {configDir}");

/// <summary>Loads and saves bridge.json atomically. Holds a lock so only one bridge uses the folder.</summary>
public sealed class SettingsStore : IDisposable
{
    private readonly Lock _lock = new();
    private readonly string _path;
    private readonly ILogger<SettingsStore> _logger;
    private readonly FileStream _instanceLock;

    public SettingsStore(BridgeOptions options, ILogger<SettingsStore> logger)
    {
        _logger = logger;
        Directory.CreateDirectory(options.ConfigDir);
        _instanceLock = TakeLock(options);
        _path = Path.Combine(options.ConfigDir, "bridge.json");
        Settings = Load();
        if (string.IsNullOrEmpty(Settings.Id))
        {
            Settings.Id = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(8));
            Save();
        }
    }

    public BridgeSettings Settings { get; }

    public void Dispose() => _instanceLock.Dispose();

    /// <summary>
    /// FileShare.None is an OS lock (flock on Linux/macOS): released when the process ends,
    /// even on a crash. After a self-update the old process may still hold it for a moment.
    /// </summary>
    private static FileStream TakeLock(BridgeOptions options)
    {
        var until = DateTime.UtcNow.AddSeconds(options.WaitForLock);
        while (true)
        {
            try
            {
                return new FileStream(Path.Combine(options.ConfigDir, "bridge.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch (IOException) when (DateTime.UtcNow < until)
            {
                Thread.Sleep(250);
            }
            catch (IOException)
            {
                throw new AlreadyRunningException(options.ConfigDir);
            }
        }
    }

    public string FilePath => _path;

    /// <summary>Change settings and write them, under one lock.</summary>
    public void Update(Action<BridgeSettings> change)
    {
        lock (_lock)
        {
            change(Settings);
            Save();
        }
    }

    private BridgeSettings Load()
    {
        if (!File.Exists(_path))
        {
            return new BridgeSettings();
        }
        try
        {
            return JsonSerializer.Deserialize(File.ReadAllText(_path), SettingsJsonContext.Default.BridgeSettings) ?? new BridgeSettings();
        }
        catch (JsonException err)
        {
            // Keep the broken file for inspection, start fresh (clients must pair again)
            var backup = _path + ".broken";
            File.Copy(_path, backup, overwrite: true);
            _logger.LogError(err, "{Path} is unreadable, saved as {Backup} and starting with new settings", _path, backup);
            return new BridgeSettings();
        }
    }

    private void Save()
    {
        var temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(Settings, SettingsJsonContext.Readable.BridgeSettings));
        File.Move(temp, _path, overwrite: true);
    }
}
