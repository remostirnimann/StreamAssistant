using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using StreamAssistant.Bridge.Devices.Virtual;

namespace StreamAssistant.Bridge.Desktop;

/// <summary>One virtual deck: its keys as Home Assistant draws them; click or hold to press.</summary>
public sealed class DeckView : Border
{
    private const double KeySize = 96;
    private const double Gap = 10;
    private static readonly IBrush DeckBrush = new SolidColorBrush(Color.Parse("#0c0c0c"));
    private static readonly IBrush EmptyKeyBrush = new SolidColorBrush(Color.Parse("#1b1b1b"));
    private static readonly IBrush FlashBrush = new SolidColorBrush(Color.Parse("#4aa8ff"));

    private readonly VirtualDevice _device;
    private readonly Border[] _keys;
    private readonly Image[] _images;
    private readonly bool[] _down;
    private readonly UniformGrid _grid;
    private readonly Border _frame;

    public DeckView(VirtualDevice device, Action<string> remove)
    {
        _device = device;
        var grid = device.Info.Capabilities.Keys!;
        _keys = new Border[grid.Count];
        _images = new Image[grid.Count];
        _down = new bool[grid.Count];
        var texts = Texts.Current;

        _grid = new UniformGrid { Columns = grid.Cols, Rows = grid.Rows };
        for (var index = 0; index < grid.Count; index++)
        {
            _images[index] = new Image { Stretch = Stretch.UniformToFill };
            var key = new Border
            {
                Width = KeySize,
                Height = KeySize,
                Margin = new Thickness(Gap / 2),
                CornerRadius = new CornerRadius(KeySize * 0.14),
                ClipToBounds = true,
                Background = EmptyKeyBrush,
                Child = _images[index],
                Cursor = new Cursor(StandardCursorType.Hand),
                RenderTransformOrigin = RelativePoint.Center,
                Name = $"key{index}",
            };
            var number = index;
            key.PointerPressed += (_, e) => OnPressed(key, number, e);
            key.PointerReleased += (_, _) => Release(key, number);
            key.PointerCaptureLost += (_, _) => Release(key, number);
            _keys[index] = key;
            _grid.Children.Add(key);
        }

        _frame = new Border
        {
            Background = DeckBrush,
            CornerRadius = new CornerRadius(18),
            Padding = new Thickness(Gap),
            BorderThickness = new Thickness(3),
            BorderBrush = Brushes.Transparent,
            Child = _grid,
        };

        var removeButton = new Button { Content = texts.Remove };
        removeButton.Click += (_, _) =>
        {
            // Second click confirms; no modal dialog needed
            if (Equals(removeButton.Content, texts.RemoveConfirm))
            {
                remove(device.Info.Id);
            }
            else
            {
                removeButton.Content = texts.RemoveConfirm;
            }
        };
        removeButton.LostFocus += (_, _) => removeButton.Content = texts.Remove;

        var header = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
        DockPanel.SetDock(removeButton, Dock.Right);
        header.Children.Add(removeButton);
        header.Children.Add(new StackPanel
        {
            VerticalAlignment = VerticalAlignment.Center,
            Children =
            {
                new TextBlock { Text = device.Info.Name, FontSize = 16, FontWeight = FontWeight.SemiBold },
                new TextBlock { Text = $"{grid.Cols} × {grid.Rows} · {device.Info.Id}", Opacity = 0.65, FontSize = 12 },
            },
        });

        Child = new StackPanel
        {
            Children =
            {
                header,
                // Scales the deck down to the window width, keys stay square
                new Viewbox
                {
                    Stretch = Stretch.Uniform,
                    StretchDirection = StretchDirection.DownOnly,
                    HorizontalAlignment = HorizontalAlignment.Left,
                    Child = _frame,
                },
            },
        };
        Padding = new Thickness(16);
        CornerRadius = new CornerRadius(12);
        Margin = new Thickness(0, 0, 0, 16);
        Classes.Add("card");

        device.Changed += OnChanged;
        device.Identified += OnIdentified;
        DetachedFromVisualTree += (_, _) =>
        {
            device.Changed -= OnChanged;
            device.Identified -= OnIdentified;
        };
        Refresh();
    }

    public VirtualDevice Device => _device;

    /// <summary>For tests: what key <paramref name="index"/> shows.</summary>
    public IImage? KeyImage(int index) => _images[index].Source;

    public double KeyOpacity => _grid.Opacity;

    private void OnChanged(VirtualDevice device, int? key) =>
        Dispatcher.UIThread.Post(() =>
        {
            if (key is { } index)
            {
                ShowKey(index);
            }
            else
            {
                Refresh();
            }
        });

    private void OnIdentified(VirtualDevice device) =>
        Dispatcher.UIThread.Post(async () =>
        {
            _frame.BorderBrush = FlashBrush;
            await Task.Delay(2000);
            _frame.BorderBrush = Brushes.Transparent;
        });

    private void Refresh()
    {
        // Brightness 0 still shows a hint of the keys, so the deck can be found and woken
        _grid.Opacity = Math.Max(_device.Brightness, 6) / 100.0;
        for (var index = 0; index < _keys.Length; index++)
        {
            ShowKey(index);
        }
    }

    private void ShowKey(int index)
    {
        if (index < 0 || index >= _keys.Length)
        {
            return;
        }
        var content = _device.GetKey(index);
        var old = _images[index].Source as Bitmap;
        if (content?.Image is { } bytes)
        {
            try
            {
                using var stream = new MemoryStream(bytes);
                _images[index].Source = new Bitmap(stream);
            }
            catch (Exception)
            {
                // Not decodable: show the key empty rather than failing
                _images[index].Source = null;
            }
            _keys[index].Background = EmptyKeyBrush;
        }
        else
        {
            _images[index].Source = null;
            _keys[index].Background = content?.Color is { } color ? new SolidColorBrush(Color.Parse(color)) : EmptyKeyBrush;
        }
        if (!ReferenceEquals(old, _images[index].Source))
        {
            old?.Dispose();
        }
    }

    private void OnPressed(Border key, int index, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(key).Properties.IsLeftButtonPressed || _down[index])
        {
            return;
        }
        e.Pointer.Capture(key);
        _down[index] = true;
        key.RenderTransform = new ScaleTransform(0.94, 0.94);
        _device.Press(index, true);
        e.Handled = true;
    }

    private void Release(Border key, int index)
    {
        if (!_down[index])
        {
            return;
        }
        _down[index] = false;
        key.RenderTransform = null;
        _device.Press(index, false);
    }
}
