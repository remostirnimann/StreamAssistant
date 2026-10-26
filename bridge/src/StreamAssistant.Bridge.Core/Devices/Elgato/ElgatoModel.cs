using System.Buffers.Binary;
using System.Text;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>How a group of Stream Decks talks over USB.</summary>
public enum ElgatoFamily
{
    /// <summary>Stream Deck (first model): BMP keys, mirrored, two large packets, keys numbered right to left.</summary>
    Original,

    /// <summary>Mini and 6 Module: BMP keys, turned, first-generation reports.</summary>
    Mini,

    /// <summary>MK.2, Original v2, XL and modules: JPEG keys, mounted upside down.</summary>
    Gen2,

    /// <summary>Stream Deck +: JPEG keys (upright), four dials and a touch strip.</summary>
    Plus,

    /// <summary>Stream Deck Pedal: three pedals, no display.</summary>
    Pedal,
}

/// <summary>
/// A Stream Deck model and its USB reports. Follows the reference implementation
/// node-elgato-stream-deck; the Gen2 data matches custom_components/stream_assistant/protocol/models.py.
/// </summary>
public sealed record ElgatoModel(
    string Name,
    IReadOnlyList<int> ProductIds,
    ElgatoFamily Family,
    int Cols,
    int Rows,
    int KeySize,
    int Dials = 0,
    int TouchWidth = 0,
    int TouchHeight = 0)
{
    public const int VendorId = 0x0FD9;

    private const int PacketSize = 1024;
    private const int OriginalPacketSize = 8191;
    private const int FeatureSize = 32;

    public static readonly IReadOnlyList<ElgatoModel> All =
    [
        new("Stream Deck MK.2", [0x0080, 0x00A5], ElgatoFamily.Gen2, 5, 3, 72),
        new("Stream Deck Original v2", [0x006D], ElgatoFamily.Gen2, 5, 3, 72),
        new("Stream Deck 15 Module", [0x00B9, 0x00E4], ElgatoFamily.Gen2, 5, 3, 72),
        new("Stream Deck XL", [0x006C, 0x008F], ElgatoFamily.Gen2, 8, 4, 96),
        new("Stream Deck 32 Module", [0x00BA], ElgatoFamily.Gen2, 8, 4, 96),
        new("Stream Deck +", [0x0084], ElgatoFamily.Plus, 4, 2, 120, Dials: 4, TouchWidth: 800, TouchHeight: 100),
        new("Stream Deck Mini", [0x0063, 0x0090, 0x00B3], ElgatoFamily.Mini, 3, 2, 80),
        new("Stream Deck 6 Module", [0x00B8], ElgatoFamily.Mini, 3, 2, 80),
        new("Stream Deck", [0x0060], ElgatoFamily.Original, 5, 3, 72),
        new("Stream Deck Pedal", [0x0086], ElgatoFamily.Pedal, 3, 1, 0),
    ];

    public int KeyCount => Cols * Rows;

    /// <summary>The keys show images (everything but the Pedal).</summary>
    public bool HasDisplay => KeySize > 0;

    public bool HasTouch => TouchWidth > 0 && TouchHeight > 0;

    private bool IsGen1 => Family is ElgatoFamily.Original or ElgatoFamily.Mini;

    public static ElgatoModel? Find(int vendorId, int productId) =>
        vendorId == VendorId ? All.FirstOrDefault(m => m.ProductIds.Contains(productId)) : null;

    public DeviceCapabilities Capabilities() => new(
        HasDisplay ? KeyGrid.Images(Cols, Rows, KeySize, "jpeg", "png") : KeyGrid.Pedals(Cols, Rows),
        Brightness: HasDisplay,
        Dials > 0 ? new DialSet(Dials, Press: true) : null,
        HasTouch ? new TouchArea(TouchWidth, TouchHeight) : null);

    /// <summary>The key number the deck uses: the first Stream Deck counts each row from the right.</summary>
    public int HidKey(int key) =>
        Family == ElgatoFamily.Original ? (key / Cols * Cols) + (Cols - 1 - (key % Cols)) : key;

    /// <summary>An upright RGB image of a key, prepared as the deck wants it (JPEG or BMP).</summary>
    public byte[] EncodeKey(byte[] rgb) => Family switch
    {
        ElgatoFamily.Gen2 => KeyImages.Jpeg(KeyImages.Transform(rgb, KeySize, rotate: false, xFlip: true, yFlip: true), KeySize, KeySize),
        ElgatoFamily.Mini => KeyImages.Bmp(KeyImages.Transform(rgb, KeySize, rotate: true, xFlip: false, yFlip: true), KeySize, 2835),
        ElgatoFamily.Original => KeyImages.Bmp(KeyImages.Transform(rgb, KeySize, rotate: false, xFlip: true, yFlip: false), KeySize, 3780),
        _ => KeyImages.Jpeg(rgb, KeySize, KeySize),
    };

    /// <summary>The output reports that show an encoded image on a key.</summary>
    public IEnumerable<byte[]> ImageReports(int key, byte[] image)
    {
        var hidKey = HidKey(key);
        switch (Family)
        {
            case ElgatoFamily.Original:
                {
                    // Always two packets, the image split in halves
                    var half = image.Length / 2;
                    yield return Gen1Packet(OriginalPacketSize, hidKey, 1, last: false, image.AsSpan(0, half));
                    yield return Gen1Packet(OriginalPacketSize, hidKey, 2, last: true, image.AsSpan(half));
                    break;
                }
            case ElgatoFamily.Mini:
                {
                    var offset = 0;
                    var part = 0;
                    do
                    {
                        var length = Math.Min(image.Length - offset, PacketSize - 16);
                        yield return Gen1Packet(PacketSize, hidKey, part++, offset + length >= image.Length, image.AsSpan(offset, length));
                        offset += length;
                    }
                    while (offset < image.Length);
                    break;
                }
            default:
                foreach (var report in Gen2Packets(image, 8, (header, part, last, length) =>
                {
                    header[1] = 0x07;
                    header[2] = (byte)hidKey;
                    header[3] = last ? (byte)1 : (byte)0;
                    BinaryPrimitives.WriteUInt16LittleEndian(header[4..], (ushort)length);
                    BinaryPrimitives.WriteUInt16LittleEndian(header[6..], (ushort)part);
                }))
                {
                    yield return report;
                }
                break;
        }
    }

    /// <summary>The output reports that show a JPEG on an area of the touch strip (Stream Deck +).</summary>
    public static IEnumerable<byte[]> TouchReports(int x, int y, int width, int height, byte[] jpeg) =>
        Gen2Packets(jpeg, 16, (header, part, last, length) =>
        {
            header[1] = 0x0C;
            BinaryPrimitives.WriteUInt16LittleEndian(header[2..], (ushort)x);
            BinaryPrimitives.WriteUInt16LittleEndian(header[4..], (ushort)y);
            BinaryPrimitives.WriteUInt16LittleEndian(header[6..], (ushort)width);
            BinaryPrimitives.WriteUInt16LittleEndian(header[8..], (ushort)height);
            header[10] = last ? (byte)1 : (byte)0;
            BinaryPrimitives.WriteUInt16LittleEndian(header[11..], (ushort)part);
            BinaryPrimitives.WriteUInt16LittleEndian(header[13..], (ushort)length);
        });

    public byte[] BrightnessReport(int percent)
    {
        var value = (byte)Math.Clamp(percent, 0, 100);
        return IsGen1 ? Feature(17, 0x05, 0x55, 0xAA, 0xD1, 0x01, value) : Feature(FeatureSize, 0x03, 0x08, value);
    }

    /// <summary>Shows the Elgato logo.</summary>
    public byte[] ResetReport() => IsGen1 ? Feature(17, 0x0B, 0x63) : Feature(FeatureSize, 0x03, 0x02);

    /// <summary>Fills a key with a colour without an image; null where the deck cannot (first generation).</summary>
    public byte[]? ColorReport(int key, byte red, byte green, byte blue) =>
        Family is ElgatoFamily.Gen2 or ElgatoFamily.Plus ? [0x03, 0x06, (byte)HidKey(key), red, green, blue] : null;

    /// <summary>Firmware version, read from the deck.</summary>
    public string ReadFirmware(IHidDevice hid)
    {
        if (!IsGen1)
        {
            return ReportString(hid.GetFeature(0x05), 6);
        }
        if (Family == ElgatoFamily.Mini && TryRead(() => PrintableFrom(hid.GetFeature(0xA1), 5)) is { Length: > 0 } mini)
        {
            return mini;
        }
        return PrintableFrom(hid.GetFeature(0x04), 5);
    }

    /// <summary>Serial number, read from the deck (when the USB descriptor has none).</summary>
    public string ReadSerial(IHidDevice hid) =>
        IsGen1 ? PrintableFrom(hid.GetFeature(0x03), 5) : ReportString(hid.GetFeature(0x06), 2);

    /// <summary>Turns input reports into key, dial and touch events (keeps the previous states).</summary>
    public sealed class InputParser(ElgatoModel model)
    {
        private readonly bool[] _keys = new bool[model.KeyCount];
        private readonly bool[] _dials = new bool[model.Dials];

        public IEnumerable<DeviceInput> Parse(byte[] report, int length)
        {
            if (length < 2 || report[0] != 0x01)
            {
                return [];
            }
            return model.Family switch
            {
                ElgatoFamily.Original or ElgatoFamily.Mini => Keys(report, length, 1),
                ElgatoFamily.Pedal => Keys(report, length, 4),
                _ => report[1] switch
                {
                    0x00 => Keys(report, length, 4),
                    0x02 when model.HasTouch => Touch(report, length),
                    0x03 when model.Dials > 0 => Dials(report, length),
                    _ => [],
                },
            };
        }

        private List<DeviceInput> Keys(byte[] report, int length, int offset)
        {
            var events = new List<DeviceInput>();
            if (length < offset + _keys.Length)
            {
                return events;
            }
            for (var key = 0; key < _keys.Length; key++)
            {
                var pressed = report[offset + model.HidKey(key)] != 0;
                if (pressed != _keys[key])
                {
                    _keys[key] = pressed;
                    events.Add(new KeyInput(key, pressed));
                }
            }
            return events;
        }

        private static List<DeviceInput> Touch(byte[] report, int length)
        {
            if (length < 13)
            {
                return [];
            }
            int Read(int offset) => BinaryPrimitives.ReadUInt16LittleEndian(report.AsSpan(offset));
            return report[4] switch
            {
                1 => [new TouchInput(TouchInput.Tap, Read(6), Read(8))],
                2 => [new TouchInput(TouchInput.Hold, Read(6), Read(8))],
                3 => [new TouchInput(TouchInput.Swipe, Read(6), Read(8), Read(10), Read(12))],
                _ => [],
            };
        }

        private List<DeviceInput> Dials(byte[] report, int length)
        {
            var events = new List<DeviceInput>();
            if (length < 5 + _dials.Length)
            {
                return events;
            }
            for (var dial = 0; dial < _dials.Length; dial++)
            {
                var value = report[5 + dial];
                if (report[4] == 0x00 && (value != 0) != _dials[dial])
                {
                    _dials[dial] = value != 0;
                    events.Add(new DialPressInput(dial, value != 0));
                }
                else if (report[4] == 0x01 && value != 0)
                {
                    events.Add(new DialInput(dial, (sbyte)value));
                }
            }
            return events;
        }
    }

    private static byte[] Gen1Packet(int size, int hidKey, int part, bool last, ReadOnlySpan<byte> data)
    {
        var report = new byte[size];
        report[0] = 0x02;
        report[1] = 0x01;
        report[2] = (byte)part;
        report[4] = last ? (byte)1 : (byte)0;
        report[5] = (byte)(hidKey + 1);
        data.CopyTo(report.AsSpan(16));
        return report;
    }

    /// <summary>1024-byte packets: report id 0x02, a header written by <paramref name="header"/>, then data.</summary>
    private static IEnumerable<byte[]> Gen2Packets(byte[] data, int headerSize, HeaderWriter header)
    {
        var offset = 0;
        var part = 0;
        do
        {
            var length = Math.Min(data.Length - offset, PacketSize - headerSize);
            var report = new byte[PacketSize];
            report[0] = 0x02;
            header(report.AsSpan(0, headerSize), part, offset + length >= data.Length, length);
            data.AsSpan(offset, length).CopyTo(report.AsSpan(headerSize));
            offset += length;
            part++;
            yield return report;
        }
        while (offset < data.Length);
    }

    private delegate void HeaderWriter(Span<byte> header, int part, bool last, int length);

    private static byte[] Feature(int size, params byte[] data)
    {
        var report = new byte[size];
        data.CopyTo(report, 0);
        return report;
    }

    private static string TryRead(Func<string> read)
    {
        try
        {
            return read();
        }
        catch (Exception err) when (err is IOException or TimeoutException or InvalidOperationException)
        {
            return "";
        }
    }

    /// <summary>ASCII from <paramref name="start"/> up to the first character that is not printable.</summary>
    public static string PrintableFrom(byte[] report, int start)
    {
        var end = start;
        while (end < report.Length && report[end] is >= 0x20 and <= 0x7E)
        {
            end++;
        }
        return start < report.Length ? Encoding.ASCII.GetString(report, start, end - start).Trim() : "";
    }

    /// <summary>ASCII from <paramref name="start"/>; byte 1 holds the length counted from byte 2.</summary>
    public static string ReportString(byte[] report, int start)
    {
        if (report.Length <= start)
        {
            return "";
        }
        var end = report[1] + 2;
        if (end <= start || end > report.Length)
        {
            end = report.Length;
        }
        var text = Encoding.ASCII.GetString(report, start, end - start);
        var zero = text.IndexOf('\0', StringComparison.Ordinal);
        return new string((zero >= 0 ? text[..zero] : text).Where(c => c is >= ' ' and <= '~').ToArray()).Trim();
    }
}
