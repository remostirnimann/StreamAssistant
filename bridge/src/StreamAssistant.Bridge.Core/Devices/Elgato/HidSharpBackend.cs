using System.Diagnostics.CodeAnalysis;
using HidSharp;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// HID access through HidSharp (Windows, macOS, Linux hidraw). Thin and
/// hardware-only: the logic lives in the drivers, tested with fakes.
/// </summary>
[ExcludeFromCodeCoverage]
public sealed class HidSharpBackend : IHidBackend
{
    private int _subscribed;

    public event Action? Changed;

    public IReadOnlyList<HidDeviceEntry> List(int vendorId)
    {
        // DeviceList is touched first here, not in the constructor: on Linux it
        // needs libudev, and a missing library must not stop the bridge
        var list = DeviceList.Local;
        if (Interlocked.Exchange(ref _subscribed, 1) == 0)
        {
            list.Changed += (_, _) => Changed?.Invoke();
        }
        return list.GetHidDevices(vendorId).Select(d => new HidDeviceEntry(d.DevicePath, d.VendorID, d.ProductID, Serial(d))).ToList();
    }

    public IHidDevice Open(string path)
    {
        var device = DeviceList.Local.GetHidDevices().FirstOrDefault(d => d.DevicePath == path)
            ?? throw new IOException($"{path} is gone");
        if (!device.TryOpen(out var stream))
        {
            throw new IOException($"Cannot open {path} (in use by another program, or no permission)");
        }
        stream.ReadTimeout = Timeout.Infinite;
        return new Device(device, stream);
    }

    private static string? Serial(HidDevice device)
    {
        try
        {
            return device.GetSerialNumber();
        }
        catch (Exception err) when (err is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            return null;
        }
    }

    private sealed class Device(HidDevice device, HidStream stream) : IHidDevice
    {
        private readonly int _output = device.GetMaxOutputReportLength();
        private readonly int _feature = device.GetMaxFeatureReportLength();

        public int InputReportLength { get; } = device.GetMaxInputReportLength();

        public void Write(byte[] report) => stream.Write(Fit(report, _output));

        public void SetFeature(byte[] report) => stream.SetFeature(Fit(report, _feature));

        public byte[] GetFeature(byte reportId)
        {
            var buffer = new byte[_feature];
            buffer[0] = reportId;
            stream.GetFeature(buffer);
            return buffer;
        }

        public int Read(byte[] buffer) => stream.Read(buffer, 0, buffer.Length);

        public void Dispose() => stream.Dispose();

        /// <summary>HidSharp wants reports of exactly the length the device declares.</summary>
        private static byte[] Fit(byte[] report, int length)
        {
            if (length <= 0 || report.Length == length)
            {
                return report;
            }
            var fitted = new byte[length];
            report.AsSpan(0, Math.Min(report.Length, length)).CopyTo(fitted);
            return fitted;
        }
    }
}
