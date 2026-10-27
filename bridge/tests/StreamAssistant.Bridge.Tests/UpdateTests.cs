using System.Formats.Tar;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Hosting;
using StreamAssistant.Bridge.Updates;

namespace StreamAssistant.Bridge.Tests;

/// <summary>Records what would be installed instead of replacing the test runner.</summary>
internal sealed class FakeInstaller(bool supported = true, string asset = "stream-assistant-bridge-{0}-linux-x64.tar.gz") : IUpdateInstaller
{
    public bool Supported => supported;

    public UpdatePackage? Installed { get; private set; }

    public List<string> StagedFiles { get; } = [];

    public string AssetName(string version) => string.Format(System.Globalization.CultureInfo.InvariantCulture, asset, version);

    public Task InstallAsync(UpdatePackage package, CancellationToken cancellationToken)
    {
        Installed = package;
        if (package.Staging is { } staging)
        {
            StagedFiles.AddRange(Directory.EnumerateFiles(staging, "*", SearchOption.AllDirectories).Select(f => Path.GetRelativePath(staging, f)));
        }
        return Task.CompletedTask;
    }
}

/// <summary>A pretend GitHub releases page: files by URL.</summary>
internal sealed class FakeReleases : HttpMessageHandler
{
    public Dictionary<string, byte[]> Files { get; } = [];

    public List<string> Requested { get; } = [];

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var url = request.RequestUri!.ToString();
        Requested.Add(url);
        return Task.FromResult(Files.TryGetValue(url, out var data)
            ? new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(data) }
            : new HttpResponseMessage(HttpStatusCode.NotFound));
    }

    /// <summary>Publishes a release file and its checksum line.</summary>
    public void Publish(string version, string name, byte[] data, string? hash = null)
    {
        var baseUrl = $"{BridgeOptions.DefaultUpdateUrl}/v{version}";
        Files[$"{baseUrl}/{name}"] = data;
        var sums = Files.TryGetValue($"{baseUrl}/SHA256SUMS.txt", out var old) ? Encoding.ASCII.GetString(old) : "";
        sums += $"{hash ?? Convert.ToHexStringLower(SHA256.HashData(data))}  {name}\n";
        Files[$"{baseUrl}/SHA256SUMS.txt"] = Encoding.ASCII.GetBytes(sums);
    }

    public static byte[] TarGz(string name, string content)
    {
        using var output = new MemoryStream();
        using (var gzip = new GZipStream(output, CompressionLevel.Fastest, leaveOpen: true))
        using (var tar = new TarWriter(gzip))
        {
            var entry = new PaxTarEntry(TarEntryType.RegularFile, name) { DataStream = new MemoryStream(Encoding.UTF8.GetBytes(content)) };
            tar.WriteEntry(entry);
        }
        return output.ToArray();
    }

    public static byte[] Zip(string name, string content)
    {
        using var output = new MemoryStream();
        using (var zip = new ZipArchive(output, ZipArchiveMode.Create, leaveOpen: true))
        using (var writer = new StreamWriter(zip.CreateEntry(name).Open()))
        {
            writer.Write(content);
        }
        return output.ToArray();
    }
}

