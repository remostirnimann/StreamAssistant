using System.Globalization;
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
        foreach (var deck in options.Simulate)
        {
            number++;
            var id = $"sim-{number}";
            var dials = deck.Dials > 0 ? new DialSet(deck.Dials, Press: true) : null;
            var touch = deck.Dials > 0 ? new TouchArea(deck.Dials * SimulatedDeck.SegmentWidth, SimulatedDeck.StripHeight) : null;
            var info = new DeviceInfo(
                Id: id,
                Vendor: "Stream Assistant",
                Model: $"Simulated deck {deck.Cols}×{deck.Rows}" + (deck.Dials > 0 ? $" with {deck.Dials} dials" : ""),
                Name: $"Simulated deck {number}",
                Serial: id,
                Firmware: BridgeServer.Version,
                Virtual: true,
                Capabilities: new DeviceCapabilities(
                    deck.KeySize > 0 ? KeyGrid.Images(deck.Cols, deck.Rows, deck.KeySize) : KeyGrid.Pedals(deck.Cols, deck.Rows),
                    Brightness: deck.KeySize > 0,
                    dials,
                    touch));
            var device = new VirtualDevice(info);
            device.Changed += (d, key) => Publish(key is { } k ? KeyJson(d, k) : DeviceJson(d));
            device.TouchChanged += (d, image) => Publish(new JsonObject { ["type"] = "touch", ["device"] = d.Info.Id, ["image"] = TouchJson(image) });
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
                    // Confirm the close, as the WebSocket protocol asks
                    await sendLock.WaitAsync(cancellationToken);
                    await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, null, cancellationToken);
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
            case "turn" when IsPlugged(device):
                device.Turn(message["dial"]?.GetValue<int>() ?? -1, message["delta"]?.GetValue<int>() ?? 0);
                break;
            case "dial_press" when IsPlugged(device):
                device.PressDial(message["dial"]?.GetValue<int>() ?? -1, message["pressed"]?.GetValue<bool>() ?? false);
                break;
            case "touch" when IsPlugged(device):
                device.Touch(
                    message["kind"]?.GetValue<string>() ?? "",
                    message["x"]?.GetValue<int>() ?? 0,
                    message["y"]?.GetValue<int>() ?? 0,
                    message["x2"]?.GetValue<int>(),
                    message["y2"]?.GetValue<int>());
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
                keys[key.ToString(CultureInfo.InvariantCulture)] = content;
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
            ["dials"] = device.Info.Capabilities.Dials?.Count ?? 0,
            ["touch"] = device.Info.Capabilities.Touch is { } touch
                ? new JsonObject
                {
                    ["width"] = touch.Width,
                    ["height"] = touch.Height,
                    ["images"] = new JsonArray(device.TouchImages.Select(i => (JsonNode)TouchJson(i)).ToArray()),
                }
                : null,
        };
    }

    private static JsonObject KeyJson(VirtualDevice device, int key) => new()
    {
        ["type"] = "key",
        ["device"] = device.Info.Id,
        ["key"] = key,
        ["content"] = ContentJson(device.GetKey(key)),
    };

    private static JsonObject TouchJson(VirtualDevice.TouchImage image) => new()
    {
        ["x"] = image.X,
        ["y"] = image.Y,
        ["width"] = image.Width,
        ["height"] = image.Height,
        ["src"] = $"data:image/{image.Format};base64,{Convert.ToBase64String(image.Image)}",
    };

    private static JsonObject? ContentJson(VirtualDevice.KeyContent? content) => content switch
    {
        { Image: { } image, Format: { } format } => new JsonObject { ["image"] = $"data:image/{format};base64,{Convert.ToBase64String(image)}" },
        { Color: { } color } => new JsonObject { ["color"] = color },
        _ => null,
    };
}
