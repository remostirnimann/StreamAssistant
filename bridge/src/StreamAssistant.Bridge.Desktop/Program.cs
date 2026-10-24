using Avalonia;
using StreamAssistant.Bridge.Hosting;

namespace StreamAssistant.Bridge.Desktop;

/// <summary>
/// The bridge with a window: shows status and pairing code, and hosts
/// virtual decks the user creates (shown and pressed in the window).
/// Takes the same options as the console bridge.
/// </summary>
internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        var bridge = BridgeHost.Build(args);
        if (!BridgeHost.Prepare(bridge, virtualDecks: true))
        {
            App.StartupError = Texts.Current.AlreadyRunning;
            return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        bridge.StartAsync().GetAwaiter().GetResult();
        try
        {
            App.Services = bridge.Services;
            return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
        }
        finally
        {
            bridge.StopAsync().GetAwaiter().GetResult();
            bridge.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
    }

    /// <summary>Also used by the visual designer and the UI tests.</summary>
    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UsePlatformDetect().LogToTrace();
}