public sealed class UpdateTests
{
    private static string TempDir()
    {
        var dir = Path.Combine(Path.GetTempPath(), "sab-update-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        return dir;
    }

    private static (UpdateService Service, FakeReleases Releases, FakeInstaller Installer, List<JsonObject> Status) Create(
        FakeInstaller? installer = null)
    {
        var options = new BridgeOptions(0, TempDir(), null, [], Mdns: false);
        var releases = new FakeReleases();
        installer ??= new FakeInstaller();
        var service = new UpdateService(options, installer, new HttpClient(releases), NullLogger<UpdateService>.Instance);
        var status = new List<JsonObject>();
        service.Status += status.Add;
        return (service, releases, installer, status);
    }

    private static string[] States(List<JsonObject> status) => status.Select(s => (string)s["state"]!).ToArray();

    [Fact]
    public async Task Downloads_checks_and_unpacks_an_archive()
    {
        var (service, releases, installer, status) = Create();
        releases.Publish("0.9.0", "stream-assistant-bridge-0.9.0-linux-x64.tar.gz", FakeReleases.TarGz("stream-assistant-bridge", "new program"));
        service.Start("0.9.0");
        Assert.True(service.Running);
        await service.Current;
        Assert.Equal(["downloading", "installing"], States(status));
        Assert.Equal("0.9.0", installer.Installed!.Version);
        Assert.Equal(["stream-assistant-bridge"], installer.StagedFiles);
        Assert.Equal("new program", File.ReadAllText(Path.Combine(installer.Installed.Staging!, "stream-assistant-bridge")));
    }

    [Fact]
    public async Task Zip_archives_and_installers()
    {
        var (zipService, zipReleases, zipInstaller, _) = Create(new FakeInstaller(asset: "stream-assistant-bridge-desktop-{0}-win-x64.zip"));
        zipReleases.Publish("1.0.0b2", "stream-assistant-bridge-desktop-1.0.0b2-win-x64.zip", FakeReleases.Zip("stream-assistant-bridge-desktop.exe", "exe"));
        zipService.Start("1.0.0b2");
        await zipService.Current;
        Assert.Equal(["stream-assistant-bridge-desktop.exe"], zipInstaller.StagedFiles);

        // An installer is handed over as it is
        var (msiService, msiReleases, msiInstaller, _) = Create(new FakeInstaller(asset: "stream-assistant-bridge-{0}-win-x64.msi"));
        msiReleases.Publish("1.0.0", "stream-assistant-bridge-1.0.0-win-x64.msi", [1, 2, 3]);
        msiService.Start("1.0.0");
        await msiService.Current;
        Assert.Null(msiInstaller.Installed!.Staging);
        Assert.EndsWith(".msi", msiInstaller.Installed.File);
    }

    [Fact]
    public async Task Failures_are_reported_and_allow_a_new_try()
    {
        var (service, releases, installer, status) = Create();
        const string asset = "stream-assistant-bridge-0.9.0-linux-x64.tar.gz";

        // No such release
        service.Start("0.9.0");
        await service.Current;
        Assert.Equal(["downloading", "failed"], States(status));
        Assert.False(service.Running);

        // Wrong checksum
        releases.Publish("0.9.0", asset, [1, 2, 3], hash: new string('0', 64));
        status.Clear();
        service.Start("0.9.0");
        await service.Current;
        Assert.Contains("Checksum", (string?)status[^1]["message"]);

        // Release without a file for this platform
        releases.Files.Clear();
        releases.Publish("0.9.1", "stream-assistant-bridge-0.9.1-osx-arm64.tar.gz", [1]);
        status.Clear();
        service.Start("0.9.1");
        await service.Current;
        Assert.Contains("not part of release", (string?)status[^1]["message"]);
        Assert.Null(installer.Installed);
    }

    [Fact]
    public void Requests_are_checked()
    {
        var (unsupported, _, _, _) = Create(new FakeInstaller(supported: false));
        Assert.Equal("unsupported", Assert.Throws<DeviceException>(() => unsupported.Start("0.9.0")).Code);
        var (service, _, _, _) = Create();
        foreach (var version in new[] { "latest", "0.9", "0.9.0-beta", "../0.9.0" })
        {
            Assert.Equal("invalid_message", Assert.Throws<DeviceException>(() => service.Start(version)).Code);
        }
    }

    [Fact]
    public async Task One_update_at_a_time()
    {
        var gate = new TaskCompletionSource();
        var (service, releases, _, _) = Create(new FakeInstaller());
        releases.Publish("0.9.0", "stream-assistant-bridge-0.9.0-linux-x64.tar.gz", FakeReleases.TarGz("a", "b"));
        service.Start("0.9.0");
        // A second request while the first runs is refused, unless the first is already done
        try
        {
            service.Start("0.9.0");
            Assert.False(service.Running);
        }
        catch (DeviceException err)
        {
            Assert.Contains("already running", err.Message);
        }
        await service.Current;
        gate.SetResult();
    }

    [Fact]
    public void Checksum_lists()
    {
        var hash = new string('a', 64);
        Assert.Equal(hash, UpdateService.ExpectedHash($"{new string('b', 64)}  other\n{hash.ToUpperInvariant()} *file.tar.gz\n", "file.tar.gz"));
        Assert.Null(UpdateService.ExpectedHash("short  file.tar.gz", "file.tar.gz"));
        Assert.Null(UpdateService.ExpectedHash("", "file.tar.gz"));
    }

    [Fact]
    public void Restart_arguments_wait_for_the_lock()
    {
        Assert.Equal(
            ["--simulate", "5x3", "--wait-for-lock", "60"],
            SelfInstaller.RestartArguments(["--simulate", "5x3", "--wait-for-lock", "30"]));
        Assert.Equal(["--wait-for-lock", "60"], SelfInstaller.RestartArguments(["--wait-for-lock=30"]));
    }

    [Fact]
    public void Install_options()
    {
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?>
        {
            ["install-kind"] = "MSI",
            ["service"] = "true",
            ["wait-for-lock"] = "999",
            ["update-url"] = "http://localhost:8000/releases/",
        }).Build();
        var options = BridgeOptions.From(config);
        Assert.Equal(InstallKind.Msi, options.Install);
        Assert.True(options.Service);
        Assert.Equal(300, options.WaitForLock);
        Assert.Equal("http://localhost:8000/releases", options.UpdateUrl);
        var defaults = BridgeOptions.From(new ConfigurationBuilder().Build());
        Assert.Equal((InstallKind.Archive, false, 0, BridgeOptions.DefaultUpdateUrl), (defaults.Install, defaults.Service, defaults.WaitForLock, defaults.UpdateUrl));
    }

