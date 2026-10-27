namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>A HID device as the operating system lists it.</summary>
public sealed record HidDeviceEntry(string Path, int VendorId, int ProductId, string? Serial);

/// <summary>
/// An open HID device. Reports start with the report id. Only one thread
/// writes and one thread reads at a time.
/// </summary>
public interface IHidDevice : IDisposable
{
    /// <summary>Send an output report.</summary>
    void Write(byte[] report);

    void SetFeature(byte[] report);

    byte[] GetFeature(byte reportId);

    /// <summary>Blocks until an input report arrives; throws once the device is gone or disposed.</summary>
    int Read(byte[] buffer);

    int InputReportLength { get; }
}

/// <summary>Lists and opens HID devices; hides the HID library so the drivers can be tested.</summary>
public interface IHidBackend
{
    IReadOnlyList<HidDeviceEntry> List(int vendorId);

    IHidDevice Open(string path);

    /// <summary>Raised when devices were plugged in or out (any vendor; may be missed, so also poll).</summary>
    event Action? Changed;
}
