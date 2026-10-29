using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Threading;
using Microsoft.Extensions.DependencyInjection;
using StreamAssistant.Bridge.Configuration;
using StreamAssistant.Bridge.Devices.Virtual;
using StreamAssistant.Bridge.Protocol;

namespace StreamAssistant.Bridge.Desktop;

/// <summary>Status, pairing code and the virtual decks.</summary>
public sealed class MainWindow : Window
{
    private readonly BridgeServer _server;
    private readonly PairingService _pairing;
    private readonly VirtualDecks _decks;
    private readonly BridgeOptions _options;
    private readonly Texts _texts = Texts.Current;

    private readonly TextBlock _status = new() { Opacity = 0.8 };
    private readonly TextBlock _code = new() { FontSize = 26, FontWeight = FontWeight.SemiBold, FontFamily = new FontFamily("Consolas, Menlo, monospace"), LetterSpacing = 3 };
    private readonly StackPanel _deckList = new();
    private readonly Border _addForm;
    private readonly TextBox _name;
    private readonly NumericUpDown _cols;
    private readonly NumericUpDown _rows;
    private readonly NumericUpDown _dials;

    public MainWindow(IServiceProvider services)
    {
        _server = services.GetRequiredService<BridgeServer>();
        _pairing = services.GetRequiredService<PairingService>();
        _decks = services.GetRequiredService<VirtualDecks>();
        _options = services.GetRequiredService<BridgeOptions>();

        Title = "Stream Assistant Bridge";
        Icon = App.Icon;
        Width = 760;
        Height = 640;
        MinWidth = 420;
        MinHeight = 320;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        _name = new TextBox { PlaceholderText = _texts.DeckNamePlaceholder, Width = 220, Name = "deckName" };
        _cols = new NumericUpDown { Minimum = 1, Maximum = VirtualDecks.MaxCols, Value = 5, Increment = 1, FormatString = "0", Width = 120, Name = "deckCols" };
        _rows = new NumericUpDown { Minimum = 1, Maximum = VirtualDecks.MaxRows, Value = 3, Increment = 1, FormatString = "0", Width = 120, Name = "deckRows" };
        _dials = new NumericUpDown { Minimum = 0, Maximum = VirtualDecks.MaxDials, Value = 0, Increment = 1, FormatString = "0", Width = 120, Name = "deckDials" };
        var addButton = new Button { Content = _texts.Add, Classes = { "accent" }, Name = "addDeck" };
        addButton.Click += (_, _) => AddDeck();
        var cancelButton = new Button { Content = _texts.Cancel };
        cancelButton.Click += (_, _) => _addForm!.IsVisible = false;
        _addForm = new Border
        {
            IsVisible = false,
            Padding = new Thickness(16),
            Margin = new Thickness(0, 0, 0, 16),
            CornerRadius = new CornerRadius(12),
            Classes = { "card" },
            Child = new WrapPanel
            {
                Orientation = Orientation.Horizontal,
                Children =
                {
                    Labeled(_texts.DeckName, _name),
                    Labeled(_texts.Columns, _cols),
                    Labeled(_texts.Rows, _rows),
                    Labeled(_texts.Dials, _dials),
                    new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        Spacing = 8,
                        VerticalAlignment = VerticalAlignment.Bottom,
                        Margin = new Thickness(0, 0, 0, 8),
                        Children = { addButton, cancelButton },
                    },
                },
            },
        };

        var openForm = new Button { Content = _texts.AddDeck, Name = "openAddForm" };
        openForm.Click += (_, _) =>
        {
            _addForm.IsVisible = true;
            _name.Focus();
        };

