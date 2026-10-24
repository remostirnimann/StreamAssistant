using System.Text.Json.Nodes;

namespace StreamAssistant.Bridge.Devices;

/// <summary>Grid of keys. Either image keys (<see cref="ImageWidth"/> > 0) or colour-only keys.</summary>
public sealed record KeyGrid(int Cols, int Rows, int ImageWidth, int ImageHeight, IReadOnlyList<string> Formats)
{
    public int Count => Cols * Rows;
    public bool HasImages => ImageWidth > 0;

    public static KeyGrid Images(int cols, int rows, int size, params string[] formats) =>
        new(cols, rows, size, size, formats.Length > 0 ? formats : ["jpeg", "png"]);

    public static KeyGrid ColorsOnly(int cols, int rows) => new(cols, rows, 0, 0, []);
}

public sealed record DialSet(int Count, bool Press);

public sealed record TouchArea(int Width, int Height);

/// <summary>What a device can do (protocol section 4.2).</summary>
public sealed record DeviceCapabilities(KeyGrid? Keys, bool Brightness, DialSet? Dials = null, TouchArea? Touch = null);

/// <summary>Static facts about a device, as sent in the inventory.</summary>
public sealed record DeviceInfo(
    string Id,
    string Vendor,
    string Model,
    string Name,
    string? Serial,
    string? Firmware,
    bool Virtual,
    DeviceCapabilities Capabilities)
{
    public JsonObject ToJson()
    {
        var caps = new JsonObject();
        if (Capabilities.Keys is { } keys)
        {
            var grid = new JsonObject { ["cols"] = keys.Cols, ["rows"] = keys.Rows };
            if (keys.HasImages)
            {
                grid["image"] = new JsonObject
                {
                    ["width"] = keys.ImageWidth,
                    ["height"] = keys.ImageHeight,
                    ["formats"] = new JsonArray(keys.Formats.Select(f => (JsonNode)f).ToArray()),
                };
            }
            else
            {
                grid["colors"] = true;
            }
            caps["keys"] = grid;
        }
        if (Capabilities.Brightness)
        {
            caps["brightness"] = true;
        }
        if (Capabilities.Dials is { } dials)
        {
            caps["dials"] = new JsonObject { ["count"] = dials.Count, ["press"] = dials.Press };
        }
        if (Capabilities.Touch is { } touch)
        {
            caps["touch"] = new JsonObject { ["width"] = touch.Width, ["height"] = touch.Height };
        }
        return new JsonObject
        {
            ["id"] = Id,
            ["vendor"] = Vendor,
            ["model"] = Model,
            ["name"] = Name,
            ["serial"] = Serial,
            ["firmware"] = Firmware,
            ["virtual"] = Virtual,
            ["capabilities"] = caps,
        };
    }
}

/// <summary>Raw input from a device (protocol section 9).</summary>
public abstract record DeviceInput
{
    public abstract JsonObject ToJson(string deviceId);
}

public sealed record KeyInput(int Key, bool Pressed) : DeviceInput
{
    public override JsonObject ToJson(string deviceId) =>
        new() { ["type"] = "key", ["device"] = deviceId, ["key"] = Key, ["pressed"] = Pressed };
}

public sealed record DialInput(int Dial, int Delta) : DeviceInput
{
    public override JsonObject ToJson(string deviceId) =>
        new() { ["type"] = "dial", ["device"] = deviceId, ["dial"] = Dial, ["delta"] = Delta };
}

public sealed record DialPressInput(int Dial, bool Pressed) : DeviceInput
{
    public override JsonObject ToJson(string deviceId) =>
        new() { ["type"] = "dial_press", ["device"] = deviceId, ["dial"] = Dial, ["pressed"] = Pressed };
}

/// <summary>A failure the client gets told about, with a protocol error code (section 8).</summary>
public sealed class DeviceException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}

/// <summary>
/// One control surface, driven by a vendor driver (or simulated).
/// Calls must return quickly; drivers queue slow hardware writes themselves
/// and keep only the newest image per key.
/// </summary>
public interface IControlDevice
{
    DeviceInfo Info { get; }

    /// <summary>Raised from any thread for every key/dial/touch event.</summary>
    event Action<IControlDevice, DeviceInput>? Input;

    Task SetBrightnessAsync(int percent, CancellationToken cancellationToken);

    /// <summary>Show an upright image (already encoded in <paramref name="format"/>).</summary>
    Task SetKeyImageAsync(int key, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken);

    Task SetKeyColorAsync(int key, string color, CancellationToken cancellationToken);

    Task ClearKeyAsync(int key, CancellationToken cancellationToken);

    /// <summary>Show the idle screen (vendor logo or blank).</summary>
    Task ResetAsync(CancellationToken cancellationToken);

    Task IdentifyAsync(CancellationToken cancellationToken);
}
