using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Runtime.InteropServices;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Updates;

/// <summary>
/// Updates this process's own files. Hardware-near and not testable in CI (it replaces the
/// running program and restarts it), so it stays thin; the logic is in <see cref="UpdateService"/>.
/// </summary>
/// <remarks>
/// <list type="bullet">
/// <item>Windows installer (service, <c>--install-kind msi</c>): starts the new installer, which stops
/// the service, replaces the files and starts it again.</item>
/// <item>Archive: replaces the files next to the program (a running program on Windows can be renamed,
/// not overwritten: the old one becomes *.old and is deleted at the next start), then restarts: with
/// <c>--service true</c> by exiting (systemd and launchd start it again), otherwise by starting the new
/// program, which waits for the settings lock of this one.</item>
/// </list>
/// </remarks>
[ExcludeFromCodeCoverage]
public sealed class SelfInstaller(BridgeOptions options, IHostApplicationLifetime lifetime, ILogger<SelfInstaller> logger) : IUpdateInstaller
{
    private static readonly string? ProgramPath = Environment.ProcessPath;

    private static string Flavor => Path.GetFileNameWithoutExtension(ProgramPath ?? "stream-assistant-bridge");

    private static bool IsWindows => OperatingSystem.IsWindows();

    /// <summary>Only the published single-file program updates itself, not a development build.</summary>
    public bool Supported =>
        ProgramPath is not null
        && string.IsNullOrEmpty(Assembly.GetEntryAssembly()?.Location)
        && Flavor.StartsWith("stream-assistant-bridge", StringComparison.Ordinal)
        && (options.Install != InstallKind.Msi || IsWindows);

    public string AssetName(string version) => options.Install == InstallKind.Msi
        ? $"stream-assistant-bridge-{version}-win-x64.msi"
        : $"{Flavor}-{version}-{RuntimeInformation.RuntimeIdentifier}.{(IsWindows ? "zip" : "tar.gz")}";

    /// <summary>Removes what the last update left behind (call at start).</summary>
    public static void CleanUp()
    {
        if (ProgramPath is null || Path.GetDirectoryName(ProgramPath) is not { } folder)
        {
            return;
        }
        foreach (var old in Directory.EnumerateFiles(folder, "*.old"))
        {
            try
            {
                File.Delete(old);
            }
            catch (Exception err) when (err is IOException or UnauthorizedAccessException)
            {
                // Still in use; next time
            }
        }
    }

    public Task InstallAsync(UpdatePackage package, CancellationToken cancellationToken)
    {
        if (options.Install == InstallKind.Msi)
        {
            var log = Path.Combine(options.ConfigDir, "update", "install.log");
            logger.LogInformation("Starting the installer for {Version}", package.Version);
            // A separate process: it outlives this service, which it stops and starts again
            Process.Start(new ProcessStartInfo("msiexec", $"/i \"{package.File}\" /qn /norestart /l*v \"{log}\"") { UseShellExecute = false });
            return Task.CompletedTask;
        }

        // A single-file program loads its assemblies from its own file when first used; once that
        // file is replaced, they cannot be found any more (e.g. System.IO.Pipes for Process.Start)
        LoadAllAssemblies();

        var folder = Path.GetDirectoryName(ProgramPath)!;
        var replaced = new List<(string Target, bool HadOld)>();
        try
        {
            foreach (var file in Directory.EnumerateFiles(package.Staging!, "*", SearchOption.AllDirectories))
            {
                var target = Path.Combine(folder, Path.GetRelativePath(package.Staging!, file));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                var hadOld = File.Exists(target);
                if (hadOld)
                {
                    File.Move(target, target + ".old", overwrite: true);
                }
                replaced.Add((target, hadOld));
                File.Move(file, target);
                if (!OperatingSystem.IsWindows())
                {
                    File.SetUnixFileMode(target, File.GetUnixFileMode(target) | UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute);
                }
            }

            if (!options.Service)
            {
                // Same arguments, and wait until this process has let go of the settings
                var start = new ProcessStartInfo(ProgramPath!) { UseShellExecute = false };
                foreach (var arg in RestartArguments(Environment.GetCommandLineArgs().Skip(1)))
                {
                    start.ArgumentList.Add(arg);
                }
                Process.Start(start);
            }
        }
        catch
        {
            // Put the old files back: this process keeps running, and a later try starts from them
            replaced.Reverse();
            foreach (var (target, hadOld) in replaced)
            {
                try
                {
                    if (hadOld)
                    {
                        File.Move(target + ".old", target, overwrite: true);
                    }
                    else
                    {
                        File.Delete(target);
                    }
                }
                catch (Exception err) when (err is IOException or UnauthorizedAccessException)
                {
                    logger.LogWarning("Could not restore {File}: {Message}", target, err.Message);
                }
            }
            throw;
        }
        logger.LogInformation("Version {Version} is in place, restarting", package.Version);
        // The desktop app keeps its window open after the bridge stops: end the whole process
        lifetime.ApplicationStopped.Register(() => Environment.Exit(0));
        lifetime.StopApplication();
        return Task.CompletedTask;
    }

    /// <summary>
    /// Loads every assembly the loaded ones reference, and so on, so the process no longer needs
    /// its own file. (A single-file program lists no trusted platform assemblies to go by.)
    /// </summary>
    private void LoadAllAssemblies()
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Queue<Assembly>(AppDomain.CurrentDomain.GetAssemblies());
        while (pending.TryDequeue(out var assembly))
        {
            if (!seen.Add(assembly.GetName().Name ?? ""))
            {
                continue;
            }
            foreach (var reference in assembly.GetReferencedAssemblies())
            {
                if (seen.Contains(reference.Name ?? ""))
                {
                    continue;
                }
                try
                {
                    pending.Enqueue(Assembly.Load(reference));
                }
                catch (Exception err) when (err is FileNotFoundException or FileLoadException or BadImageFormatException)
                {
                    // Not part of this program (an optional dependency); the restart does not need it
                    seen.Add(reference.Name ?? "");
                }
            }
        }
        logger.LogInformation("Loaded {Count} assemblies before replacing the program", seen.Count);
    }

    /// <summary>The arguments for the new process: the old ones, waiting for the settings lock.</summary>
    public static IEnumerable<string> RestartArguments(IEnumerable<string> args)
    {
        using var items = args.GetEnumerator();
        while (items.MoveNext())
        {
            if (items.Current == "--wait-for-lock")
            {
                items.MoveNext();
                continue;
            }
            if (!items.Current.StartsWith("--wait-for-lock=", StringComparison.Ordinal))
            {
                yield return items.Current;
            }
        }
        yield return "--wait-for-lock";
        yield return "60";
    }
}
