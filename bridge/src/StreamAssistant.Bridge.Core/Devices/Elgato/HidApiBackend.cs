using System.Diagnostics.CodeAnalysis;
using System.Runtime.InteropServices;
using System.Text;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// HID access through hidapi over libusb (<c>libhidapi-libusb.so.0</c>, Alpine package
/// <c>hidapi</c>). A Home Assistant add-on gets raw USB access (<c>/dev/bus/usb</c>, follows
/// plugging) but no hidraw devices, which HidSharp needs. Thin and hardware-only like
/// <see cref="HidSharpBackend"/>; the drivers are tested with fakes.
/// </summary>
[ExcludeFromCodeCoverage]
public sealed partial class HidApiBackend : IHidBackend
{
    private const string Library = "libhidapi-libusb.so.0";

    /// <summary>Elgato reports are at most 1024 bytes; features far less.</summary>
    private const int FeatureLength = 512;

    private static readonly Lock InitLock = new();
    private static bool _initialized;

    private readonly ILogger<HidApiBackend> _logger;

    public HidApiBackend(ILogger<HidApiBackend> logger) => _logger = logger;

    /// <summary>Never raised: libusb has no plug events here, the watcher polls.</summary>
    public event Action? Changed
    {
        add { }
        remove { }
    }

    public IReadOnlyList<HidDeviceEntry> List(int vendorId)
    {
        Init();
        var list = new List<HidDeviceEntry>();
        var first = hid_enumerate((ushort)vendorId, 0);
        try
        {
            // struct hid_device_info on 64-bit: path @0, vendor_id @8, product_id @10,
            // serial_number @16, ..., next @56
            for (var info = first; info != IntPtr.Zero; info = Marshal.ReadIntPtr(info, 56))
            {
                var path = Marshal.PtrToStringUTF8(Marshal.ReadIntPtr(info, 0));
                if (path is null)
                {
                    continue;
                }
                list.Add(new HidDeviceEntry(
                    path,
                    (ushort)Marshal.ReadInt16(info, 8),
                    (ushort)Marshal.ReadInt16(info, 10),
                    WideString(Marshal.ReadIntPtr(info, 16))));
            }
        }
        finally
        {
            if (first != IntPtr.Zero)
            {
                hid_free_enumeration(first);
            }
        }
        return list;
    }

    public IHidDevice Open(string path)
    {
        Init();
        var handle = hid_open_path(path);
        if (handle == IntPtr.Zero)
        {
            throw new IOException($"Cannot open {path} (in use by another program, or no USB access)");
        }
        _logger.LogDebug("Opened {Path} through libusb", path);
        return new Device(handle);
    }

    private static void Init()
    {
        lock (InitLock)
        {
            if (!_initialized)
            {
                if (hid_init() != 0)
                {
                    throw new IOException("hidapi could not start libusb");
                }
                _initialized = true;
            }
        }
    }

    /// <summary>wchar_t strings are UTF-32 on Linux.</summary>
    private static string? WideString(IntPtr text)
    {
        if (text == IntPtr.Zero)
        {
            return null;
        }
        var bytes = new List<byte>();
        for (var offset = 0; ; offset += 4)
        {
            var c = Marshal.ReadInt32(text, offset);
            if (c == 0)
            {
                break;
            }
            bytes.AddRange(BitConverter.GetBytes(c));
        }
        return Encoding.UTF32.GetString([.. bytes]);
    }

    private sealed class Device(IntPtr handle) : IHidDevice
    {
        private const int ReadTimeoutMs = 250;

        private IntPtr _handle = handle;

        // hid_close must not run while another thread is inside a call on the handle
        private readonly Lock _readLock = new();
        private readonly Lock _writeLock = new();
        private volatile bool _closed;

        /// <summary>Unknown to hidapi; the drivers read at least 512 bytes.</summary>
        public int InputReportLength => 0;

        public void Write(byte[] report)
        {
            lock (_writeLock)
            {
                Check(_closed ? -1 : hid_write(_handle, report, report.Length), "write");
            }
        }

        public void SetFeature(byte[] report)
        {
            lock (_writeLock)
            {
                Check(_closed ? -1 : hid_send_feature_report(_handle, report, report.Length), "set feature");
            }
        }

        public byte[] GetFeature(byte reportId)
        {
            var buffer = new byte[FeatureLength];
            buffer[0] = reportId;
            lock (_writeLock)
            {
                Check(_closed ? -1 : hid_get_feature_report(_handle, buffer, buffer.Length), "get feature");
            }
            return buffer;
        }

        public int Read(byte[] buffer)
        {
            while (true)
            {
                lock (_readLock)
                {
                    var read = _closed ? -1 : hid_read_timeout(_handle, buffer, buffer.Length, ReadTimeoutMs);
                    if (read > 0)
                    {
                        return read;
                    }
                    Check(read, "read");
                }
            }
        }

        public void Dispose()
        {
            _closed = true;
            lock (_readLock)
            {
                lock (_writeLock)
                {
                    if (_handle != IntPtr.Zero)
                    {
                        hid_close(_handle);
                        _handle = IntPtr.Zero;
                    }
                }
            }
        }

        private void Check(int result, string what)
        {
            if (result < 0)
            {
                var error = _closed || _handle == IntPtr.Zero ? "closed" : WideString(hid_error(_handle)) ?? "error";
                throw new IOException($"HID {what} failed: {error}");
            }
        }
    }

    [LibraryImport(Library)]
    private static partial int hid_init();

    [LibraryImport(Library)]
    private static partial IntPtr hid_enumerate(ushort vendorId, ushort productId);

    [LibraryImport(Library)]
    private static partial void hid_free_enumeration(IntPtr devices);

    [LibraryImport(Library, StringMarshalling = StringMarshalling.Utf8)]
    private static partial IntPtr hid_open_path(string path);

    [LibraryImport(Library)]
    private static partial int hid_write(IntPtr device, byte[] data, nint length);

    [LibraryImport(Library)]
    private static partial int hid_read_timeout(IntPtr device, [Out] byte[] data, nint length, int milliseconds);

    [LibraryImport(Library)]
    private static partial int hid_send_feature_report(IntPtr device, byte[] data, nint length);

    [LibraryImport(Library)]
    private static partial int hid_get_feature_report(IntPtr device, [In, Out] byte[] data, nint length);

    [LibraryImport(Library)]
    private static partial void hid_close(IntPtr device);

    [LibraryImport(Library)]
    private static partial IntPtr hid_error(IntPtr device);
}