    [Fact]
    public void A_restarted_bridge_waits_for_the_old_one()
    {
        var dir = TempDir();
        var old = new SettingsStore(new BridgeOptions(0, dir, null, [], Mdns: false), NullLogger<SettingsStore>.Instance);
        // Without waiting: refused right away
        Assert.Throws<AlreadyRunningException>(() => new SettingsStore(new BridgeOptions(0, dir, null, [], Mdns: false), NullLogger<SettingsStore>.Instance));
        // Waiting: the old one lets go meanwhile
        var cancel = TestContext.Current.CancellationToken;
        _ = Task.Run(
            async () =>
            {
                await Task.Delay(300, cancel);
                old.Dispose();
            },
            cancel);
        using var restarted = new SettingsStore(new BridgeOptions(0, dir, null, [], Mdns: false, WaitForLock: 10), NullLogger<SettingsStore>.Instance);
        Assert.Equal(old.Settings.Id, restarted.Settings.Id);
    }

    [Fact]
    public void Service_log_file_rotates()
    {
        var path = Path.Combine(TempDir(), "bridge.log");
        using var provider = new FileLoggerProvider(path);
        var logger = provider.CreateLogger("StreamAssistant.Bridge");
        logger.LogInformation("Hello {Name}", "log");
        logger.LogDebug("not written");
        provider.CreateLogger("Microsoft.AspNetCore").LogInformation("framework noise");
        logger.LogError(new InvalidOperationException("boom"), "Failed");
        var text = File.ReadAllText(path);
        Assert.Contains("info: StreamAssistant.Bridge Hello log", text);
        Assert.Contains("boom", text);
        Assert.DoesNotContain("not written", text);
        Assert.DoesNotContain("framework noise", text);
        Assert.Null(logger.BeginScope("x"));

        File.WriteAllText(path, new string('x', (1024 * 1024) + 1));
        logger.LogInformation("after rotation");
        Assert.True(File.Exists(path + ".1"));
        Assert.Contains("after rotation", File.ReadAllText(path));
    }

    [Fact]
    public async Task Home_Assistant_starts_an_update_and_sees_its_progress()
    {
        var releases = new FakeReleases();
        releases.Publish("0.9.0", "stream-assistant-bridge-0.9.0-linux-x64.tar.gz", FakeReleases.TarGz("stream-assistant-bridge", "x"));
        var installer = new FakeInstaller();
        await using var bridge = new TestBridge(services =>
        {
            services.AddSingleton<IUpdateInstaller>(installer);
            services.AddSingleton(new HttpClient(releases));
        });
        var (client, _) = await bridge.PairAsync();
        await using var _ = client;
        var (again, welcome, _) = await bridge.HelloAsync(await PairToken(bridge));
        await using var __ = again;
        Assert.Contains("update", welcome["features"]!.AsArray().Select(f => (string?)f));

        await again.SendAsync(new JsonObject { ["type"] = "update", ["version"] = "0.9.0", ["id"] = 5 });
        Assert.True((bool)(await again.ReceiveAsync())["ok"]!);
        Assert.Equal("downloading", (string?)(await again.ReceiveAsync())["state"]);
        Assert.Equal("installing", (string?)(await again.ReceiveAsync())["state"]);
        Assert.Equal("0.9.0", installer.Installed!.Version);

        await again.SendAsync(new JsonObject { ["type"] = "update", ["id"] = 6 });
        Assert.Equal("invalid_message", (string?)(await again.ReceiveAsync())["error"]!["code"]);
    }

    [Fact]
    public async Task Bridges_that_cannot_update_do_not_offer_it()
    {
        await using var bridge = new TestBridge(services => services.AddSingleton<IUpdateInstaller>(new FakeInstaller(supported: false)));
        var (client, welcomeToken) = await bridge.PairAsync();
        await client.DisposeAsync();
        var (again, welcome, _) = await bridge.HelloAsync(welcomeToken);
        await using var _ = again;
        Assert.DoesNotContain("update", welcome["features"]!.AsArray().Select(f => (string?)f));
        await again.SendAsync(new JsonObject { ["type"] = "update", ["version"] = "0.9.0", ["id"] = 1 });
        Assert.Equal("unsupported", (string?)(await again.ReceiveAsync())["error"]!["code"]);
    }

    private static async Task<string> PairToken(TestBridge bridge)
    {
        var (client, token) = await bridge.PairAsync();
        await client.DisposeAsync();
        return token;
    }
}
