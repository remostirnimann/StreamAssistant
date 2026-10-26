using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using Avalonia.Controls.Shapes;
using StreamAssistant.Bridge.Devices;
using StreamAssistant.Bridge.Devices.Virtual;

namespace StreamAssistant.Bridge.Desktop;

/// <summary>
/// One virtual deck: its keys as Home Assistant draws them; click or hold to press.
/// With dials: the touch strip (click, hold or drag) and the dials (arrows or
/// mouse wheel turn, the knob pushes).
/// </summary>
public sealed class DeckView : Border
{
    private const double KeySize = 96;
    private const double Gap = 10;
    private static readonly IBrush DeckBrush = new SolidColorBrush(Color.Parse("#0c0c0c"));
    private static readonly IBrush EmptyKeyBrush = new SolidColorBrush(Color.Parse("#1b1b1b"));
    private static readonly IBrush FlashBrush = new SolidColorBrush(Color.Parse("#4aa8ff"));
    private static readonly IBrush KnobBrush = new SolidColorBrush(Color.Parse("#3a3a3a"));
    private static readonly TimeSpan LongTouch = TimeSpan.FromMilliseconds(500);

    private readonly VirtualDevice _device;
    private readonly Border[] _keys;
    private readonly Image[] _images;
    private readonly bool[] _down;
    private readonly UniformGrid _grid;
    private readonly Border _frame;
    private readonly Canvas? _strip;
    private (Point At, DateTime Time)? _touchStart;

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

        var controls = new StackPanel { Children = { _grid } };
        if (device.Info.Capabilities.Touch is { } touch && device.Info.Capabilities.Dials is { } dials)
        {
            var width = (grid.Cols * (KeySize + Gap)) - Gap;
            _strip = new Canvas { Width = touch.Width, Height = touch.Height, Background = EmptyKeyBrush, Name = "strip", Cursor = new Cursor(StandardCursorType.Hand) };
            _strip.PointerPressed += OnTouchPressed;
            _strip.PointerReleased += OnTouchReleased;
            controls.Children.Add(new Viewbox
            {
                Width = width,
                Margin = new Thickness(Gap / 2),
                Stretch = Stretch.Uniform,
                Child = new Border { CornerRadius = new CornerRadius(8), ClipToBounds = true, Child = _strip },
            });
            var knobs = new UniformGrid { Columns = dials.Count, Width = width, Margin = new Thickness(Gap / 2) };
            for (var index = 0; index < dials.Count; index++)
            {
                knobs.Children.Add(Dial(index));
            }
            controls.Children.Add(knobs);
        }

        _frame = new Border
        {
            Background = DeckBrush,
            CornerRadius = new CornerRadius(18),
            Padding = new Thickness(Gap),
            BorderThickness = new Thickness(3),
            BorderBrush = Brushes.Transparent,
            Child = controls,
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
                new TextBlock
                {
                    Text = $"{grid.Cols} × {grid.Rows}"
                        + (device.Info.Capabilities.Dials is { } d ? $" + {d.Count} {texts.Dials}" : "")
                        + $" · {device.Info.Id}",
                    Opacity = 0.65,
                    FontSize = 12,
                },
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
        device.TouchChanged += OnTouchChanged;
        DetachedFromVisualTree += (_, _) =>
        {
            device.Changed -= OnChanged;
            device.Identified -= OnIdentified;
            device.TouchChanged -= OnTouchChanged;
        };
        Refresh();
    }

    public VirtualDevice Device => _device;

    /// <summary>For tests: what key <paramref name="index"/> shows.</summary>
    public IImage? KeyImage(int index) => _images[index].Source;

    public double KeyOpacity => _grid.Opacity;

    /// <summary>For tests: how many images the touch strip shows.</summary>
    public int TouchImageCount => _strip?.Children.Count ?? 0;

