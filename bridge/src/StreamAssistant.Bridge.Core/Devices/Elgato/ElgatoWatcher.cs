using StreamAssistant.Bridge.Configuration;

namespace StreamAssistant.Bridge.Devices.Elgato;

/// <summary>
/// Finds Stream Decks on USB and keeps <see cref="DeviceManager"/> in step:
/// scans on every plug event and every few seconds (events can be missed),
/// adds new decks, removes unplugged or failed ones. Off with --usb false.
/// </summary>
public sealed class ElgatoWatcher(
    IHidBackend backend,
    DeviceManager manager,
    BridgeOptions options,
    TimeProvider time,
    ILogger<ElgatoWatcher> logger) : BackgroundService
{
    public static readonly TimeSpan ScanInterval = TimeSpan.FromSeconds(5);

    private readonly Dictionary<string, ElgatoDeck> _decks = [];
    private readonly HashSet<string> _reported = [];
    private readonly SemaphoreSlim _wake = new(0);
    private bool _listFailed;

    /// <summary>Decks currently open, by HID path.</summary>
    public IReadOnlyCollection<ElgatoDeck> Decks => _decks.Values;

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (!options.Usb)
        {
            return;
        }
        backend.Changed += Wake;
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                Scan();
                // Whichever comes first: a plug event, a failed deck or the next poll
                using var poll = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
                poll.CancelAfter(ScanInterval);
                try
                {
                    await _wake.WaitAsync(poll.Token);
                }
                catch (OperationCanceledException) when (!stoppingToken.IsCancellationRequested)
                {
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        finally
        {
            backend.Changed -= Wake;
            // Leave the decks showing the Elgato logo, not a frozen layout
            await Task.WhenAll(_decks.Values.Select(Close));
            _decks.Clear();
        }
    }

    private void Wake() => _wake.Release();

    /// <summary>One pass: drop what is gone or failed, open what is new.</summary>
    internal void Scan()
    {
        IReadOnlyList<HidDeviceEntry> entries;
        try
        {
            entries = backend.List(ElgatoModel.VendorId);
            _listFailed = false;
        }
        catch (Exception err) when (err is not OperationCanceledException)
        {
            if (!_listFailed)
            {
                logger.LogWarning("USB devices cannot be listed, Stream Decks on USB are not available: {Message}", err.Message);
                _listFailed = true;
            }
            return;
        }

        var present = entries.Select(e => e.Path).ToHashSet(StringComparer.Ordinal);
        foreach (var (path, deck) in _decks.ToList())
        {
            if (deck.Failed || !present.Contains(path))
            {
                _decks.Remove(path);
                manager.Remove(deck.Info.Id);
                deck.Dispose();
            }
        }
        _reported.IntersectWith(present);

        foreach (var entry in entries)
        {
            if (_decks.ContainsKey(entry.Path) || ElgatoModel.Find(entry.VendorId, entry.ProductId) is not { } model)
            {
                continue;
            }
            Open(entry, model);
        }
    }

    private void Open(HidDeviceEntry entry, ElgatoModel model)
    {
        IHidDevice? hid = null;
        try
        {
            hid = backend.Open(entry.Path);
            var deck = ElgatoDeck.Start(hid, model, entry.Serial, time, logger);
            deck.Faulted += _ => Wake();
            _decks[entry.Path] = deck;
            _reported.Remove(entry.Path);
            manager.Add(deck);
        }
        catch (Exception err) when (err is IOException or UnauthorizedAccessException or InvalidOperationException or TimeoutException)
        {
            hid?.Dispose();
            // Tried again on every scan; told once
            if (_reported.Add(entry.Path))
            {
                logger.LogWarning(
                    "{Model} found but cannot be opened: {Message}. Close the Elgato Stream Deck app; on Linux, check the udev rule (see the bridge README)",
                    model.Name, err.Message);
            }
        }
    }

    private async Task Close(ElgatoDeck deck)
    {
        manager.Remove(deck.Info.Id);
        await deck.CloseAsync(reset: true);
    }

    public override void Dispose()
    {
        _wake.Dispose();
        base.Dispose();
    }
}
