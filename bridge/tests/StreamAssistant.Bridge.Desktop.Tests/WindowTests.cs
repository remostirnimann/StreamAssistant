using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Avalonia.VisualTree;
using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;
using StreamAssistant.Bridge.Desktop;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Devices.Virtual;
using StreamAssistant.Bridge.Hosting;
using StreamAssistant.Bridge.Protocol;

[assembly: AvaloniaTestApplication(typeof(StreamAssistant.Bridge.Desktop.Tests.TestApp))]

namespace StreamAssistant.Bridge.Desktop.Tests;

public static class TestApp
{
    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>().UseSkia().UseHeadless(new AvaloniaHeadlessPlatformOptions { UseHeadlessDrawing = false });
}

/// <summary>A bridge (not listening) with its own settings folder, plus the main window.</summary>
public sealed class DesktopFixture : IDisposable
{
    public DesktopFixture()
    {
        ConfigDir = Path.Combine(Path.GetTempPath(), "sab-desktop-" + Guid.NewGuid().ToString("N"));
        Texts.Current = Texts.German;
        Bridge = BridgeHost.Build(["--config-dir", ConfigDir, "--mdns", "false", "--name", "Testrechner"]);
        Assert.True(BridgeHost.Prepare(Bridge, virtualDecks: true));
        Window = new MainWindow(Bridge.Services) { Width = 760, Height = 900 };
        Window.Show();
    }

    public string ConfigDir { get; }

    public WebApplication Bridge { get; }

    public MainWindow Window { get; }

    public VirtualDecks Decks => Bridge.Services.GetRequiredService<VirtualDecks>();

    public T Find<T>(string name) where T : Control =>
        Window.GetVisualDescendants().OfType<T>().First(c => c.Name == name);

    public static void Flush() => Dispatcher.UIThread.RunJobs();

    /// <summary>Saves what the window shows, for looking at it.</summary>
    public void Screenshot(string name)
    {
        Flush();
        var frame = Window.CaptureRenderedFrame();
        var dir = Path.Combine(AppContext.BaseDirectory, "screenshots");
        Directory.CreateDirectory(dir);
        frame?.Save(Path.Combine(dir, name + ".png"), new PngBitmapEncoderOptions());
    }

    public void Dispose()
    {
        Window.Close();
        ((IDisposable)Bridge).Dispose();
        try
        {
            Directory.Delete(ConfigDir, recursive: true);
        }
        catch (IOException)
        {
        }
    }
}

public sealed class WindowTests
{
    /// <summary>A key image as Home Assistant would send it (here PNG, the window decodes either).</summary>
    private static byte[] KeyImage(string text, string color)
    {
        var size = new PixelSize(144, 144);
        using var target = new RenderTargetBitmap(size);
        using (var context = target.CreateDrawingContext())
        {
            context.FillRectangle(new SolidColorBrush(Color.Parse(color)), new Rect(0, 0, 144, 144));
            var formatted = new FormattedText(text, System.Globalization.CultureInfo.InvariantCulture, FlowDirection.LeftToRight,
                Typeface.Default, 24, Brushes.White);
            context.DrawText(formatted, new Point((144 - formatted.Width) / 2, (144 - formatted.Height) / 2));
        }
        using var stream = new MemoryStream();
        target.Save(stream, new PngBitmapEncoderOptions());
        return stream.ToArray();
    }

    [AvaloniaFact]
    public void Empty_window_shows_status_code_and_hint()
    {
        using var app = new DesktopFixture();
        DesktopFixture.Flush();

        Assert.Contains("noch nicht gekoppelt", app.Window.StatusText);
        var pairing = app.Bridge.Services.GetRequiredService<PairingService>();
        Assert.Equal($"{pairing.Code[..3]} {pairing.Code[3..]}", app.Window.CodeText);
        Assert.NotNull(app.Find<TextBlock>("noDecks"));
        app.Screenshot("01-empty");
    }