    private StackPanel Dial(int index)
    {
        Button Arrow(string symbol, int delta, string name)
        {
            var button = new Button
            {
                Content = symbol,
                Name = name,
                Padding = new Thickness(7, 2),
                MinWidth = 0,
                FontSize = 18,
                Foreground = Brushes.Gainsboro,
                Background = KnobBrush,
                VerticalAlignment = VerticalAlignment.Center,
            };
            button.Click += (_, _) => _device.Turn(index, delta);
            return button;
        }

        var knob = new Ellipse { Width = 38, Height = 38, Fill = KnobBrush, Name = $"knob{index}", Cursor = new Cursor(StandardCursorType.Hand), RenderTransformOrigin = RelativePoint.Center };
        var down = false;
        knob.PointerPressed += (_, e) =>
        {
            if (!e.GetCurrentPoint(knob).Properties.IsLeftButtonPressed || down)
            {
                return;
            }
            e.Pointer.Capture(knob);
            down = true;
            knob.RenderTransform = new ScaleTransform(0.92, 0.92);
            _device.PressDial(index, true);
            e.Handled = true;
        };
        void Release()
        {
            if (!down)
            {
                return;
            }
            down = false;
            knob.RenderTransform = null;
            _device.PressDial(index, false);
        }
        knob.PointerReleased += (_, _) => Release();
        knob.PointerCaptureLost += (_, _) => Release();

        var panel = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Center,
            Spacing = 4,
            Background = Brushes.Transparent,
            Children = { Arrow("‹", -1, $"left{index}"), knob, Arrow("›", 1, $"right{index}") },
        };
        panel.PointerWheelChanged += (_, e) =>
        {
            _device.Turn(index, e.Delta.Y < 0 ? 1 : -1);
            e.Handled = true;
        };
        return panel;
    }

    private void OnTouchPressed(object? sender, PointerPressedEventArgs e)
    {
        if (!e.GetCurrentPoint(_strip).Properties.IsLeftButtonPressed)
        {
            return;
        }
        e.Pointer.Capture(_strip);
        _touchStart = (e.GetPosition(_strip), DateTime.UtcNow);
        e.Handled = true;
    }

    private void OnTouchReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_touchStart is not { } start || _strip is null)
        {
            return;
        }
        _touchStart = null;
        var end = e.GetPosition(_strip);
        var (x, y) = ((int)start.At.X, (int)start.At.Y);
        if (Math.Abs(end.X - start.At.X) + Math.Abs(end.Y - start.At.Y) > _strip.Height / 3)
        {
            _device.Touch(TouchInput.Swipe, x, y, (int)end.X, (int)end.Y);
        }
        else
        {
            _device.Touch(DateTime.UtcNow - start.Time >= LongTouch ? TouchInput.Hold : TouchInput.Tap, x, y);
        }
    }

    private void OnTouchChanged(VirtualDevice device, VirtualDevice.TouchImage image) =>
        Dispatcher.UIThread.Post(ShowTouch);

    /// <summary>Draw the strip's images again, oldest first.</summary>
    private void ShowTouch()
    {
        if (_strip is null)
        {
            return;
        }
        foreach (var old in _strip.Children.OfType<Image>())
        {
            (old.Source as Bitmap)?.Dispose();
        }
        _strip.Children.Clear();
        foreach (var touch in _device.TouchImages)
        {
            try
            {
                using var stream = new MemoryStream(touch.Image);
                var image = new Image { Source = new Bitmap(stream), Width = touch.Width, Height = touch.Height, Stretch = Stretch.Fill };
                Canvas.SetLeft(image, touch.X);
                Canvas.SetTop(image, touch.Y);
                _strip.Children.Add(image);
            }
            catch (Exception)
            {
                // Not decodable: leave that part of the strip empty
            }
        }
    }

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
        if (_strip is not null)
        {
            _strip.Opacity = _grid.Opacity;
        }
        for (var index = 0; index < _keys.Length; index++)
        {
            ShowKey(index);
        }
        ShowTouch();
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
