using System.Globalization;
using StbImageSharp;
using StbImageWriteSharp;
using ReadComponents = StbImageSharp.ColorComponents;
using WriteComponents = StbImageWriteSharp.ColorComponents;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>Turns the client's upright images into what a Gen2 deck shows: JPEG, key size, turned by 180°.</summary>
public static class KeyImages
{
    private const int Quality = 90;

    /// <summary>Decode any JPEG or PNG; scale it to the key and turn it.</summary>
    public static byte[] ForKey(ReadOnlyMemory<byte> image, int size)
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
        var pixels = Scale(decoded.Data, decoded.Width, decoded.Height, size);
        return Encode(Turn(pixels), size);
    }

    /// <summary>A key in one colour, <paramref name="color"/> as #rrggbb.</summary>
    public static byte[] Solid(string color, int size)
    {
        var rgb = int.Parse(color.AsSpan(1), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
        var pixels = new byte[size * size * 3];
        for (var i = 0; i < pixels.Length; i += 3)
        {
            pixels[i] = (byte)(rgb >> 16);
            pixels[i + 1] = (byte)(rgb >> 8);
            pixels[i + 2] = (byte)rgb;
        }
        return Encode(pixels, size);
    }

    /// <summary>Nearest neighbour; the client normally sends the right size already.</summary>
    private static byte[] Scale(byte[] pixels, int width, int height, int size)
    {
        if (width == size && height == size)
        {
            return pixels;
        }
        var scaled = new byte[size * size * 3];
        for (var y = 0; y < size; y++)
        {
            var sy = y * height / size;
            for (var x = 0; x < size; x++)
            {
                var sx = x * width / size;
                Array.Copy(pixels, ((sy * width) + sx) * 3, scaled, ((y * size) + x) * 3, 3);
            }
        }
        return scaled;
    }

    /// <summary>180°: the pixel order reversed.</summary>
    private static byte[] Turn(byte[] pixels)
    {
        var turned = new byte[pixels.Length];
        for (int from = 0, to = pixels.Length - 3; from < pixels.Length; from += 3, to -= 3)
        {
            turned[to] = pixels[from];
            turned[to + 1] = pixels[from + 1];
            turned[to + 2] = pixels[from + 2];
        }
        return turned;
    }

    private static byte[] Encode(byte[] pixels, int size)
    {
        using var output = new MemoryStream();
        new ImageWriter().WriteJpg(pixels, size, size, WriteComponents.RedGreenBlue, output, Quality);
        return output.ToArray();
    }
}