    [AvaloniaFact]
    public void Adding_a_deck_through_the_form_offers_it_to_home_assistant_and_stores_it()
    {
        using var app = new DesktopFixture();
        var added = new List<string>();
        app.Bridge.Services.GetRequiredService<DeviceManager>().Added += d => added.Add(d.Info.Id);

        app.Find<Button>("openAddForm").RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        DesktopFixture.Flush();
        app.Find<TextBox>("deckName").Text = "Büro Monitor";
        app.Find<NumericUpDown>("deckCols").Value = 4;
        app.Find<NumericUpDown>("deckRows").Value = 2;
        app.Screenshot("02-add-form");
        app.Find<Button>("addDeck").RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        DesktopFixture.Flush();

        var deck = Assert.Single(app.Decks.Decks);
        Assert.Equal("Büro Monitor", deck.Info.Name);
        Assert.Equal((4, 2), (deck.Info.Capabilities.Keys!.Cols, deck.Info.Capabilities.Keys.Rows));
        Assert.Equal(144, deck.Info.Capabilities.Keys.ImageWidth);
        Assert.Equal([deck.Info.Id], added);
        Assert.Single(app.Window.DeckViews);
        Assert.Contains("Büro Monitor", File.ReadAllText(Path.Combine(app.ConfigDir, "bridge.json")));
    }

    [AvaloniaFact]
    public async Task Key_images_brightness_and_presses()
    {
        using var app = new DesktopFixture();
        var deck = app.Decks.Add("Küche", 5, 3);
        DesktopFixture.Flush();
        var view = Assert.Single(app.Window.DeckViews);

        string[] labels = ["Licht", "Rollo", "Szene", "Musik", "Heizung"];
        string[] colors = ["#f2b134", "#2b2b2b", "#2f6fb0", "#1e4d3a", "#8a3b2b"];
        for (var key = 0; key < 15; key++)
        {
            await deck.SetKeyImageAsync(key, "jpeg", KeyImage(labels[key % 5], colors[key % 5]), CancellationToken.None);
        }
        await deck.SetKeyColorAsync(14, "#000000", CancellationToken.None);
        DesktopFixture.Flush();
        Assert.NotNull(view.KeyImage(0));
        Assert.Null(view.KeyImage(14));
        app.Screenshot("03-deck");

        await deck.SetBrightnessAsync(30, CancellationToken.None);
        DesktopFixture.Flush();
        Assert.Equal(0.3, view.KeyOpacity, 3);
        await deck.SetBrightnessAsync(100, CancellationToken.None);
        DesktopFixture.Flush();

        var presses = new List<(int Key, bool Pressed)>();
        deck.Input += (_, input) =>
        {
            if (input is KeyInput key)
            {
                presses.Add((key.Key, key.Pressed));
            }
        };
        var key7 = app.Find<Border>("key7");
        var center = key7.TranslatePoint(new Point(key7.Bounds.Width / 2, key7.Bounds.Height / 2), app.Window)!.Value;
        app.Window.MouseDown(center, MouseButton.Left);
        DesktopFixture.Flush();
        app.Window.MouseUp(center, MouseButton.Left);
        DesktopFixture.Flush();
        Assert.Equal([(7, true), (7, false)], presses);
    }

    [AvaloniaFact]
    public void Removing_needs_a_second_click()
    {
        using var app = new DesktopFixture();
        app.Decks.Add("Weg damit", 3, 2);
        DesktopFixture.Flush();
        var view = Assert.Single(app.Window.DeckViews);
        var remove = view.GetVisualDescendants().OfType<Button>().First();

        remove.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        DesktopFixture.Flush();
        Assert.Single(app.Decks.Decks);
        remove.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        DesktopFixture.Flush();
        Assert.Empty(app.Decks.Decks);
        Assert.Empty(app.Window.DeckViews);
    }

    [AvaloniaFact]
    public void Decks_survive_a_restart()
    {
        string dir;
        string id;
        using (var first = new DesktopFixture())
        {
            id = first.Decks.Add("Bleibt", 2, 2).Info.Id;
            dir = first.ConfigDir;
            // Keep the folder: dispose the bridge without the fixture's cleanup
            ((IDisposable)first.Bridge).Dispose();
            var again = BridgeHost.Build(["--config-dir", dir, "--mdns", "false"]);
            Assert.True(BridgeHost.Prepare(again, virtualDecks: true));
            var decks = again.Services.GetRequiredService<VirtualDecks>().Decks;
            Assert.Equal(id, Assert.Single(decks).Info.Id);
            Assert.NotNull(again.Services.GetRequiredService<DeviceManager>().Get(id));
            ((IDisposable)again).Dispose();
        }
    }
}
