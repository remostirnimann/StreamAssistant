using System.Globalization;

namespace StreamAssistant.Bridge.Desktop;

/// <summary>Window texts in German or English, after the system language.</summary>
public sealed record Texts(
    string HomeAssistant,
    string Connected,
    string NotConnected,
    string NeverPaired,
    string PairingCode,
    string PairingHelp,
    string AddDeck,
    string DeckName,
    string DeckNamePlaceholder,
    string Columns,
    string Rows,
    string Add,
    string Cancel,
    string Remove,
    string RemoveConfirm,
    string NoDecks,
    string AlreadyRunning)
{
    public static readonly Texts German = new(
        HomeAssistant: "Home Assistant",
        Connected: "verbunden",
        NotConnected: "nicht verbunden",
        NeverPaired: "noch nicht gekoppelt",
        PairingCode: "Kopplungscode",
        PairingHelp: "In Home Assistant: Einstellungen → Geräte & Dienste → Stream Assistant. Die Bridge wird meist automatisch gefunden.",
        AddDeck: "+ Virtuelles Deck",
        DeckName: "Name",
        DeckNamePlaceholder: "z. B. Büro Monitor",
        Columns: "Spalten",
        Rows: "Zeilen",
        Add: "Hinzufügen",
        Cancel: "Abbrechen",
        Remove: "Entfernen",
        RemoveConfirm: "Wirklich entfernen?",
        NoDecks: "Noch kein virtuelles Deck. Ein virtuelles Deck erscheint in Home Assistant wie ein echtes Stream Deck: Tasten, Seiten und Vorlagen richtest du dort ein, gedrückt wird hier im Fenster.",
        AlreadyRunning: "Die Stream Assistant Bridge läuft bereits auf diesem Computer.");

    public static readonly Texts English = new(
        HomeAssistant: "Home Assistant",
        Connected: "connected",
        NotConnected: "not connected",
        NeverPaired: "not paired yet",
        PairingCode: "Pairing code",
        PairingHelp: "In Home Assistant: Settings → Devices & services → Stream Assistant. The bridge is usually found automatically.",
        AddDeck: "+ Virtual deck",
        DeckName: "Name",
        DeckNamePlaceholder: "e.g. Office monitor",
        Columns: "Columns",
        Rows: "Rows",
        Add: "Add",
        Cancel: "Cancel",
        Remove: "Remove",
        RemoveConfirm: "Really remove?",
        NoDecks: "No virtual deck yet. A virtual deck shows up in Home Assistant like a real Stream Deck: set up keys, pages and templates there, press them here in the window.",
        AlreadyRunning: "The Stream Assistant Bridge is already running on this computer.");

    public static Texts Current { get; set; } =
        CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "de" ? German : English;
}
