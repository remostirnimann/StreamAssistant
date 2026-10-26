using System.Buffers.Binary;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Channels;
using StreamAssistant.Bridge.Devices;

namespace StreamAssistant.Bridge.Protocol;

/// <summary>One protocol connection: handshake, commands from the client, events to it.</summary>
internal sealed partial class ClientSession(BridgeServer server, WebSocket socket, string remote, ILogger<ClientSession> logger)
{
    public static readonly TimeSpan HandshakeTimeout = TimeSpan.FromSeconds(10);

    /// <summary>Largest accepted message; key images are a few kB.</summary>
    public const int MaxMessageBytes = 4 * 1024 * 1024;

    private static readonly TimeSpan CloseTimeout = TimeSpan.FromSeconds(2);

    private readonly Channel<Outgoing> _out = Channel.CreateUnbounded<Outgoing>(new UnboundedChannelOptions { SingleReader = true });
    private CancellationTokenSource? _cts;

    private readonly record struct Outgoing(byte[] Data, WebSocketMessageType Type);

    private readonly record struct Incoming(WebSocketMessageType Type, byte[] Data);

    /// <summary>Thrown to answer a message with a protocol error.</summary>
    private sealed class ProtocolError(string code, string message) : Exception(message)
    {
        public string Code { get; } = code;
    }

    public string ClientName { get; private set; } = "unknown client";

    public string Remote => remote;

