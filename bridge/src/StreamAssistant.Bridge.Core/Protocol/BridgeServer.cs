using System.Net.WebSockets;
using System.Reflection;
using System.Text.Json.Nodes;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;

namespace StreamAssistant.Bridge.Protocol;

/// <summary>
/// Accepts protocol connections and keeps track of the one active client
/// (protocol sections 3.3 and 3.5).
/// </summary>
public sealed class BridgeServer(
    DeviceManager devices,
    PairingService pairing,
    SettingsStore store,
    BridgeOptions options,
    TimeProvider time,
    ILoggerFactory loggerFactory)
{
    public const int ProtocolVersion = 1;

    /// <summary>After the client is gone this long, devices go back to their idle screen.</summary>
    public static readonly TimeSpan IdleResetDelay = TimeSpan.FromSeconds(30);

    public static readonly string[] Features = ["key_images", "key_colors", "brightness"];

    public static string Version { get; } =
        typeof(BridgeServer).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0]
        ?? "0.0.0";

    private readonly Lock _lock = new();
    private readonly ILogger<BridgeServer> _logger = loggerFactory.CreateLogger<BridgeServer>();
    private ClientSession? _active;
    private ITimer? _idleReset;

    /// <summary>Raised (from any thread) when a client connects or disconnects.</summary>
    public event Action? ClientChanged;

    public DeviceManager Devices => devices;
    public PairingService Pairing => pairing;
    public TimeProvider Time => time;
    public string Id => store.Settings.Id;
    public string Name => options.Name ?? store.Settings.Name ?? Environment.MachineName;

    /// <summary>Name of the connected client, if any.</summary>
    public string? ActiveClient
    {
        get
        {
            lock (_lock)
            {
                return _active?.ClientName;
            }
        }
    }

    public JsonObject BridgeJson() => new()
    {
        ["id"] = Id,
        ["name"] = Name,
        ["version"] = Version,
        ["platform"] = System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier,
    };

    public Task RunSessionAsync(WebSocket socket, string remote, CancellationToken aborted) =>
        new ClientSession(this, socket, remote, loggerFactory.CreateLogger<ClientSession>()).RunAsync(aborted);

    internal void Activate(ClientSession session)
    {
        ClientSession? previous;
        lock (_lock)
        {
            previous = _active;
            _active = session;
            _idleReset?.Dispose();
            _idleReset = null;
        }
        if (previous is not null)
        {
            _logger.LogInformation("{Client} took over from {Previous}", session.ClientName, previous.ClientName);
            previous.Replace();
        }
        else
        {
            _logger.LogInformation("{Client} connected from {Remote}", session.ClientName, session.Remote);
        }
        ClientChanged?.Invoke();
    }

    internal void Deactivate(ClientSession session)
    {
        lock (_lock)
        {
            if (_active != session)
            {
                return;
            }
            _active = null;
            _idleReset?.Dispose();
            _idleReset = time.CreateTimer(_ => ResetIfIdle(), null, IdleResetDelay, Timeout.InfiniteTimeSpan);
        }
        _logger.LogInformation("{Client} disconnected", session.ClientName);
        ClientChanged?.Invoke();
    }

    private void ResetIfIdle()
    {
        lock (_lock)
        {
            if (_active is not null)
            {
                return;
            }
        }
        _logger.LogInformation("No client for {Seconds} s, showing the idle screen", IdleResetDelay.TotalSeconds);
        foreach (var device in devices.All)
        {
            _ = ResetQuietlyAsync(device);
        }
    }

    private async Task ResetQuietlyAsync(IControlDevice device)
    {
        try
        {
            await device.ResetAsync(CancellationToken.None);
        }
        catch (Exception err)
        {
            _logger.LogWarning(err, "Resetting {Id} failed", device.Info.Id);
        }
    }
}
