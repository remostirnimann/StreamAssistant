using System.Text.Json.Nodes;

namespace StreamAssistant.Bridge.Devices;

/// <summary>
/// Grid of keys: image keys (<see cref="ImageWidth"/> > 0), colour-only keys, or
/// keys without any display (<see cref="InputOnly"/>, e.g. pedals).
/// </summary>
public sealed record KeyGrid(int Cols, int Rows, int ImageWidth, int ImageHeight, IReadOnlyList<string> Formats, bool InputOnly = false)
{
    public int Count => Cols * Rows;
    public bool HasImages => ImageWidth > 0;

    public static KeyGrid Images(int cols, int rows, int size, params string[] formats) =>
        Images(cols, rows, size, size, formats);

    /// <summary>Keys with images of <paramref name="width"/> × <paramref name="height"/> (not always square).</summary>
    public static KeyGrid Images(int cols, int rows, int width, int height, params string[] formats) =>
        new(cols, rows, width, height, formats.Length > 0 ? formats : ["jpeg", "png"]);

    public static KeyGrid ColorsOnly(int cols, int rows) => new(cols, rows, 0, 0, []);

    /// <summary>Keys without any display, such as pedals.</summary>
    public static KeyGrid Pedals(int cols, int rows) => new(cols, rows, 0, 0, [], InputOnly: true);
}

/// <summary>Dials; <paramref name="Ring"/> is the number of LEDs in a ring around each (0: none).</summary>
public sealed record DialSet(int Count, bool Press, int Ring = 0);

public sealed record TouchArea(int Width, int Height);

/// <summary>Buttons outside the key grid (e.g. the page buttons of the Neo), optionally lit in a colour.</summary>
public sealed record ButtonSet(int Count, bool Colors);

/// <summary>A display without touch input (e.g. the info display of the Neo).</summary>
public sealed record ScreenArea(int Width, int Height);

/// <summary>What a device can do (protocol section 4.2).</summary>
public sealed record DeviceCapabilities(
    KeyGrid? Keys,
    bool Brightness,
    DialSet? Dials = null,
    TouchArea? Touch = null,
    ButtonSet? Buttons = null,
    ScreenArea? Screen = null,
    bool Nfc = false);

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
            else if (!keys.InputOnly)
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
            if (dials.Ring > 0)
            {
                caps["dials"]!["ring"] = dials.Ring;
            }
        }
        if (Capabilities.Touch is { } touch)
        {
            caps["touch"] = new JsonObject { ["width"] = touch.Width, ["height"] = touch.Height };
        }
        if (Capabilities.Buttons is { } buttons)
        {
            caps["buttons"] = new JsonObject { ["count"] = buttons.Count, ["colors"] = buttons.Colors };
        }
        if (Capabilities.Screen is { } screen)
        {
            caps["screen"] = new JsonObject
            {
                ["width"] = screen.Width,
                ["height"] = screen.Height,
                ["formats"] = new JsonArray("jpeg", "png"),
            };
        }
        if (Capabilities.Nfc)
        {
            caps["nfc"] = true;
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

/// <summary>A touch display was tapped, held or swiped (pixels from the top left).</summary>
public sealed record TouchInput(string Kind, int X, int Y, int? X2 = null, int? Y2 = null) : DeviceInput
{
    public const string Tap = "tap";
    public const string Hold = "long";
    public const string Swipe = "swipe";

    public override JsonObject ToJson(string deviceId)
    {
        var json = new JsonObject { ["type"] = "touch", ["device"] = deviceId, ["kind"] = Kind, ["x"] = X, ["y"] = Y };
        if (X2 is { } x2 && Y2 is { } y2)
        {
            json["x2"] = x2;
            json["y2"] = y2;
        }
        return json;
    }
}

/// <summary>A button outside the key grid went down or up.</summary>
public sealed record ButtonInput(int Button, bool Pressed) : DeviceInput
{
    public override JsonObject ToJson(string deviceId) =>
        new() { ["type"] = "button", ["device"] = deviceId, ["button"] = Button, ["pressed"] = Pressed };
}

/// <summary>An NFC tag was read.</summary>
public sealed record NfcInput(string Id) : DeviceInput
{
    public override JsonObject ToJson(string deviceId) => new() { ["type"] = "nfc", ["device"] = deviceId, ["id"] = Id };
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

    /// <summary>Show an upright image on an area of the touch display (already checked against its size).</summary>
    Task SetTouchImageAsync(int x, int y, int width, int height, string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken);

    /// <summary>Light a button outside the grid; black is off.</summary>
    Task SetButtonColorAsync(int button, string color, CancellationToken cancellationToken);

    /// <summary>Show an upright image on the whole screen.</summary>
    Task SetScreenImageAsync(string format, ReadOnlyMemory<byte> image, CancellationToken cancellationToken);

    /// <summary>Light <paramref name="level"/> (0–1) of a dial's LED ring, and its centre, in <paramref name="color"/>.</summary>
    Task SetDialLedsAsync(int dial, string color, double level, CancellationToken cancellationToken);

    Task ClearKeyAsync(int key, CancellationToken cancellationToken);

    /// <summary>Show the idle screen (vendor logo or blank).</summary>
    Task ResetAsync(CancellationToken cancellationToken);

    Task IdentifyAsync(CancellationToken cancellationToken);
}