        var header = new Border
        {
            Padding = new Thickness(20, 16),
            Classes = { "header" },
            Child = new DockPanel
            {
                Children =
                {
                    Docked(new StackPanel
                    {
                        HorizontalAlignment = HorizontalAlignment.Right,
                        Children =
                        {
                            new TextBlock { Text = _texts.PairingCode, Opacity = 0.7, FontSize = 12, HorizontalAlignment = HorizontalAlignment.Right },
                            _code,
                        },
                    }, Dock.Right),
                    new StackPanel
                    {
                        Children =
                        {
                            new TextBlock { Text = _server.Name, FontSize = 20, FontWeight = FontWeight.SemiBold },
                            _status,
                        },
                    },
                },
            },
        };

        var body = new StackPanel
        {
            Margin = new Thickness(20),
            Children =
            {
                new TextBlock { Text = _texts.PairingHelp, TextWrapping = TextWrapping.Wrap, Opacity = 0.7, Margin = new Thickness(0, 0, 0, 16) },
                new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 0, 16), Children = { openForm } },
                _addForm,
                _deckList,
            },
        };

        var root = new DockPanel();
        DockPanel.SetDock(header, Dock.Top);
        root.Children.Add(header);
        root.Children.Add(new ScrollViewer { Content = body });
        Content = root;

        Styles.Add(new Style(x => x.OfType<Border>().Class("card"))
        {
            Setters = { new Setter(Border.BackgroundProperty, new SolidColorBrush(Color.FromArgb(0x14, 0x80, 0x80, 0x80))) },
        });
        Styles.Add(new Style(x => x.OfType<Border>().Class("header"))
        {
            Setters = { new Setter(Border.BackgroundProperty, new SolidColorBrush(Color.FromArgb(0x22, 0x80, 0x80, 0x80))) },
        });

        _server.ClientChanged += OnStatusChanged;
        _pairing.Changed += OnStatusChanged;
        _decks.Changed += OnDecksChanged;
        Closed += (_, _) =>
        {
            _server.ClientChanged -= OnStatusChanged;
            _pairing.Changed -= OnStatusChanged;
            _decks.Changed -= OnDecksChanged;
        };
        UpdateStatus();
        UpdateDecks();
    }

    public IEnumerable<DeckView> DeckViews => _deckList.Children.OfType<DeckView>();

    public string StatusText => _status.Text ?? "";

    public string CodeText => _code.Text ?? "";

    private static Control Docked(Control control, Dock dock)
    {
        DockPanel.SetDock(control, dock);
        return control;
    }

    private static StackPanel Labeled(string label, Control control) => new()
    {
        Margin = new Thickness(0, 0, 16, 8),
        Spacing = 4,
        Children = { new TextBlock { Text = label, Opacity = 0.75 }, control },
    };

    private void AddDeck()
    {
        _decks.Add(_name.Text ?? "", (int)(_cols.Value ?? 5), (int)(_rows.Value ?? 3), (int)(_dials.Value ?? 0));
        _name.Text = "";
        _addForm.IsVisible = false;
    }

    private void OnStatusChanged() => Dispatcher.UIThread.Post(UpdateStatus);

    private void OnDecksChanged() => Dispatcher.UIThread.Post(UpdateDecks);

    private void UpdateStatus()
    {
        var client = _server.ActiveClient;
        var state = client is not null ? _texts.Connected
            : _pairing.PairedClients == 0 ? _texts.NeverPaired
            : _texts.NotConnected;
        _status.Text = $"{_texts.HomeAssistant}: {state} · Port {_options.Port}";
        _code.Text = $"{_pairing.Code[..3]} {_pairing.Code[3..]}";
    }

    private void UpdateDecks()
    {
        _deckList.Children.Clear();
        var decks = _decks.Decks;
        if (decks.Count == 0)
        {
            _deckList.Children.Add(new TextBlock { Text = _texts.NoDecks, TextWrapping = TextWrapping.Wrap, Opacity = 0.7, Name = "noDecks" });
            return;
        }
        foreach (var deck in decks)
        {
            _deckList.Children.Add(new DeckView(deck, _decks.Remove));
        }
    }
}
