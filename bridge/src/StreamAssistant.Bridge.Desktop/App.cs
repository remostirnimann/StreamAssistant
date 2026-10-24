using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Layout;
using Avalonia.Styling;
using Avalonia.Themes.Fluent;

namespace StreamAssistant.Bridge.Desktop;

public sealed class App : Application
{
    /// <summary>The running bridge's services; null when it could not start.</summary>
    public static IServiceProvider? Services { get; set; }

    public static string? StartupError { get; set; }

    public override void Initialize()
    {
        Styles.Add(new FluentTheme());
        RequestedThemeVariant = ThemeVariant.Default;
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = Services is not null ? new MainWindow(Services) : ErrorWindow(StartupError ?? "?");
        }
        base.OnFrameworkInitializationCompleted();
    }

    private static Window ErrorWindow(string message) => new()
    {
        Title = "Stream Assistant Bridge",
        Width = 420,
        Height = 160,
        WindowStartupLocation = WindowStartupLocation.CenterScreen,
        Content = new TextBlock
        {
            Text = message,
            TextWrapping = Avalonia.Media.TextWrapping.Wrap,
            Margin = new Thickness(24),
            VerticalAlignment = VerticalAlignment.Center,
        },
    };
}