    public async Task RunAsync(CancellationToken aborted)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(aborted);
        _cts = cts;
        var writer = WriteLoopAsync(cts.Token);
        var active = false;
        try
        {
            if (await HandshakeAsync(cts.Token))
            {
                active = true;
                server.Devices.Added += OnDeviceAdded;
                server.Devices.Removed += OnDeviceRemoved;
                server.Devices.Input += OnInput;
                Send(new JsonObject
                {
                    ["type"] = "devices",
                    ["devices"] = new JsonArray(server.Devices.All.Select(d => (JsonNode)d.Info.ToJson()).ToArray()),
                });
                await ReadLoopAsync(cts.Token);
            }
        }
        catch (Exception err) when (err is OperationCanceledException or WebSocketException)
        {
            logger.LogDebug("Connection from {Remote} ended: {Error}", remote, err.Message);
        }
        finally
        {
            if (active)
            {
                server.Devices.Added -= OnDeviceAdded;
                server.Devices.Removed -= OnDeviceRemoved;
                server.Devices.Input -= OnInput;
                server.Deactivate(this);
            }
            _out.Writer.TryComplete();
            try
            {
                await writer;
            }
            catch (Exception err) when (err is OperationCanceledException or WebSocketException)
            {
            }
        }
    }

    /// <summary>Another client took over: tell this one and close.</summary>
    public void Replace()
    {
        SendError("replaced", "Another client took over the bridge");
        _out.Writer.TryComplete();
    }

    // Handshake (section 3)

    private async Task<bool> HandshakeAsync(CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(HandshakeTimeout);
        Incoming? first;
        try
        {
            first = await ReceiveAsync(timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            logger.LogDebug("No handshake from {Remote}", remote);
            return Fail("invalid_message", "Expected hello within 10 seconds");
        }
        if (first is null)
        {
            return false;
        }
        if (first.Value.Type != WebSocketMessageType.Text || ParseJson(first.Value.Data) is not { } hello)
        {
            return Fail("invalid_message", "Expected a hello message");
        }

        var type = Str(hello, "type");
        if (type is not ("hello" or "pair"))
        {
            return Fail("invalid_message", "Expected a hello message");
        }
        ClientName = Str(hello, "client") is { Length: > 0 } client ? client[..Math.Min(client.Length, 100)] : "unknown client";
        if (Int(hello, "protocol") != BridgeServer.ProtocolVersion)
        {
            SendError("unsupported_protocol", $"This bridge speaks protocol {BridgeServer.ProtocolVersion}",
                extra: new JsonObject { ["supported"] = new JsonArray(BridgeServer.ProtocolVersion) });
            _out.Writer.TryComplete();
            return false;
        }

        if (type == "pair")
        {
            switch (server.Pairing.TryPair(Str(hello, "code"), ClientName, out var token))
            {
                case PairingResult.Paired:
                    Send(new JsonObject { ["type"] = "paired", ["token"] = token });
                    break;
                case PairingResult.LockedOut:
                    return Fail("invalid_code", "Too many wrong codes, try again in a minute");
                default:
                    logger.LogInformation("Wrong pairing code from {Client} ({Remote})", ClientName, remote);
                    return Fail("invalid_code", "Wrong pairing code");
            }
        }
        else if (!server.Pairing.IsAuthorized(Str(hello, "token")))
        {
            logger.LogInformation("Unpaired client {Client} ({Remote}) refused", ClientName, remote);
            return Fail("unauthorized", "Pair with this bridge first");
        }

        server.Activate(this);
        Send(new JsonObject
        {
            ["type"] = "welcome",
            ["protocol"] = BridgeServer.ProtocolVersion,
            ["bridge"] = server.BridgeJson(),
            ["features"] = new JsonArray(BridgeServer.Features.Select(f => (JsonNode)f).ToArray()),
        });
        return true;
    }

    private bool Fail(string code, string message)
    {
        SendError(code, message);
        _out.Writer.TryComplete();
        return false;
    }

    // Commands (sections 5-7)

    private async Task ReadLoopAsync(CancellationToken cancellationToken)
    {
        while (await ReceiveAsync(cancellationToken) is { } message)
        {
            if (message.Type == WebSocketMessageType.Text)
            {
                if (ParseJson(message.Data) is { } command)
                {
                    await HandleAsync(command, ReadOnlyMemory<byte>.Empty, cancellationToken);
                }
                else
                {
                    SendError("invalid_message", "Messages must be JSON objects");
                }
            }
            else if (SplitEnvelope(message.Data) is var (header, payload))
            {
                await HandleAsync(header, payload, cancellationToken);
            }
            else
            {
                SendError("invalid_message", "Malformed binary envelope");
            }
        }
    }

    private async Task HandleAsync(JsonObject command, ReadOnlyMemory<byte> payload, CancellationToken cancellationToken)
    {
        var type = Str(command, "type") ?? "";
        var id = command["id"] is JsonValue idValue && idValue.TryGetValue<int>(out var number) ? number : (int?)null;
        try
        {
            await ExecuteAsync(type, command, payload, cancellationToken);
            if (id is not null)
            {
                Send(new JsonObject { ["type"] = "result", ["id"] = id, ["ok"] = true });
            }
        }
        catch (Exception err) when (err is ProtocolError or DeviceException)
        {
            var code = err is ProtocolError protocol ? protocol.Code : ((DeviceException)err).Code;
            if (id is not null)
            {
                Send(new JsonObject
                {
                    ["type"] = "result",
                    ["id"] = id,
                    ["ok"] = false,
                    ["error"] = new JsonObject { ["code"] = code, ["message"] = err.Message },
                });
            }
            else
            {
                SendError(code, err.Message, request: type);
            }
        }
        catch (Exception err) when (err is not OperationCanceledException)
        {
            // A driver failed unexpectedly: report it, keep the session
            logger.LogWarning(err, "{Type} failed", type);
            if (id is not null)
            {
                Send(new JsonObject
                {
                    ["type"] = "result",
                    ["id"] = id,
                    ["ok"] = false,
                    ["error"] = new JsonObject { ["code"] = "device_error", ["message"] = err.Message },
                });
            }
            else
            {
                SendError("device_error", err.Message, request: type);
            }
        }
    }

    private Task ExecuteAsync(string type, JsonObject command, ReadOnlyMemory<byte> payload, CancellationToken cancellationToken)
    {
        switch (type)
        {
            case "set_brightness":
                {
                    var device = Device(command);
                    if (!device.Info.Capabilities.Brightness)
                    {
                        throw new ProtocolError("unsupported", "The device has no adjustable brightness");
                    }
                    return device.SetBrightnessAsync(Range(command, "percent", 0, 100), cancellationToken);
                }
            case "set_key_image":
                {
                    var device = Device(command);
                    var grid = Keys(device);
                    if (!grid.HasImages)
                    {
                        throw new ProtocolError("unsupported", grid.InputOnly ? "The keys of this device have no display" : "The keys of this device only show colours");
                    }
                    var key = Range(command, "key", 0, grid.Count - 1);
                    var format = Str(command, "format");
                    if (format is null || !grid.Formats.Contains(format))
                    {
                        throw new ProtocolError("invalid_message", $"format must be one of {string.Join(", ", grid.Formats)}");
                    }
                    if (payload.IsEmpty)
                    {
                        throw new ProtocolError("invalid_message", "set_key_image is sent as a binary envelope with the image");
                    }
                    return device.SetKeyImageAsync(key, format, payload, cancellationToken);
                }
            case "set_touch_image":
                {
                    var device = Device(command);
                    var touch = device.Info.Capabilities.Touch ?? throw new ProtocolError("unsupported", "The device has no touch display");
                    var x = Range(command, "x", 0, touch.Width - 1);
                    var y = Range(command, "y", 0, touch.Height - 1);
                    var width = Range(command, "width", 1, touch.Width - x);
                    var height = Range(command, "height", 1, touch.Height - y);
                    var format = Str(command, "format");
                    if (format is not ("jpeg" or "png"))
                    {
                        throw new ProtocolError("invalid_message", "format must be jpeg or png");
                    }
                    if (payload.IsEmpty)
                    {
                        throw new ProtocolError("invalid_message", "set_touch_image is sent as a binary envelope with the image");
                    }
                    return device.SetTouchImageAsync(x, y, width, height, format, payload, cancellationToken);
                }
            case "set_key_color":
                {
                    var device = Device(command);
                    var key = Range(command, "key", 0, Display(device).Count - 1);
                    var color = Str(command, "color");
                    if (color is null || !ColorPattern().IsMatch(color))
                    {
                        throw new ProtocolError("invalid_message", "color must look like #rrggbb");
                    }
                    return device.SetKeyColorAsync(key, color.ToLowerInvariant(), cancellationToken);
                }
            case "clear_key":
                {
                    var device = Device(command);
                    return device.ClearKeyAsync(Range(command, "key", 0, Display(device).Count - 1), cancellationToken);
                }
            case "reset":
                return Device(command).ResetAsync(cancellationToken);
            case "identify":
                return Device(command).IdentifyAsync(cancellationToken);
            default:
                throw new ProtocolError("invalid_message", $"Unknown message type '{type}'");
        }
    }

    private IControlDevice Device(JsonObject command)
    {
        var id = Str(command, "device") ?? throw new ProtocolError("invalid_message", "device is missing");
        return server.Devices.Get(id) ?? throw new ProtocolError("unknown_device", $"No device {id}");
    }

    private static KeyGrid Keys(IControlDevice device) =>
        device.Info.Capabilities.Keys ?? throw new ProtocolError("unsupported", "The device has no keys");

    /// <summary>Keys that show something (image or colour).</summary>
    private static KeyGrid Display(IControlDevice device)
    {
        var grid = Keys(device);
        return grid.InputOnly ? throw new ProtocolError("unsupported", "The keys of this device have no display") : grid;
    }

    private static int Range(JsonObject command, string field, int min, int max)
    {
        var value = Int(command, field) ?? throw new ProtocolError("invalid_message", $"{field} is missing or not an integer");
        if (value < min || value > max)
        {
            throw new ProtocolError("invalid_message", $"{field} must be between {min} and {max}");
        }
        return value;
    }

    // Events to the client

    private void OnDeviceAdded(IControlDevice device) =>
        Send(new JsonObject { ["type"] = "device_added", ["device"] = device.Info.ToJson() });

    private void OnDeviceRemoved(string id) =>
        Send(new JsonObject { ["type"] = "device_removed", ["device"] = id });

    private void OnInput(IControlDevice device, DeviceInput input) => Send(input.ToJson(device.Info.Id));

    // Sending and receiving

    private void SendError(string code, string message, string? request = null, JsonObject? extra = null)
    {
        var error = new JsonObject { ["type"] = "error", ["code"] = code, ["message"] = message };
        if (request is not null)
        {
            error["request"] = request;
        }
        foreach (var (name, value) in extra ?? [])
        {
            error[name] = value?.DeepClone();
        }
        Send(error);
    }

    private void Send(JsonObject message) =>
        _out.Writer.TryWrite(new Outgoing(Encoding.UTF8.GetBytes(message.ToJsonString()), WebSocketMessageType.Text));

    private async Task WriteLoopAsync(CancellationToken cancellationToken)
    {
        await foreach (var message in _out.Reader.ReadAllAsync(cancellationToken))
        {
            await socket.SendAsync(message.Data, message.Type, endOfMessage: true, cancellationToken);
        }
        // Nothing more to send (handshake failed, replaced or the client left): close
        if (socket.State is WebSocketState.Open or WebSocketState.CloseReceived)
        {
            using var timeout = new CancellationTokenSource(CloseTimeout);
            await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, null, timeout.Token);
        }
        // Do not wait forever for the client to confirm the close
        _cts?.CancelAfter(CloseTimeout);
    }

    private async Task<Incoming?> ReceiveAsync(CancellationToken cancellationToken)
    {
        var buffer = new byte[16 * 1024];
        using var data = new MemoryStream();
        while (true)
        {
            var result = await socket.ReceiveAsync(buffer, cancellationToken);
            if (result.MessageType == WebSocketMessageType.Close)
            {
                return null;
            }
            if (data.Length + result.Count > MaxMessageBytes)
            {
                await socket.CloseAsync(WebSocketCloseStatus.MessageTooBig, "Message too big", cancellationToken);
                return null;
            }
            data.Write(buffer, 0, result.Count);
            if (result.EndOfMessage)
            {
                return new Incoming(result.MessageType, data.ToArray());
            }
        }
    }

    /// <summary>Binary envelope (section 6): u16 big-endian header length, JSON header, payload.</summary>
    internal static (JsonObject Header, ReadOnlyMemory<byte> Payload)? SplitEnvelope(byte[] frame)
    {
        if (frame.Length < 2)
        {
            return null;
        }
        var length = BinaryPrimitives.ReadUInt16BigEndian(frame);
        if (frame.Length < 2 + length || ParseJson(frame.AsSpan(2, length).ToArray()) is not { } header)
        {
            return null;
        }
        return (header, frame.AsMemory(2 + length));
    }

    private static JsonObject? ParseJson(byte[] data)
    {
        try
        {
            return JsonNode.Parse(data) as JsonObject;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static string? Str(JsonObject message, string field) =>
        message[field] is JsonValue value && value.TryGetValue<string>(out var text) ? text : null;

    private static int? Int(JsonObject message, string field) =>
        message[field] is JsonValue value && value.TryGetValue<int>(out var number) ? number : null;

    [GeneratedRegex("^#[0-9a-fA-F]{6}$")]
    private static partial Regex ColorPattern();
}
