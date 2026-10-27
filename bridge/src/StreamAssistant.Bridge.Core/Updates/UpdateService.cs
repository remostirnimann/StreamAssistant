using System.Formats.Tar;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;

namespace StreamAssistant.Bridge.Updates;

/// <summary>A downloaded, checked release, ready to be installed.</summary>
/// <param name="Version">The release, e.g. 0.9.0b1.</param>
/// <param name="File">The downloaded file (installer or archive).</param>
/// <param name="Staging">For archives: the unpacked files; null for installers.</param>
public sealed record UpdatePackage(string Version, string File, string? Staging);

/// <summary>The platform part of an update: which file to fetch, and how to put it in place.</summary>
public interface IUpdateInstaller
{
    /// <summary>False when this bridge cannot update itself (started from source, unknown platform).</summary>
    bool Supported { get; }

    /// <summary>Name of the release file for <paramref name="version"/>.</summary>
    string AssetName(string version);

    /// <summary>Puts the package in place and restarts the bridge (does not return in a real installer).</summary>
    Task InstallAsync(UpdatePackage package, CancellationToken cancellationToken);
}

/// <summary>
/// Updates the bridge to a release on request of Home Assistant (command <c>update</c>):
/// downloads the release file and SHA256SUMS.txt, checks the checksum, unpacks archives
/// and hands over to <see cref="IUpdateInstaller"/>. Progress is reported as
/// <c>update_status</c> messages: downloading, installing, failed.
/// </summary>
public sealed partial class UpdateService(BridgeOptions options, IUpdateInstaller installer, HttpClient http, ILogger<UpdateService> logger)
{
    private const string Checksums = "SHA256SUMS.txt";
    private int _running;

    /// <summary>Raised with each <c>update_status</c> message, from any thread.</summary>
    public event Action<JsonObject>? Status;

    public bool Supported => installer.Supported;

    public bool Running => Volatile.Read(ref _running) == 1;

    /// <summary>The task of the update in progress (for tests).</summary>
    public Task Current { get; private set; } = Task.CompletedTask;

    /// <summary>Checks the request and starts the update in the background.</summary>
    public void Start(string version)
    {
        if (!Supported)
        {
            throw new DeviceException("unsupported", "This bridge cannot update itself; install the new version by hand");
        }
        if (!VersionPattern().IsMatch(version))
        {
            throw new DeviceException("invalid_message", "version must look like 1.2.3 or 1.2.3b1");
        }
        if (Interlocked.CompareExchange(ref _running, 1, 0) != 0)
        {
            throw new DeviceException("invalid_message", "An update is already running");
        }
        Current = Task.Run(() => RunAsync(version));
    }

    private async Task RunAsync(string version)
    {
        var folder = Path.Combine(options.ConfigDir, "update");
        try
        {
            Report("downloading", version);
            logger.LogInformation("Updating to {Version}", version);
            if (Directory.Exists(folder))
            {
                Directory.Delete(folder, recursive: true);
            }
            Directory.CreateDirectory(folder);
            var asset = installer.AssetName(version);
            var baseUrl = $"{options.UpdateUrl}/v{version}";
            var sums = await http.GetStringAsync($"{baseUrl}/{Checksums}");
            var expected = ExpectedHash(sums, asset)
                ?? throw new InvalidDataException($"{asset} is not part of release {version}");
            var file = Path.Combine(folder, asset);
            await using (var source = await http.GetStreamAsync($"{baseUrl}/{asset}"))
            await using (var target = File.Create(file))
            {
                await source.CopyToAsync(target);
            }
            await using (var check = File.OpenRead(file))
            {
                var actual = Convert.ToHexStringLower(await SHA256.HashDataAsync(check));
                if (actual != expected)
                {
                    throw new InvalidDataException($"Checksum of {asset} does not match");
                }
            }

            string? staging = null;
            if (!asset.EndsWith(".msi", StringComparison.OrdinalIgnoreCase))
            {
                staging = Path.Combine(folder, "files");
                await ExtractAsync(file, staging);
            }
            Report("installing", version);
            logger.LogInformation("Installing {Version}, the bridge restarts", version);
            await installer.InstallAsync(new UpdatePackage(version, file, staging), CancellationToken.None);
        }
        catch (Exception err) when (err is HttpRequestException or IOException or InvalidDataException or UnauthorizedAccessException
            or TaskCanceledException or InvalidOperationException or System.ComponentModel.Win32Exception)
        {
            logger.LogWarning("Update to {Version} failed: {Message}", version, err.Message);
            Report("failed", version, err.Message);
            Volatile.Write(ref _running, 0);
        }
    }

    private void Report(string state, string version, string? message = null)
    {
        var status = new JsonObject { ["type"] = "update_status", ["state"] = state, ["version"] = version };
        if (message is not null)
        {
            status["message"] = message;
        }
        Status?.Invoke(status);
    }

    /// <summary>The hash of <paramref name="asset"/> from a sha256sum list ("hash  name" per line).</summary>
    public static string? ExpectedHash(string sums, string asset)
    {
        foreach (var line in sums.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var parts = line.Split(' ', 2, StringSplitOptions.TrimEntries);
            if (parts.Length == 2 && parts[1].TrimStart('*') == asset && parts[0].Length == 64)
            {
                return parts[0].ToLowerInvariant();
            }
        }
        return null;
    }

    private static async Task ExtractAsync(string archive, string target)
    {
        Directory.CreateDirectory(target);
        if (archive.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
        {
            await ZipFile.ExtractToDirectoryAsync(archive, target);
            return;
        }
        await using var file = File.OpenRead(archive);
        await using var gzip = new GZipStream(file, CompressionMode.Decompress);
        await TarFile.ExtractToDirectoryAsync(gzip, target, overwriteFiles: true);
    }

    [GeneratedRegex(@"^\d+\.\d+\.\d+((a|b|rc)\d+)?$")]
    private static partial Regex VersionPattern();
}
