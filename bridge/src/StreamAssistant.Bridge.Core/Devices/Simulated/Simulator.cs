using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices.Virtual;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Devices.Simulated;

/// <summary>
/// Simulated decks (--simulate 5x3) and the local simulator page that shows
/// them, presses keys and plugs them in and out.
/// </summary>
public sealed class Simulator
{
    private readonly DeviceManager _manager;
    private readonly ILogger<Simulator> _logger;
    private readonly List<VirtualDevice> _devices = [];

    public Simulator(DeviceManager manager, BridgeOptions options, ILogger<Simulator> logger)
    {
        _manager = manager;
        _logger = logger;
        var number = 0;
        foreach (var (cols, rows) in options.Simulate)
        {
            number++;
            var id = $"sim-{number}";
            var info = new DeviceInfo(
                Id: id,
                Vendor: "Stream Assistant",
                Model: $"Simulated deck {cols}×{rows}",
                Name: $"Simulated deck {number}",
                Serial: id,
                Firmware: BridgeServer.Version,
                Virtual: true,
                Capabilities: new DeviceCapabilities(KeyGrid.Images(cols, rows, 72), Brightness: true));
            var device = new VirtualDevice(info);
            device.Changed += (d, key) => Publish(key is { } k ? KeyJson(d, k) : DeviceJson(d));
            device.Identified += d => Publish(new JsonObject { ["type"] = "identify", ["device"] = d.Info.Id });
            _devices.Add(device);
        }
    }

    /// <summary>Simulator page events (JSON), for the open pages.</summary>
    public event Action<JsonObject>? PageEvent;

    public IReadOnlyList<VirtualDevice> Devices => _devices;

    public bool IsPlugged(VirtualDevice device) => _manager.Get(device.Info.Id) == device;

    /// <summary>Attach all simulated decks.</summary>
    public void Start()
    {
        foreach (var device in _devices)
        {
            _manager.Add(device);
        }
    }

    public void SetPlugged(string id, bool plugged)
    {
        if (_devices.FirstOrDefault(d => d.Info.Id == id) is not { } device || IsPlugged(device) == plugged)
        {
            return;
        }
        if (plugged)
        {
            _manager.Add(device);
        }
        else
        {
            _manager.Remove(id);
        }
        Publish(DeviceJson(device));
    }

    // Page connection

    public async Task RunPageAsync(WebSocket socket, CancellationToken cancellationToken)
    {
        var sendLock = new SemaphoreSlim(1, 1);
        async Task SendAsync(JsonObject message)
        {
            await sendLock.WaitAsync(cancellationToken);
            try
            {
                if (socket.State == WebSocketState.Open)
                {
                    await socket.SendAsync(Encoding.UTF8.GetBytes(message.ToJsonString()), WebSocketMessageType.Text, true, cancellationToken);
                }
            }
            finally
            {
                sendLock.Release();
            }
        }

        void OnEvent(JsonObject message) => _ = SendQuietlyAsync(SendAsync, message);

        PageEvent += OnEvent;
        try
        {
            await SendAsync(new JsonObject
            {
                ["type"] = "state",
                ["devices"] = new JsonArray(_devices.Select(d => (JsonNode)DeviceJson(d)).ToArray()),
            });
            var buffer = new byte[4096];
            while (true)
            {
                var result = await socket.ReceiveAsync(buffer, cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    break;
                }
                HandlePageMessage(Encoding.UTF8.GetString(buffer, 0, result.Count));
            }
        }
        catch (Exception err) when (err is OperationCanceledException or WebSocketException)
        {
        }
        finally
        {
            PageEvent -= OnEvent;
        }
    }

    private static async Task SendQuietlyAsync(Func<JsonObject, Task> send, JsonObject message)
    {
        try
        {
            await send(message);
        }
        catch (Exception err) when (err is OperationCanceledException or WebSocketException or ObjectDisposedException)
        {
        }
    }

    private void HandlePageMessage(string text)
    {
        try
        {
            HandlePageMessage(JsonNode.Parse(text) as JsonObject);
        }
        catch (Exception err) when (err is JsonException or InvalidOperationException or FormatException)
        {
            // Only our own page sends here; ignore what it should not have sent
        }
    }

    private void HandlePageMessage(JsonObject? message)
    {
        var id = message?["device"]?.GetValue<string>();
        var device = _devices.FirstOrDefault(d => d.Info.Id == id);
        if (message is null || device is null)
        {
            return;
        }
        switch (message["type"]?.GetValue<string>())
        {
            case "press" when IsPlugged(device):
                device.Press(message["key"]?.GetValue<int>() ?? -1, message["pressed"]?.GetValue<bool>() ?? false);
                break;
            case "plug":
                _logger.LogInformation("Simulator: {Id} {Action}", device.Info.Id, message["plugged"]?.GetValue<bool>() == true ? "plugged in" : "unplugged");
                SetPlugged(device.Info.Id, message["plugged"]?.GetValue<bool>() ?? true);
                break;
        }
    }

    private void Publish(JsonObject message) => PageEvent?.Invoke(message);

    private JsonObject DeviceJson(VirtualDevice device)
    {
        var grid = device.Info.Capabilities.Keys!;
        var keys = new JsonObject();
        for (var key = 0; key < grid.Count; key++)
        {
            if (ContentJson(device.GetKey(key)) is { } content)
            {
                keys[key.ToString()] = content;
            }
        }
        return new JsonObject
        {
            ["type"] = "device",
            ["id"] = device.Info.Id,
            ["name"] = device.Info.Name,
            ["cols"] = grid.Cols,
            ["rows"] = grid.Rows,
            ["plugged"] = IsPlugged(device),
            ["brightness"] = device.Brightness,
            ["keys"] = keys,
        };
    }

    private static JsonObject KeyJson(VirtualDevice device, int key) => new()
    {
        ["type"] = "key",
        ["device"] = device.Info.Id,
        ["key"] = key,
        ["content"] = ContentJson(device.GetKey(key)),
    };

    private static JsonObject? ContentJson(VirtualDevice.KeyContent? content) => content switch
    {
        { Image: { } image, Format: { } format } => new JsonObject { ["image"] = $"data:image/{format};base64,{Convert.ToBase64String(image)}" },
        { Color: { } color } => new JsonObject { ["color"] = color },
        _ => null,
    };
}
