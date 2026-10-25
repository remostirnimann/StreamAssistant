using System.Buffers.Binary;
using System.Text;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// A Stream Deck model with the Gen2 USB protocol (JPEG keys, mounted upside
/// down). Same data as custom_components/stream_assistant/protocol/models.py.
/// </summary>
public sealed record ElgatoModel(string Name, IReadOnlyList<int> ProductIds, int Cols, int Rows, int KeySize)
{
    public const int VendorId = 0x0FD9;

    private const int PacketSize = 1024;
    private const int PacketHeader = 8;
    private const int FeatureSize = 32;

    /// <summary>Offset of the first key state in an input report (after the report id).</summary>
    private const int KeyDataOffset = 4;

    public static readonly IReadOnlyList<ElgatoModel> All =
    [
        new("Stream Deck MK.2", [0x0080, 0x00A5, 0x00B9], 5, 3, 72),
        new("Stream Deck Original v2", [0x006D], 5, 3, 72),
        new("Stream Deck XL", [0x006C, 0x008F], 8, 4, 96),
    ];

    public int KeyCount => Cols * Rows;

    public static ElgatoModel? Find(int vendorId, int productId) =>
        vendorId == VendorId ? All.FirstOrDefault(m => m.ProductIds.Contains(productId)) : null;

    /// <summary>The output reports that show <paramref name="jpeg"/> on a key.</summary>
    public static IEnumerable<byte[]> ImageReports(int key, byte[] jpeg)
    {
        var offset = 0;
        var part = 0;
        do
        {
            var length = Math.Min(jpeg.Length - offset, PacketSize - PacketHeader);
            var report = new byte[PacketSize];
            report[0] = 0x02;
            report[1] = 0x07;
            report[2] = (byte)key;
            report[3] = offset + length >= jpeg.Length ? (byte)1 : (byte)0;
            BinaryPrimitives.WriteUInt16LittleEndian(report.AsSpan(4), (ushort)length);
            BinaryPrimitives.WriteUInt16LittleEndian(report.AsSpan(6), (ushort)part);
            jpeg.AsSpan(offset, length).CopyTo(report.AsSpan(PacketHeader));
            offset += length;
            part++;
            yield return report;
        }
        while (offset < jpeg.Length);
    }

    public static byte[] BrightnessReport(int percent) => Feature(0x03, 0x08, (byte)Math.Clamp(percent, 0, 100));

    /// <summary>Shows the Elgato logo.</summary>
    public static byte[] ResetReport() => Feature(0x03, 0x02);

    public const byte FirmwareReport = 0x05;
    public const byte SerialReport = 0x06;

    /// <summary>Firmware version from feature report 0x05.</summary>
    public static string ParseFirmware(byte[] report) => ReportString(report, 6);

    /// <summary>Serial number from feature report 0x06.</summary>
    public static string ParseSerial(byte[] report) => ReportString(report, 2);

    /// <summary>Key states of an input report, or null for other reports.</summary>
    public bool[]? ParseKeys(byte[] report, int length)
    {
        if (length < KeyDataOffset + KeyCount || report[0] != 0x01)
        {
            return null;
        }
        return Enumerable.Range(0, KeyCount).Select(i => report[KeyDataOffset + i] != 0).ToArray();
    }

    private static byte[] Feature(params byte[] data)
    {
        var report = new byte[FeatureSize];
        data.CopyTo(report, 0);
        return report;
    }

    /// <summary>ASCII from <paramref name="start"/>; byte 1 holds the length counted from byte 2.</summary>
    private static string ReportString(byte[] report, int start)
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
