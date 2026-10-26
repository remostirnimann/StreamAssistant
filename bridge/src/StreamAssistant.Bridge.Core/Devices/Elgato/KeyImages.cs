using System.Buffers.Binary;
using System.Globalization;
using StbImageSharp;
using StbImageWriteSharp;
using ReadComponents = StbImageSharp.ColorComponents;
using WriteComponents = StbImageWriteSharp.ColorComponents;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// Image work for Stream Decks: the client sends upright JPEG or PNG; decks want
/// them scaled, flipped or turned, as JPEG or BMP. Pixels are RGB, row by row.
/// </summary>
public static class KeyImages
{
    private const int Quality = 90;
    private const int BmpHeader = 54;

    /// <summary>
    /// Decode a JPEG or PNG for a key: scaled to fit and centred on black when its shape
    /// differs (Home Assistant draws square keys; the Studio's are 144×112).
    /// </summary>
    public static byte[] Fit(ReadOnlyMemory<byte> image, int width, int height)
    {
        var decoded = DecodeImage(image);
        var scale = Math.Min((double)width / decoded.Width, (double)height / decoded.Height);
        var innerWidth = Math.Max(1, (int)Math.Round(decoded.Width * scale));
        var innerHeight = Math.Max(1, (int)Math.Round(decoded.Height * scale));
        var inner = Scale(decoded.Data, decoded.Width, decoded.Height, innerWidth, innerHeight);
        if (innerWidth == width && innerHeight == height)
        {
            return inner;
        }
        var result = new byte[width * height * 3];
        var left = (width - innerWidth) / 2;
        var top = (height - innerHeight) / 2;
        for (var y = 0; y < innerHeight; y++)
        {
            Array.Copy(inner, y * innerWidth * 3, result, (((top + y) * width) + left) * 3, innerWidth * 3);
        }
        return result;
    }

    /// <summary>Decode a JPEG or PNG and scale it to <paramref name="width"/> × <paramref name="height"/>.</summary>
    public static byte[] Decode(ReadOnlyMemory<byte> image, int width, int height)
    {
        var decoded = DecodeImage(image);
        return Scale(decoded.Data, decoded.Width, decoded.Height, width, height);
    }

    private static ImageResult DecodeImage(ReadOnlyMemory<byte> image)
    {
        ImageResult decoded;
        try
        {
            decoded = ImageResult.FromMemory(image.ToArray(), ReadComponents.RedGreenBlue);
        }
        catch (Exception err) when (err is InvalidOperationException or ArgumentException or IndexOutOfRangeException or NotSupportedException)
        {
            throw new DeviceException("invalid_message", $"Unreadable image: {err.Message}");
        }
        return decoded;
    }

    /// <summary>An area in one colour, <paramref name="color"/> as #rrggbb.</summary>
    public static byte[] Solid(string color, int width, int height)
    {
        var (red, green, blue) = Rgb(color);
        var pixels = new byte[width * height * 3];
        for (var i = 0; i < pixels.Length; i += 3)
        {
            pixels[i] = red;
            pixels[i + 1] = green;
            pixels[i + 2] = blue;
        }
        return pixels;
    }

    public static (byte Red, byte Green, byte Blue) Rgb(string color)
    {
        var rgb = int.Parse(color.AsSpan(1), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
        return ((byte)(rgb >> 16), (byte)(rgb >> 8), (byte)rgb);
    }

    /// <summary>
    /// Mirror and/or turn an image, as the reference implementation does: target (x, y)
    /// takes the source pixel after the flips, with x and y swapped when turning (square
    /// images only). Both flips together turn the image by 180°.
    /// </summary>
    public static byte[] Transform(byte[] pixels, int width, int height, bool rotate, bool xFlip, bool yFlip)
    {
        var result = new byte[pixels.Length];
        for (var y = 0; y < height; y++)
        {
            for (var x = 0; x < width; x++)
            {
                var sx = xFlip ? width - x - 1 : x;
                var sy = yFlip ? height - y - 1 : y;
                if (rotate)
                {
                    (sx, sy) = (sy, sx);
                }
                Array.Copy(pixels, ((sy * width) + sx) * 3, result, ((y * width) + x) * 3, 3);
            }
        }
        return result;
    }

    public static byte[] Jpeg(byte[] pixels, int width, int height)
    {
        using var output = new MemoryStream();
        new ImageWriter().WriteJpg(pixels, width, height, WriteComponents.RedGreenBlue, output, Quality);
        return output.ToArray();
    }

    /// <summary>24-bit BMP with the rows in the given order (as the first-generation decks expect), BGR.</summary>
    public static byte[] Bmp(byte[] pixels, int size, int pixelsPerMeter)
    {
        var data = new byte[BmpHeader + pixels.Length];
        var span = data.AsSpan();
        span[0] = (byte)'B';
        span[1] = (byte)'M';
        BinaryPrimitives.WriteUInt32LittleEndian(span[2..], (uint)data.Length);
        BinaryPrimitives.WriteUInt32LittleEndian(span[10..], BmpHeader);
        BinaryPrimitives.WriteUInt32LittleEndian(span[14..], 40);
        BinaryPrimitives.WriteInt32LittleEndian(span[18..], size);
        BinaryPrimitives.WriteInt32LittleEndian(span[22..], size);
        BinaryPrimitives.WriteInt16LittleEndian(span[26..], 1);
        BinaryPrimitives.WriteInt16LittleEndian(span[28..], 24);
        BinaryPrimitives.WriteInt32LittleEndian(span[34..], pixels.Length);
        BinaryPrimitives.WriteInt32LittleEndian(span[38..], pixelsPerMeter);
        BinaryPrimitives.WriteInt32LittleEndian(span[42..], pixelsPerMeter);
        for (var i = 0; i < pixels.Length; i += 3)
        {
            data[BmpHeader + i] = pixels[i + 2];
            data[BmpHeader + i + 1] = pixels[i + 1];
            data[BmpHeader + i + 2] = pixels[i];
        }
        return data;
    }

    /// <summary>Nearest neighbour; the client normally sends the right size already.</summary>
    private static byte[] Scale(byte[] pixels, int width, int height, int toWidth, int toHeight)
    {
        if (width == toWidth && height == toHeight)
        {
            return pixels;
        }
        var scaled = new byte[toWidth * toHeight * 3];
        for (var y = 0; y < toHeight; y++)
        {
            var sy = y * height / toHeight;
            for (var x = 0; x < toWidth; x++)
            {
                var sx = x * width / toWidth;
                Array.Copy(pixels, ((sy * width) + sx) * 3, scaled, ((y * toWidth) + x) * 3, 3);
            }
        }
        return scaled;
    }
}
