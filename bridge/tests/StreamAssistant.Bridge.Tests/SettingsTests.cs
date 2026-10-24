using Microsoft.Extensions.Logging.Abstractions;
using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Tests;

public sealed class SettingsTests
{
    [Fact]
    public void Second_bridge_with_the_same_settings_is_refused()
    {
        var dir = Path.Combine(Path.GetTempPath(), "sab-test-" + Guid.NewGuid().ToString("N"));
        var options = new BridgeOptions(0, dir, null, [], Mdns: false);
        using (var first = new SettingsStore(options, NullLogger<SettingsStore>.Instance))
        {
            Assert.Throws<AlreadyRunningException>(() => new SettingsStore(options, NullLogger<SettingsStore>.Instance));
            Assert.Equal(16, first.Settings.Id.Length);
        }

        // Released with the first one; the id survives
        using var again = new SettingsStore(options, NullLogger<SettingsStore>.Instance);
        Assert.Equal(16, again.Settings.Id.Length);
        again.Dispose();
        Directory.Delete(dir, recursive: true);
    }
}
