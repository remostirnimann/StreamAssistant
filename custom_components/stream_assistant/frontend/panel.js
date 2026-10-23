// Stream Assistant key editor. Plain web component, no build step.
// Talks to the integration over the WebSocket API (stream_assistant/*).

const ROOT_PAGE = "main";
const DEFAULT_KEY = () => ({
  title: "",
  icon: null,
  icon_off: null,
  entity_id: null,
  second_line: "state",
  second_text: "",
  on_color: "#f2b134",
  off_color: "#2b2b2b",
  text_color: null,
  font_size: null,
  image: null,
  short: { type: "none" },
  long: { type: "none" },
});

const T = {
  de: {
    title: "Stream Assistant",
    device: "Gerät",
    connected: "Verbunden",
    disconnected: "Getrennt",
    noDeck: "Kein Stream Deck angeschlossen",
    noEntries: "Noch kein Dock eingerichtet. Du kannst trotzdem schon planen: Lege eine Vorlage für dein künftiges Stream Deck an. Ein Dock fügst du unter Einstellungen → Geräte & Dienste hinzu.",
    newFolder: "+ Ordner",
    folderName: "Name des neuen Ordners",
    rename: "Umbenennen",
    deletePage: "Ordner löschen",
    confirmDelete: "Ordner und alle Tasten darin löschen?",
    showOnDeck: "Auf Deck anzeigen",
    shownOnDeck: "Wird angezeigt",
    hint: "Taste anklicken zum Bearbeiten. Vorschau mit Live-Zuständen.",
    key: "Taste",
    row: "Reihe",
    col: "Spalte",
    backKey: "Diese Taste führt in Ordnern immer zurück.",
    sectionState: "Status",
    entity: "Entity",
    entityHint: "Steuert Farbe und zweite Zeile. Leer = immer «an»-Farbe.",
    sectionLook: "Darstellung",
    titleField: "Titel",
    titleHint: "Leer = Name der Entity",
    icon: "Icon",
    iconHint: "z. B. mdi:lightbulb, leer = passend zur Entity",
    second: "Zweite Zeile",
    secondState: "Zustand anzeigen",
    secondText: "Eigener Text",
    secondNone: "Nichts",
    secondTextField: "Text",
    onColor: "Farbe wenn an",
    offColor: "Farbe wenn aus",
    textColor: "Textfarbe",
    autoText: "automatisch",
    sectionActions: "Aktionen",
    short: "Kurz drücken",
    long: "Lang drücken (ab 0,5 s)",
    aNone: "Keine",
    aDefault: "Automatisch (passend zur Entity)",
    runs: "Führt aus",
    needsEntity: "Wähle oben eine Entity oder hier eine eigene.",
    aPage: "Ordner / Seite öffnen",
    aBack: "Zurück",
    aCall: "Aktion aufrufen",
    targetEntity: "Entity",
    targetEntityHint: "Leer = Entity von oben",
    page: "Seite",
    actionName: "Aktion",
    actionData: "Daten (JSON)",
    clearKey: "Taste leeren",
    discard: "Verwerfen",
    save: "Speichern",
    saved: "Gespeichert",
    unsaved: "Ungespeicherte Änderungen",
    invalidJson: "Ungültiges JSON",
    root: "Startseite",
    pickEntity: "Entity wählen",
    search: "Suchen …",
    allAreas: "Alle Bereiche",
    noArea: "Ohne Bereich",
    allDevices: "Alle Geräte",
    allTypes: "Alle Typen",
    showHidden: "Auch versteckte und Diagnose-Entities",
    noEntity: "Keine Entity",
    choose: "Wählen",
    remove: "Entfernen",
    moreResults: "Weitere Treffer vorhanden – Suche oder Filter verfeinern.",
    noResults: "Keine Treffer.",
    pickIcon: "Icon wählen",
    iconSearch: "Suchen (englische Namen), z. B. lamp, blinds, door",
    autoIcon: "Automatisch",
    iconOn: "Icon wenn an",
    iconOff: "Icon wenn aus",
    iconAutoHint: "Leer = passend zur Entity und ihrem Zustand. «Aus» leer = wie «an».",
    suggestions: "Vorschläge",
    close: "Schliessen",
    none: "Keine",
    conflict: "Das Layout wurde inzwischen anderswo geändert. «Verwerfen» lädt den aktuellen Stand (deine Änderungen hier gehen verloren).",
    test: "Ausführen",
    testHint: "Wie ein echter Tastendruck: löst die Events und die Aktion aus (auch ungespeichert)",
    tested: "Ausgeführt",
    devices: "Geräte",
    templatesGroup: "Vorlagen",
    newTemplate: "+ Vorlage",
    templateInfo: "Vorlage für {model}",
    usedBy: "verwendet von",
    notUsed: "noch keinem Deck",
    deleteTemplate: "Vorlage löschen",
    droppedKeys: "{n} Tasten der Vorlage passen nicht auf dieses Deck.",
    linkedTo: "Verknüpft mit Vorlage «{name}». Änderungen gelten für alle verknüpften Decks.",
    openTemplate: "Vorlage öffnen",
    detach: "Loskoppeln",
    ownLayout: "Eigenes Layout",
    assignTemplate: "Vorlage zuweisen …",
    saveAsTemplate: "Als Vorlage speichern",
    virtual: "Vorlage (ohne Hardware)",
    leaveUnsaved: "Es gibt ungespeicherte Änderungen. Trotzdem wechseln?",
    templateHelp: "Eine Vorlage ist ein Layout ohne Hardware. Du kannst sie planen, bevor das Deck da ist, und später einem oder mehreren Decks zuweisen.",
    templateName: "Name der Vorlage",
    templateNamePlaceholder: "z. B. Wohnzimmer",
    model: "Modell",
    cancel: "Abbrechen",
    create: "Erstellen",
    savedAsTemplate: "Als Vorlage gespeichert und verknüpft.",
    confirmLink: "Das Deck zeigt danach die Vorlage. Sein bisheriges Layout wird ersetzt. Weiter?",
    confirmDetach: "Das Deck bekommt eine eigene Kopie der Vorlage und folgt ihr nicht mehr. Weiter?",
    confirmDeleteTemplate: "Vorlage löschen? Verknüpfte Decks behalten eine Kopie des Layouts.",
    viewKeys: "Tasten",
    viewInfo: "Info & Verhalten",
    infoTitle: "Informationen",
    behaviorTitle: "Verhalten",
    factDock: "Network Dock",
    factDeck: "Stream Deck",
    factDisplay: "Anzeige",
    factLayout: "Layout",
    factSerial: "Seriennummer",
    factFirmware: "Firmware",
    factAddress: "IP-Adresse",
    factMac: "MAC-Adresse",
    factConnection: "Verbindung",
    factSince: "Verbunden seit",
    factModel: "Modell",
    factKeys: "Tasten",
    factBrightnessSet: "Helligkeit (eingestellt)",
    factBrightnessNow: "Helligkeit (aktuell)",
    factDimsAt: "Dimmt um",
    factTemplate: "Vorlage",
    factPages: "Seiten",
    factFolders: "Ordner",
    factAssigned: "Belegte Tasten",
    factCurrentPage: "Aktuelle Seite",
    stateDimmed: "gedimmt",
    stateNight: "Nacht",
    nightTitle: "Nacht-Helligkeit",
    nightHelp: "Während der Nacht leuchtet das Deck mit eigener Helligkeit.",
    nightMode: "Nacht ist",
    nightModeTime: "Zeitfenster",
    nightModeSun: "Sonne untergegangen",
    nightBrightness: "Helligkeit in der Nacht (%)",
    from: "Von",
    to: "Bis",
    idleTitle: "Ausblenden ohne Bedienung",
    idleHelp: "Nach einer Zeit ohne Tastendruck wird das Deck gedimmt oder ausgeschaltet. Ein Tastendruck holt es zurück.",
    idleTimeout: "Ausblenden nach (Sekunden)",
    idleBrightness: "Helligkeit ausgeblendet (%, 0 = aus)",
    wakeOnly: "Erster Druck weckt nur auf (keine Aktion, keine Events)",
    invalidValues: "Bitte die rot markierten Felder ausfüllen.",
    idleWhen: "Aktiv",
    idleWhenAlways: "Immer",
    idleWhenNight: "Nur nachts",
    idleWhenTime: "Eigenes Zeitfenster",
    idleWhenNightHelp: "Nacht wie oben bei der Nacht-Helligkeit definiert (Zeitfenster oder Sonne), auch wenn diese ausgeschaltet ist.",
    saveBehavior: "Verhalten speichern",
  },
  en: {
    title: "Stream Assistant",
    device: "Device",
    connected: "Connected",
    disconnected: "Disconnected",
    noDeck: "No Stream Deck attached",
    noEntries: "No dock set up yet. You can already plan: create a template for your future Stream Deck. Add a dock under Settings → Devices & services.",
    newFolder: "+ Folder",
    folderName: "Name of the new folder",
    rename: "Rename",
    deletePage: "Delete folder",
    confirmDelete: "Delete the folder and all its keys?",
    showOnDeck: "Show on deck",
    shownOnDeck: "Shown on deck",
    hint: "Click a key to edit it. Preview uses live states.",
    key: "Key",
    row: "Row",
    col: "Column",
    backKey: "In folders this key always goes back.",
    sectionState: "State",
    entity: "Entity",
    entityHint: "Drives colour and second line. Empty = always the 'on' colour.",
    sectionLook: "Appearance",
    titleField: "Title",
    titleHint: "Empty = entity name",
    icon: "Icon",
    iconHint: "e.g. mdi:lightbulb, empty = matching the entity",
    second: "Second line",
    secondState: "Show state",
    secondText: "Custom text",
    secondNone: "Nothing",
    secondTextField: "Text",
    onColor: "Colour when on",
    offColor: "Colour when off",
    textColor: "Text colour",
    autoText: "automatic",
    sectionActions: "Actions",
    short: "Short press",
    long: "Long press (0.5 s)",
    aNone: "None",
    aDefault: "Automatic (matching the entity)",
    runs: "Runs",
    needsEntity: "Choose an entity above or a specific one here.",
    aPage: "Open folder / page",
    aBack: "Back",
    aCall: "Call action",
    targetEntity: "Entity",
    targetEntityHint: "Empty = entity from above",
    page: "Page",
    actionName: "Action",
    actionData: "Data (JSON)",
    clearKey: "Clear key",
    discard: "Discard",
    save: "Save",
    saved: "Saved",
    unsaved: "Unsaved changes",
    invalidJson: "Invalid JSON",
    root: "Home",
    pickEntity: "Choose entity",
    search: "Search …",
    allAreas: "All areas",
    noArea: "No area",
    allDevices: "All devices",
    allTypes: "All types",
    showHidden: "Include hidden and diagnostic entities",
    noEntity: "No entity",
    choose: "Choose",
    remove: "Remove",
    moreResults: "More results available – refine the search or filters.",
    noResults: "No results.",
    pickIcon: "Choose icon",
    iconSearch: "Search, e.g. lamp, blinds, door",
    autoIcon: "Automatic",
    iconOn: "Icon when on",
    iconOff: "Icon when off",
    iconAutoHint: "Empty = matching the entity and its state. 'Off' empty = same as 'on'.",
    suggestions: "Suggestions",
    close: "Close",
    none: "None",
    conflict: "The layout was changed elsewhere. 'Discard' loads the current version (your changes here are lost).",
    test: "Run",
    testHint: "Like a real key press: fires the events and the action (also unsaved)",
    tested: "Ran",
    devices: "Devices",
    templatesGroup: "Templates",
    newTemplate: "+ Template",
    templateInfo: "Template for {model}",
    usedBy: "used by",
    notUsed: "no deck yet",
    deleteTemplate: "Delete template",
    droppedKeys: "{n} keys of the template do not fit this deck.",
    linkedTo: "Linked to template '{name}'. Changes apply to all linked decks.",
    openTemplate: "Open template",
    detach: "Detach",
    ownLayout: "Own layout",
    assignTemplate: "Assign template …",
    saveAsTemplate: "Save as template",
    virtual: "Template (no hardware)",
    leaveUnsaved: "There are unsaved changes. Switch anyway?",
    templateHelp: "A template is a layout without hardware. Plan it before the deck arrives and assign it to one or more decks later.",
    templateName: "Template name",
    templateNamePlaceholder: "e.g. Living room",
    model: "Model",
    cancel: "Cancel",
    create: "Create",
    savedAsTemplate: "Saved as template and linked.",
    confirmLink: "The deck will show the template, replacing its current layout. Continue?",
    confirmDetach: "The deck gets its own copy of the template and stops following it. Continue?",
    confirmDeleteTemplate: "Delete the template? Linked decks keep a copy of the layout.",
    viewKeys: "Keys",
    viewInfo: "Info & behaviour",
    infoTitle: "Information",
    behaviorTitle: "Behaviour",
    factDock: "Network Dock",
    factDeck: "Stream Deck",
    factDisplay: "Display",
    factLayout: "Layout",
    factSerial: "Serial number",
    factFirmware: "Firmware",
    factAddress: "IP address",
    factMac: "MAC address",
    factConnection: "Connection",
    factSince: "Connected since",
    factModel: "Model",
    factKeys: "Keys",
    factBrightnessSet: "Brightness (set)",
    factBrightnessNow: "Brightness (now)",
    factDimsAt: "Dims at",
    factTemplate: "Template",
    factPages: "Pages",
    factFolders: "folders",
    factAssigned: "Assigned keys",
    factCurrentPage: "Current page",
    stateDimmed: "dimmed",
    stateNight: "night",
    nightTitle: "Night brightness",
    nightHelp: "At night the deck uses its own brightness.",
    nightMode: "Night is",
    nightModeTime: "Time window",
    nightModeSun: "Sun has set",
    nightBrightness: "Brightness at night (%)",
    from: "From",
    to: "To",
    idleTitle: "Fade out when idle",
    idleHelp: "After a while without key presses the deck dims or turns off. A key press brings it back.",
    idleTimeout: "Fade out after (seconds)",
    idleBrightness: "Brightness when faded (%, 0 = off)",
    wakeOnly: "First press only wakes (no action, no events)",
    invalidValues: "Please fill in the fields marked red.",
    idleWhen: "Active",
    idleWhenAlways: "Always",
    idleWhenNight: "Only at night",
    idleWhenTime: "Own time window",
    idleWhenNightHelp: "Night as defined above for night brightness (time window or sun), even if that is turned off.",
    saveBehavior: "Save behaviour",
  },
};

const DOMAIN_NAMES = {
  de: {
    light: "Licht", switch: "Schalter", cover: "Storen / Abdeckung", sensor: "Sensor",
    binary_sensor: "Binärsensor", scene: "Szene", script: "Skript", automation: "Automation",
    media_player: "Medien", climate: "Klima", lock: "Schloss", fan: "Ventilator",
    button: "Taste", input_boolean: "Helfer: Schalter", input_number: "Helfer: Zahl",
    input_select: "Helfer: Auswahl", input_button: "Helfer: Taste", camera: "Kamera",
    person: "Person", vacuum: "Staubsauger", valve: "Ventil", number: "Zahl", select: "Auswahl",
    weather: "Wetter", update: "Update", device_tracker: "Geräte-Tracker", zone: "Zone",
  },
  en: {},
};

// Icon names (without "mdi:") offered before the user searches
const ICON_SUGGESTIONS = {
  light: ["lightbulb", "lightbulb-on", "lightbulb-outline", "lightbulb-off", "ceiling-light", "floor-lamp", "desk-lamp", "lamp", "led-strip-variant", "wall-sconce", "string-lights", "chandelier"],
  switch: ["toggle-switch", "toggle-switch-off", "power-plug", "power-plug-off", "power", "power-off"],
  cover: ["window-shutter", "window-shutter-open", "blinds", "blinds-open", "roller-shade", "roller-shade-closed", "curtains", "curtains-closed", "garage", "garage-open", "arrow-up", "arrow-down"],
  lock: ["lock", "lock-open-variant", "door-closed-lock", "door-open"],
  media_player: ["play", "pause", "play-pause", "stop", "skip-next", "skip-previous", "volume-high", "volume-off", "speaker", "television", "music"],
  scene: ["palette", "movie-open", "weather-night", "sofa", "silverware-fork-knife", "party-popper", "book-open-variant", "bed"],
  script: ["script-text", "play-circle", "robot", "flash"],
  climate: ["thermostat", "radiator", "radiator-off", "air-conditioner", "fire", "snowflake"],
  fan: ["fan", "fan-off", "air-purifier"],
  sensor: ["thermometer", "water-percent", "gauge", "flash", "lightning-bolt", "weather-sunny", "molecule-co2"],
  binary_sensor: ["door-open", "door-closed", "window-open", "window-closed", "motion-sensor", "motion-sensor-off", "smoke-detector", "water-alert"],
  vacuum: ["robot-vacuum", "home-import-outline"],
  _common: ["home", "folder", "folder-outline", "arrow-left", "arrow-right", "power", "bell", "alarm", "car", "door", "garage", "weather-sunny", "weather-night", "account", "heart", "star", "cog", "information-outline"],
};

// Mirrors actions.py: what "automatic" calls for an entity
const DEFAULT_SERVICES = {
  light: "toggle", switch: "toggle", fan: "toggle", input_boolean: "toggle", group: "toggle",
  siren: "toggle", humidifier: "toggle", climate: "toggle", cover: "toggle", valve: "toggle",
  media_player: "media_play_pause", scene: "turn_on", script: "turn_on", button: "press",
  input_button: "press", automation: "trigger", vacuum: "start",
};
const defaultService = (entityId, state) => {
  const domain = entityId.split(".")[0];
  if (domain === "lock") return `lock.${state?.state === "locked" ? "unlock" : "lock"}`;
  if (domain === "vacuum") return `vacuum.${state?.state === "cleaning" ? "return_to_base" : "start"}`;
  return DEFAULT_SERVICES[domain] ? `${domain}.${DEFAULT_SERVICES[domain]}` : "homeassistant.toggle";
};

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const clone = (value) => JSON.parse(JSON.stringify(value));
const newId = () => Math.random().toString(16).slice(2, 10);

class StreamAssistantPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._started = false;
    this.entries = [];
    this.templates = [];
    this.models = [];
    this.targetKind = "entry";
    this.entryId = null;
    this.view = "keys";
    this.dockInfo = null;
    this.behaviorDraft = null;
    this.behaviorDirty = false;
    this._behaviorErrors = new Set();
    this._infoTimer = null;
    this.info = null;
    this.saved = null;
    this.draft = null;
    this.pageId = ROOT_PAGE;
    this.selected = null;
    this.images = [];
    this.dirty = false;
    this.message = "";
    this.icons = [];
    this._previewTimer = null;
    this._entityStamps = "";
    this._jsonErrors = {};
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.hass = hass;
    if (first && !this._started) {
      this._started = true;
      this._init();
    } else {
      this._maybeRefreshForStates();
    }
  }

  set narrow(value) {
    this._narrow = value;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.narrow = value;
  }

  set panel(_value) {}

  get t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2);
    return T[lang] || T.en;
  }

  // Data

  async _init() {
    this._renderShell();
    try {
      let lists;
      [lists, this.icons, this.models] = await Promise.all([
        this._hass.callWS({ type: "stream_assistant/entries" }),
        this._hass.callWS({ type: "stream_assistant/icons" }),
        this._hass.callWS({ type: "stream_assistant/models" }),
      ]);
      this.entries = lists.entries;
      this.templates = lists.templates;
    } catch (err) {
      this.message = String(err?.message || err);
    }
    if (this.entries.length) await this._loadTarget("entry", this.entries[0].entry_id);
    else if (this.templates.length) await this._loadTarget("template", this.templates[0].template_id);
    else this._renderAll();
  }

  async _refreshLists() {
    const lists = await this._hass.callWS({ type: "stream_assistant/entries" });
    this.entries = lists.entries;
    this.templates = lists.templates;
  }

  // Parameters that address the current dock or template in WebSocket calls
  get _targetParams() {
    return this.targetKind === "template" ? { template_id: this.entryId } : { entry_id: this.entryId };
  }

  get isTemplate() {
    return this.targetKind === "template";
  }

  // Kept for the existing callers: a dock is the default target kind
  async _loadEntry(id) {
    return this._loadTarget(this.targetKind || "entry", id);
  }

  async _loadTarget(kind, id) {
    this.targetKind = kind;
    this.entryId = id;
    const result = await this._hass.callWS({ type: "stream_assistant/layout/get", ...this._targetParams });
    this.info = result;
    this.revision = result.revision;
    this.saved = result.layout;
    this.draft = clone(result.layout);
    this.pageId = result.current_page || ROOT_PAGE;
    this.selected = null;
    this.dirty = false;
    this.message = "";
    if (this.view === "info" && !this.isTemplate) {
      await this._showView("info");
      return;
    }
    if (this.isTemplate) {
      this.view = "keys";
      clearInterval(this._infoTimer);
      this._infoTimer = null;
    }
    this._renderAll();
    this._schedulePreview(0);
  }

  get page() {
    return this.draft?.pages.find((p) => p.id === this.pageId) || this.draft?.pages[0];
  }

  _isBackKey(index) {
    return Boolean(this.page?.parent) && index === 0;
  }

  _key(index) {
    return this.page?.keys[String(index)] || null;
  }

  _ensureKey(index) {
    const keys = this.page.keys;
    if (!keys[String(index)]) keys[String(index)] = DEFAULT_KEY();
    return keys[String(index)];
  }

  _changed() {
    this.dirty = true;
    this.message = "";
    this._renderStatus();
    this._schedulePreview();
  }

  _schedulePreview(delay = 250) {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => this._preview(), delay);
  }

  async _preview() {
    if (!this.entryId || !this.info?.model || !this.page) return;
    try {
      const result = await this._hass.callWS({
        type: "stream_assistant/preview",
        ...this._targetParams,
        page: this._cleanPage(this.page),
      });
      this.images = result.images;
      this._renderDeck();
    } catch (_err) {
      // Typing in progress (e.g. half an entity id): keep the last preview
    }
  }

  _maybeRefreshForStates() {
    if (!this.page || !this._hass) return;
    const ids = Object.values(this.page.keys)
      .map((k) => k.entity_id)
      .filter(Boolean);
    const stamp = ids.map((id) => this._hass.states[id]?.last_updated || "").join("|");
    if (stamp !== this._entityStamps) {
      this._entityStamps = stamp;
      this._schedulePreview(400);
    }
  }

  // Remove empty optional values so the backend schema accepts the draft
  _cleanKey(key) {
    const out = clone(key);
    for (const field of ["icon", "icon_off", "entity_id", "text_color", "image"]) {
      if (!out[field]) out[field] = null;
    }
    if (out.font_size === "" || out.font_size === undefined) out.font_size = null;
    for (const slot of ["short", "long"]) {
      const action = out[slot];
      if (action.type === "default") {
        const entity = action.entity_id || out.entity_id;
        out[slot] = entity ? { type: "default", entity_id: entity } : { type: "none" };
      } else if (action.type === "action") {
        out[slot] = {
          type: "action",
          action: action.action || "",
          data: action.data || {},
          target: action.target || {},
        };
        if (!out[slot].action) out[slot] = { type: "none" };
      } else if (action.type === "page") {
        out[slot] = action.page ? { type: "page", page: action.page } : { type: "none" };
      } else {
        out[slot] = { type: action.type };
      }
    }
    return out;
  }

  // A key with nothing on it and no action is not stored (it would light up in the "on" colour)
  _isEmptyKey(key) {
    return (
      !key.title && !key.icon && !key.icon_off && !key.entity_id && !key.image &&
      !(key.second_line === "text" && key.second_text) &&
      key.short.type === "none" && key.long.type === "none"
    );
  }

  _cleanPage(page) {
    const keys = {};
    for (const [index, key] of Object.entries(page.keys)) {
      const clean = this._cleanKey(key);
      if (!this._isEmptyKey(clean)) keys[index] = clean;
    }
    return { id: page.id, name: page.name, parent: page.parent || null, keys };
  }

  async _save() {
    if (Object.keys(this._jsonErrors).length) {
      this.message = this.t.invalidJson;
      this._renderStatus();
      return;
    }
    const layout = { pages: this.draft.pages.map((p) => this._cleanPage(p)) };
    try {
      const result = await this._hass.callWS({
        type: "stream_assistant/layout/save",
        ...this._targetParams,
        layout,
        revision: this.revision,
      });
      this.revision = result.revision;
      this.saved = result.layout;
      this.draft = clone(result.layout);
      if (!this.draft.pages.some((p) => p.id === this.pageId)) this.pageId = ROOT_PAGE;
      this.dirty = false;
      this.message = this.t.saved;
    } catch (err) {
      this.message = err?.code === "conflict" ? this.t.conflict : String(err?.message || err);
    }
    this._renderAll();
    this._schedulePreview(0);
  }

  // Reload from the server: also the way out of a save conflict
  async _discard() {
    const pageId = this.pageId;
    this._jsonErrors = {};
    await this._loadEntry(this.entryId);
    if (this.draft.pages.some((p) => p.id === pageId)) {
      this.pageId = pageId;
      this._renderAll();
      this._schedulePreview(0);
    }
  }

  async _showOnDeck() {
    if (this.dirty) await this._save();
    const result = await this._hass.callWS({
      type: "stream_assistant/show_page",
      entry_id: this.entryId,
      page_id: this.pageId,
    });
    this.info.current_page = result.current_page;
    this._renderTabs();
  }

  // Templates

  get _infoActive() {
    return this.view === "info" && !this.isTemplate;
  }

  // Unsaved keys or unsaved behaviour: ask before throwing them away
  _confirmLeave() {
    return (!this.dirty && !this.behaviorDirty) || confirm(this.t.leaveUnsaved);
  }

  async _afterTemplateChange(kind, id) {
    await this._refreshLists();
    await this._loadTarget(kind, id);
  }

  _openTemplateDialog() {
    const t = this.t;
    this._picker = { kind: "template" };
    const dlg = this.shadowRoot.getElementById("picker");
    const models = this.models
      .map((m) => `<option value="${esc(m.id)}">${esc(m.name)} (${m.cols} × ${m.rows})</option>`)
      .join("");
    dlg.innerHTML = `
      <div class="dlg-head"><h2>${t.newTemplate}</h2><button type="button" class="icon-btn" data-role="pk-close" aria-label="${esc(t.close)}"><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="dlg-body">
        <p class="help">${t.templateHelp}</p>
        <label>${t.templateName}<input id="tpl-name" maxlength="60" placeholder="${esc(t.templateNamePlaceholder)}"></label>
        <label>${t.model}<select id="tpl-model">${models}</select></label>
      </div>
      <div class="dlg-foot">
        <button type="button" class="btn" data-role="pk-close">${t.cancel}</button>
        <button type="button" class="btn primary" data-role="tpl-create">${t.create}</button>
      </div>`;
    dlg.showModal();
    this.shadowRoot.getElementById("tpl-name").focus();
  }

  async _createTemplate() {
    const name = this.shadowRoot.getElementById("tpl-name").value.trim();
    const model = this.shadowRoot.getElementById("tpl-model").value;
    if (!name) return;
    if (!this._confirmLeave()) return;
    this._closePicker();
    const result = await this._hass.callWS({ type: "stream_assistant/template/create", name, model });
    await this._afterTemplateChange("template", result.template_id);
  }

  async _saveAsTemplate() {
    const t = this.t;
    if (this.dirty) await this._save();
    const name = prompt(t.templateName, this.info.title);
    if (!name) return;
    await this._hass.callWS({ type: "stream_assistant/template/create", name: name.slice(0, 60), from_entry_id: this.entryId });
    await this._afterTemplateChange("entry", this.entryId);
    this.message = t.savedAsTemplate;
    this._renderStatus();
  }

  async _link(templateId) {
    const t = this.t;
    if (!templateId || !this._confirmLeave() || !confirm(t.confirmLink)) {
      this._renderLinkBar();
      return;
    }
    const result = await this._hass.callWS({ type: "stream_assistant/link", entry_id: this.entryId, template_id: templateId });
    await this._afterTemplateChange("entry", this.entryId);
    if (result.dropped) {
      this.message = t.droppedKeys.replace("{n}", result.dropped);
      this._renderStatus();
    }
  }

  async _detach() {
    if (!this._confirmLeave() || !confirm(this.t.confirmDetach)) return;
    await this._hass.callWS({ type: "stream_assistant/detach", entry_id: this.entryId });
    await this._afterTemplateChange("entry", this.entryId);
  }

  async _renameTemplate() {
    const name = prompt(this.t.rename, this.info.title);
    if (!name) return;
    await this._hass.callWS({ type: "stream_assistant/template/rename", template_id: this.entryId, name: name.slice(0, 60) });
    await this._refreshLists();
    this.info.title = name.slice(0, 60);
    this._renderAll();
  }

  async _deleteTemplate() {
    if (!confirm(this.t.confirmDeleteTemplate)) return;
    await this._hass.callWS({ type: "stream_assistant/template/delete", template_id: this.entryId });
    await this._refreshLists();
    this.dirty = false;
    if (this.entries.length) await this._loadTarget("entry", this.entries[0].entry_id);
    else if (this.templates.length) await this._loadTarget("template", this.templates[0].template_id);
    else {
      this.info = null;
      this._renderAll();
    }
  }

  _addFolder() {
    const name = prompt(this.t.folderName);
    if (!name) return;
    const page = { id: newId(), name: name.slice(0, 40), parent: this.pageId, keys: {} };
    this.draft.pages.push(page);
    this.pageId = page.id;
    this.selected = null;
    this._changed();
    this._renderAll();
  }

  _renamePage() {
    const name = prompt(this.t.rename, this.page.name);
    if (!name) return;
    this.page.name = name.slice(0, 40);
    this._changed();
    this._renderTabs();
  }

  _deletePage() {
    if (this.page.id === ROOT_PAGE || !confirm(this.t.confirmDelete)) return;
    const doomed = new Set([this.page.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const p of this.draft.pages) {
        if (p.parent && doomed.has(p.parent) && !doomed.has(p.id)) {
          doomed.add(p.id);
          grew = true;
        }
      }
    }
    const parent = this.page.parent || ROOT_PAGE;
    this.draft.pages = this.draft.pages.filter((p) => !doomed.has(p.id));
    // Keys that opened a deleted page do nothing now
    for (const p of this.draft.pages) {
      for (const key of Object.values(p.keys)) {
        for (const slot of ["short", "long"]) {
          if (key[slot].type === "page" && doomed.has(key[slot].page)) key[slot] = { type: "none" };
        }
      }
    }
    this.pageId = parent;
    this.selected = null;
    this._changed();
    this._renderAll();
  }

  // Rendering

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="toolbar">
        <ha-menu-button></ha-menu-button>
        <div class="main-title">Stream Assistant</div>
        <nav class="header-views" id="header-views"></nav>
      </div>
      <div class="content" id="content"></div>
      <dialog id="picker" class="dlg"></dialog>`;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("input", (ev) => this._onInput(ev));
    this.shadowRoot.addEventListener("change", (ev) => this._onChange(ev));
  }

  _renderAll() {
    const t = this.t;
    const content = this.shadowRoot.getElementById("content");
    if (!this.entries.length && !this.templates.length) {
      content.innerHTML = `<div class="card empty">${esc(this.message || t.noEntries)}
        <p><button class="btn" data-role="new-template">${t.newTemplate}</button></p></div>`;
      return;
    }
    const option = (kind, id, title) => {
      const selected = kind === this.targetKind && id === this.entryId;
      return `<option value="${kind}:${esc(id)}" ${selected ? "selected" : ""}>${esc(title)}</option>`;
    };
    const entryOptions = this.entries.map((e) => option("entry", e.entry_id, e.title)).join("");
    const templateOptions = this.templates
      .map((tpl) => option("template", tpl.template_id, `${tpl.title} (${tpl.model?.name || "?"})`))
      .join("");
    content.innerHTML = `
      <div class="topbar">
        <label class="inline">${t.device}
          <select data-role="entry">
            ${entryOptions ? `<optgroup label="${esc(t.devices)}">${entryOptions}</optgroup>` : ""}
            ${templateOptions ? `<optgroup label="${esc(t.templatesGroup)}">${templateOptions}</optgroup>` : ""}
          </select>
        </label>
        <button class="btn small" data-role="new-template">${t.newTemplate}</button>
        <span id="status-chip"></span>
        <span class="spacer"></span>
        <span id="status-text" class="status-text"></span>
        ${this._infoActive
          ? "" /* The info view has its own "save behaviour" button; these act on the keys */
          : `<button class="btn" data-role="discard">${t.discard}</button>
        <button class="btn primary" data-role="save">${t.save}</button>`}
      </div>
      <div class="linkbar card" id="linkbar"></div>
      ${!this.isTemplate && this.view === "info" ? this._infoViewHtml() : `<div class="layout">
        <section class="left">
          <div class="tabs" id="tabs"></div>
          <div class="card deck-card">
            <div class="deck" id="deck"></div>
            <p class="hint">${t.hint}</p>
          </div>
        </section>
        <aside class="card right" id="form"></aside>
      </div>`}`;
    this._renderStatus();
    this._renderHeaderViews();
    this._renderLinkBar();
    this._renderTabs();
    this._renderDeck();
    this._renderForm();
    this._renderFacts();
  }

  // View switch lives in the header bar, like tabs of HA's own pages
  _renderHeaderViews() {
    const t = this.t;
    const views = this.shadowRoot.getElementById("header-views");
    if (!views) return;
    if (this.isTemplate || !this.entries.length) {
      views.innerHTML = "";
      return;
    }
    const tab = (view, icon, label) =>
      `<button class="header-tab ${this.view === view ? "active" : ""}" data-role="view" data-view="${view}" aria-pressed="${this.view === view}" aria-label="${esc(label)}">
        <ha-icon icon="${icon}"></ha-icon><span>${label}</span></button>`;
    views.innerHTML = tab("keys", "mdi:keyboard-outline", t.viewKeys) + tab("info", "mdi:information-outline", t.viewInfo);
  }

  // Info & behavior view (docks only)

  async _showView(view) {
    this.view = view;
    clearInterval(this._infoTimer);
    this._infoTimer = null;
    this.behaviorDirty = false;
    this._behaviorErrors = new Set();
    if (view === "info") {
      await this._loadInfo();
      this.behaviorDraft = clone(this.dockInfo.behavior);
      this._infoTimer = setInterval(() => this._loadInfo().then(() => this._renderFacts()), 5000);
    }
    this._renderAll();
    if (view === "keys") this._schedulePreview(0);
  }

  async _loadInfo() {
    try {
      this.dockInfo = await this._hass.callWS({ type: "stream_assistant/info", entry_id: this.entryId });
    } catch (err) {
      this.message = String(err?.message || err);
    }
  }

  disconnectedCallback() {
    clearInterval(this._infoTimer);
    this._infoTimer = null;
  }

  connectedCallback() {
    // Coming back to the panel: keep the info page live again
    if (this.view === "info" && !this._infoTimer && this.entryId && !this.isTemplate) {
      this._infoTimer = setInterval(() => this._loadInfo().then(() => this._renderFacts()), 5000);
    }
  }

  _fmtDate(iso) {
    if (!iso) return "–";
    return new Date(iso).toLocaleString(this._hass?.locale?.language || undefined, {
      dateStyle: "short",
      timeStyle: "short",
    });
  }

  _renderFacts() {
    const facts = this.shadowRoot.getElementById("facts");
    if (!facts || !this.dockInfo) return;
    const t = this.t;
    const i = this.dockInfo;
    const yes = (v) => (v ? t.connected : t.disconnected);
    const tpl = i.layout.template_id ? this.templates.find((x) => x.template_id === i.layout.template_id)?.title || "?" : t.ownLayout;
    const page = this.draft?.pages.find((p) => p.id === i.layout.current_page);
    let brightness = `${i.brightness.current} %`;
    if (i.brightness.dimmed) brightness += ` (${t.stateDimmed})`;
    else if (i.brightness.night_active) brightness += ` (${t.stateNight})`;
    const rows = [
      [t.factDock, ""],
      [t.factSerial, i.dock.serial],
      [t.factFirmware, i.dock.firmware || "–"],
      [t.factAddress, i.dock.host],
      [t.factMac, i.dock.mac || "–"],
      [t.factConnection, yes(i.dock.connected)],
      [t.factDeck, ""],
      [t.factModel, i.deck.model || "–"],
      [t.factSerial, i.deck.serial || "–"],
      [t.factFirmware, i.deck.firmware || "–"],
      [t.factConnection, yes(i.deck.connected)],
      [t.factSince, this._fmtDate(i.deck.connected_since)],
      [t.factKeys, i.deck.key_count ?? "–"],
      [t.factDisplay, ""],
      [t.factBrightnessSet, `${i.brightness.base} %`],
      [t.factBrightnessNow, brightness],
      [t.factDimsAt, i.brightness.dims_at ? this._fmtDate(i.brightness.dims_at) : "–"],
      [t.factLayout, ""],
      [t.factTemplate, tpl],
      [t.factPages, `${i.layout.pages} (${i.layout.folders} ${t.factFolders})`],
      [t.factAssigned, i.layout.keys],
      [t.factCurrentPage, page ? (page.id === ROOT_PAGE ? t.root : page.name) : i.layout.current_page],
    ];
    facts.innerHTML = rows
      .map(([k, v]) => (v === "" ? `<dt class="fact-group">${esc(k)}</dt>` : `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`))
      .join("");
  }

  _infoViewHtml() {
    const t = this.t;
    const b = this.behaviorDraft || { night: {}, idle: {} };
    const n = b.night;
    const idle = b.idle;
    const checked = (v) => (v ? "checked" : "");
    return `<div class="layout">
      <section class="card info-card">
        <h2>${t.infoTitle}</h2>
        <dl class="facts" id="facts"></dl>
      </section>
      <section class="card info-card">
        <h2>${t.behaviorTitle}</h2>
        <div class="section">
          <label class="check toggle"><input type="checkbox" data-bfield="night.enabled" ${checked(n.enabled)}>${t.nightTitle}</label>
          <p class="help">${t.nightHelp}</p>
          <div class="grid2 ${n.enabled ? "" : "disabled"}">
            <label>${t.nightMode}<select data-bfield="night.mode">
              <option value="time" ${n.mode === "time" ? "selected" : ""}>${t.nightModeTime}</option>
              <option value="sun" ${n.mode === "sun" ? "selected" : ""}>${t.nightModeSun}</option>
            </select></label>
            <label>${t.nightBrightness}<input type="number" min="0" max="100" data-bfield="night.brightness" value="${esc(n.brightness)}"></label>
            ${n.mode === "sun" ? "" : `<label>${t.from}<input type="time" data-bfield="night.start" value="${esc(n.start)}"></label>
            <label>${t.to}<input type="time" data-bfield="night.end" value="${esc(n.end)}"></label>`}
          </div>
        </div>
        <div class="section">
          <label class="check toggle"><input type="checkbox" data-bfield="idle.enabled" ${checked(idle.enabled)}>${t.idleTitle}</label>
          <p class="help">${t.idleHelp}</p>
          <div class="grid2 ${idle.enabled ? "" : "disabled"}">
            <label>${t.idleTimeout}<input type="number" min="5" max="86400" data-bfield="idle.timeout" value="${esc(idle.timeout)}"></label>
            <label>${t.idleBrightness}<input type="number" min="0" max="100" data-bfield="idle.brightness" value="${esc(idle.brightness)}"></label>
            <label>${t.idleWhen}<select data-bfield="idle.when">
              <option value="always" ${idle.when === "always" ? "selected" : ""}>${t.idleWhenAlways}</option>
              <option value="night" ${idle.when === "night" ? "selected" : ""}>${t.idleWhenNight}</option>
              <option value="time" ${idle.when === "time" ? "selected" : ""}>${t.idleWhenTime}</option>
            </select></label>
            <span></span>
            ${idle.when === "time" ? `<label>${t.from}<input type="time" data-bfield="idle.start" value="${esc(idle.start)}"></label>
            <label>${t.to}<input type="time" data-bfield="idle.end" value="${esc(idle.end)}"></label>` : ""}
          </div>
          ${idle.when === "night" ? `<p class="help">${t.idleWhenNightHelp}</p>` : ""}
          <label class="check"><input type="checkbox" data-bfield="idle.wake_only" ${checked(idle.wake_only)}>${t.wakeOnly}</label>
        </div>
        <div class="form-foot"><button class="btn primary" data-role="save-behavior">${t.saveBehavior}</button></div>
      </section>
    </div>`;
  }

  _onBehaviorInput(el) {
    const [group, field] = el.dataset.bfield.split(".");
    let value = el.value;
    if (el.type === "checkbox") value = el.checked;
    else if (el.type === "number" || el.type === "time") {
      // An emptied or out-of-range field must not silently become 0 / be sent
      const invalid = el.value === "" || !el.checkValidity();
      el.classList.toggle("invalid", invalid);
      this._behaviorErrors[invalid ? "add" : "delete"](el.dataset.bfield);
      if (invalid) {
        this.behaviorDirty = true;
        this._renderStatus();
        return;
      }
      if (el.type === "number") value = Number(value);
    }
    this.behaviorDraft[group][field] = value;
    this.behaviorDirty = true;
    this.message = this.t.unsaved;
    this._renderStatus();
  }

  async _saveBehavior() {
    if (this._behaviorErrors.size) {
      this.message = this.t.invalidValues;
      this._renderStatus();
      return;
    }
    try {
      this.dockInfo = await this._hass.callWS({
        type: "stream_assistant/behavior/set",
        entry_id: this.entryId,
        behavior: this.behaviorDraft,
      });
      this.behaviorDraft = clone(this.dockInfo.behavior);
      this.behaviorDirty = false;
      this.message = this.t.saved;
    } catch (err) {
      this.message = String(err?.message || err);
    }
    this._renderAll();
  }

  _renderLinkBar() {
    const t = this.t;
    const bar = this.shadowRoot.getElementById("linkbar");
    if (!bar || !this.info) return;
    if (this.isTemplate) {
      const used = this.info.linked?.length ? this.info.linked.join(", ") : t.notUsed;
      bar.innerHTML = `<ha-icon icon="mdi:file-document-outline"></ha-icon>
        <span class="link-text">${esc(t.templateInfo.replace("{model}", this.info.model?.name || "?"))} · ${esc(t.usedBy)}: ${esc(used)}</span>
        <span class="spacer"></span>
        <button class="btn small" data-role="rename-template">${t.rename}</button>
        <button class="btn small danger" data-role="delete-template">${t.deleteTemplate}</button>`;
      return;
    }
    if (this.info.template_id) {
      const tpl = this.templates.find((x) => x.template_id === this.info.template_id);
      const dropped = this.info.template_dropped
        ? `<span class="warn-text">${esc(t.droppedKeys.replace("{n}", this.info.template_dropped))}</span>`
        : "";
      bar.innerHTML = `<ha-icon icon="mdi:link-variant"></ha-icon>
        <span class="link-text">${esc(t.linkedTo.replace("{name}", tpl?.title || "?"))} ${dropped}</span>
        <span class="spacer"></span>
        <button class="btn small" data-role="open-template">${t.openTemplate}</button>
        <button class="btn small" data-role="detach">${t.detach}</button>`;
      return;
    }
    const options = this.templates
      .map((tpl) => `<option value="${esc(tpl.template_id)}">${esc(tpl.title)} (${esc(tpl.model?.name || "?")})</option>`)
      .join("");
    bar.innerHTML = `<ha-icon icon="mdi:link-variant-off"></ha-icon>
      <span class="link-text">${t.ownLayout}</span>
      <span class="spacer"></span>
      ${options ? `<select data-role="link" aria-label="${esc(t.assignTemplate)}"><option value="">${t.assignTemplate}</option>${options}</select>` : ""}
      <button class="btn small" data-role="save-as-template">${t.saveAsTemplate}</button>`;
  }

  _renderStatus() {
    const t = this.t;
    const chip = this.shadowRoot.getElementById("status-chip");
    const text = this.shadowRoot.getElementById("status-text");
    if (!chip || !this.info) return;
    if (this.isTemplate) {
      chip.className = "chip neutral";
      chip.textContent = t.virtual;
    } else {
      const ok = this.info.deck_connected;
      chip.className = `chip ${ok ? "ok" : "bad"}`;
      chip.textContent = ok ? t.connected : t.disconnected;
    }
    text.textContent = this.message || (this.dirty ? t.unsaved : "");
    text.classList.toggle("warn", this.dirty);
  }

  _pageDepth(page) {
    let depth = 0;
    let current = page;
    while (current?.parent && depth < 10) {
      current = this.draft.pages.find((p) => p.id === current.parent);
      depth += 1;
    }
    return depth;
  }

  _renderTabs() {
    const t = this.t;
    const tabs = this.shadowRoot.getElementById("tabs");
    if (!tabs || !this.draft) return;
    const pages = this.draft.pages
      .map((p) => {
        const active = p.id === this.pageId;
        const onDeck = !this.isTemplate && p.id === this.info?.current_page;
        const name = p.id === ROOT_PAGE ? t.root : p.name;
        const icon = p.parent ? `<ha-icon icon="mdi:folder-outline"></ha-icon>` : `<ha-icon icon="mdi:home-outline"></ha-icon>`;
        return `<button class="tab ${active ? "active" : ""}" data-role="page" data-page="${esc(p.id)}" style="--depth:${this._pageDepth(p)}">
          ${icon}<span>${esc(name)}</span>${onDeck ? `<span class="dot" title="${esc(t.shownOnDeck)}"></span>` : ""}
        </button>`;
      })
      .join("");
    const isFolder = this.page && this.page.id !== ROOT_PAGE;
    tabs.innerHTML = `${pages}
      <button class="tab add" data-role="add-folder">${t.newFolder}</button>
      <span class="spacer"></span>
      ${isFolder ? `<button class="btn small" data-role="rename">${t.rename}</button><button class="btn small danger" data-role="delete-page">${t.deletePage}</button>` : ""}
      ${this.isTemplate ? "" : `<button class="btn small" data-role="show">${this.pageId === this.info?.current_page ? t.shownOnDeck : t.showOnDeck}</button>`}`;
  }

  _renderDeck() {
    const deck = this.shadowRoot.getElementById("deck");
    if (!deck) return;
    const model = this.info?.model;
    if (!model) {
      deck.innerHTML = `<div class="empty">${esc(this.t.noDeck)}</div>`;
      return;
    }
    deck.style.setProperty("--cols", model.cols);
    const cells = [];
    for (let i = 0; i < model.key_count; i += 1) {
      const img = this.images[i] ? `<img alt="" src="data:image/jpeg;base64,${this.images[i]}">` : "";
      const key = this._key(i);
      const label = `${this.t.key} ${i + 1}${key?.title ? `: ${key.title}` : ""}`;
      cells.push(
        `<button class="key ${this.selected === i ? "selected" : ""} ${!key && !this._isBackKey(i) ? "blank" : ""}" data-role="key" data-key="${i}" aria-label="${esc(label)}">${img}</button>`
      );
    }
    deck.innerHTML = cells.join("");
  }

  _actionFields(slot, action) {
    const t = this.t;
    const pages = this.draft.pages
      .filter((p) => p.id !== this.pageId)
      .map((p) => `<option value="${esc(p.id)}" ${action.page === p.id ? "selected" : ""}>${esc(p.id === ROOT_PAGE ? t.root : p.name)}</option>`)
      .join("");
    const types = [
      ["none", t.aNone],
      ["default", t.aDefault],
      ["page", t.aPage],
      ["back", t.aBack],
      ["action", t.aCall],
    ]
      .map(([value, label]) => `<option value="${value}" ${action.type === value ? "selected" : ""}>${label}</option>`)
      .join("");
    let extra = "";
    if (action.type === "default") {
      const entity = action.entity_id || this._key(this.selected)?.entity_id;
      const runs = entity ? `${t.runs}: ${defaultService(entity, this._hass.states[entity])}` : t.needsEntity;
      extra = `<div class="field"><span class="field-label">${t.targetEntity}</span>${this._entityField(`${slot}:entity_id`, action.entity_id, t.targetEntityHint)}</div>
        <p class="help">${esc(runs)}</p>`;
    } else if (action.type === "page") {
      extra = `<label>${t.page}<select data-slot="${slot}" data-afield="page"><option value=""></option>${pages}</select></label>`;
    } else if (action.type === "action") {
      extra = `<label>${t.actionName}<input list="sa-services" data-slot="${slot}" data-afield="action" value="${esc(action.action || "")}" placeholder="light.turn_on"></label>
        <label>${t.actionData}<textarea rows="3" data-slot="${slot}" data-afield="data" placeholder='{"entity_id": "light.kueche"}'>${esc(JSON.stringify(action.data || {}, null, 0) === "{}" ? "" : JSON.stringify(action.data))}</textarea></label>`;
    }
    return `<div class="field"><span class="field-label">${slot === "short" ? t.short : t.long}</span>
      <div class="action-row">
        <select data-slot="${slot}" data-afield="type" aria-label="${esc(slot === "short" ? t.short : t.long)}">${types}</select>
        ${this._testButton(slot === "long")}
      </div></div>${extra}`;
  }

  _testButton(long) {
    const t = this.t;
    return `<button type="button" class="btn small test" data-role="test" data-long="${long ? 1 : 0}" title="${esc(t.testHint)}">
      <ha-icon icon="mdi:play"></ha-icon>${t.test}</button>`;
  }

  async _test(long) {
    const t = this.t;
    if (Object.keys(this._jsonErrors).length) {
      this.message = t.invalidJson;
      this._renderStatus();
      return;
    }
    try {
      await this._hass.callWS({
        type: "stream_assistant/press",
        ...this._targetParams,
        key: this.selected,
        long,
        page: this._cleanPage(this.page),
      });
      this.message = `${t.tested}: ${t.key} ${this.selected + 1} · ${long ? t.long : t.short}`;
      if (!this.isTemplate) {
        // A folder/back action switches the deck page
        await this._refreshLists();
        const current = this.entries.find((e) => e.entry_id === this.entryId);
        if (current) this.info.current_page = current.current_page;
        this._renderTabs();
      }
    } catch (err) {
      this.message = String(err?.message || err);
    }
    this._renderStatus();
  }

  _renderForm() {
    const t = this.t;
    const form = this.shadowRoot.getElementById("form");
    if (!form) return;
    const model = this.info?.model;
    if (this.selected === null || !model) {
      form.innerHTML = `<div class="empty">${esc(t.hint)}</div>`;
      return;
    }
    const index = this.selected;
    const position = `${t.row} ${Math.floor(index / model.cols) + 1} · ${t.col} ${(index % model.cols) + 1}`;
    if (this._isBackKey(index)) {
      form.innerHTML = `<h2>${t.key} ${index + 1}</h2><p class="sub">${position}</p><p>${t.backKey}</p>${this._testButton(false)}`;
      return;
    }
    const key = this._key(index) || DEFAULT_KEY();
    const serviceOptions = Object.entries(this._hass.services || {})
      .flatMap(([domain, services]) => Object.keys(services).map((s) => `<option value="${esc(domain)}.${esc(s)}"></option>`))
      .join("");
    const second = key.second_line || "state";
    form.innerHTML = `
      <datalist id="sa-services">${serviceOptions}</datalist>
      <div class="form-head">
        <h2>${t.key} ${index + 1}</h2>
        <span class="sub">${position}</span>
      </div>
      <div class="section">
        <h3>${t.sectionState}</h3>
        <div class="field"><span class="field-label">${t.entity}</span>${this._entityField("key:entity_id", key.entity_id, t.noEntity)}</div>
        <p class="help">${t.entityHint}</p>
      </div>
      <div class="section">
        <h3>${t.sectionLook}</h3>
        <label>${t.titleField}<input data-field="title" maxlength="40" value="${esc(key.title)}" placeholder="${esc(t.titleHint)}"></label>
        <div class="grid2">
          <div class="field"><span class="field-label">${t.iconOn}</span>${this._iconField("key:icon", key.icon)}</div>
          <div class="field"><span class="field-label">${t.iconOff}</span>${this._iconField("key:icon_off", key.icon_off)}</div>
        </div>
        <p class="help">${t.iconAutoHint}</p>
        <label>${t.second}<select data-field="second_line">
          <option value="state" ${second === "state" ? "selected" : ""}>${t.secondState}</option>
          <option value="text" ${second === "text" ? "selected" : ""}>${t.secondText}</option>
          <option value="none" ${second === "none" ? "selected" : ""}>${t.secondNone}</option>
        </select></label>
        ${second === "text" ? `<label>${t.secondTextField}<input data-field="second_text" maxlength="40" value="${esc(key.second_text)}"></label>` : ""}
        <div class="grid3">
          <label>${t.onColor}<input type="color" data-field="on_color" value="${esc(key.on_color)}"></label>
          <label>${t.offColor}<input type="color" data-field="off_color" value="${esc(key.off_color)}"></label>
          <label>${t.textColor}<span class="color-auto"><input type="color" data-field="text_color" value="${esc(key.text_color || "#ffffff")}" ${key.text_color ? "" : "disabled"}>
            <label class="check"><input type="checkbox" data-role="auto-text" ${key.text_color ? "" : "checked"}>${t.autoText}</label></span></label>
        </div>
      </div>
      <div class="section">
        <h3>${t.sectionActions}</h3>
        ${this._actionFields("short", key.short)}
        ${this._actionFields("long", key.long)}
      </div>
      <div class="form-foot">
        <button class="btn danger" data-role="clear-key">${t.clearKey}</button>
      </div>`;
    this._hydrateStateIcons(form);
  }

  // Pickers

  _getTarget(target) {
    const [scope, field] = target.split(":");
    const key = this._key(this.selected) || DEFAULT_KEY();
    return scope === "key" ? key[field] : key[scope]?.[field];
  }

  _setTarget(target, value) {
    const [scope, field] = target.split(":");
    const key = this._ensureKey(this.selected);
    if (scope === "key") key[field] = value || null;
    else key[scope][field] = value || null;
    // A new key with an entity should do the obvious thing right away
    if (scope === "key" && field === "entity_id" && value && key.short.type === "none") {
      key.short = { type: "default" };
    }
    this._changed();
    this._renderForm();
  }

  _entityInfo(entityId) {
    const hass = this._hass;
    const state = hass.states[entityId];
    const reg = hass.entities?.[entityId];
    const device = reg?.device_id ? hass.devices?.[reg.device_id] : undefined;
    const areaId = reg?.area_id || device?.area_id || null;
    return {
      id: entityId,
      state,
      name: state?.attributes.friendly_name || reg?.name || entityId,
      domain: entityId.split(".")[0],
      areaId,
      area: areaId ? hass.areas?.[areaId]?.name || areaId : "",
      deviceId: reg?.device_id || null,
      device: device ? device.name_by_user || device.name || "" : "",
      hidden: Boolean(reg?.hidden || reg?.entity_category),
    };
  }

  _stateText(state) {
    if (!state) return "";
    try {
      if (this._hass.formatEntityState) return this._hass.formatEntityState(state);
    } catch (_err) {
      // fall through
    }
    return state.state;
  }

  _entityField(target, entityId, emptyText) {
    const t = this.t;
    const info = entityId ? this._entityInfo(entityId) : null;
    const body = info
      ? `<ha-state-icon data-entity="${esc(info.id)}"></ha-state-icon>
         <span class="pick-text"><span class="pick-main">${esc(info.name)}</span><span class="pick-sub">${esc([info.area, info.id].filter(Boolean).join(" · "))}</span></span>`
      : `<span class="pick-text"><span class="pick-sub">${esc(emptyText)}</span></span>`;
    return `<div class="pick">
      <button type="button" class="pick-btn" data-role="pick-entity" data-target="${target}" aria-label="${esc(t.pickEntity)}">${body}</button>
      ${info ? `<button type="button" class="icon-btn" data-role="pick-clear" data-target="${target}" aria-label="${esc(t.remove)}"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}
    </div>`;
  }

  _iconField(target, icon) {
    const t = this.t;
    return `<div class="pick">
      <button type="button" class="pick-btn" data-role="pick-icon" data-target="${target}" aria-label="${esc(t.pickIcon)}">
        ${icon ? `<ha-icon icon="${esc(icon)}"></ha-icon>` : `<ha-icon class="muted" icon="mdi:auto-fix"></ha-icon>`}
        <span class="pick-text"><span class="${icon ? "pick-main" : "pick-sub"}">${esc(icon ? icon.slice(4) : t.autoIcon)}</span></span>
      </button>
      ${icon ? `<button type="button" class="icon-btn" data-role="pick-clear" data-target="${target}" aria-label="${esc(t.remove)}"><ha-icon icon="mdi:close"></ha-icon></button>` : ""}
    </div>`;
  }

  // ha-state-icon needs real properties, not attributes
  _hydrateStateIcons(root) {
    const defined = customElements.get("ha-state-icon");
    for (const el of root.querySelectorAll("ha-state-icon[data-entity]")) {
      const state = this._hass.states[el.dataset.entity];
      if (defined && state) {
        el.hass = this._hass;
        el.stateObj = state;
      } else {
        const fallback = document.createElement("ha-icon");
        fallback.icon = state?.attributes.icon || "mdi:shape-outline";
        el.replaceWith(fallback);
      }
    }
  }

  _openEntityPicker(target) {
    const t = this.t;
    this._picker = { kind: "entity", target, search: "", area: "", device: "", domain: "", all: false };
    const infos = Object.keys(this._hass.states).map((id) => this._entityInfo(id));
    this._pickerEntities = infos;
    const areas = Object.values(this._hass.areas || {}).sort((a, b) => a.name.localeCompare(b.name));
    const domains = [...new Set(infos.map((i) => i.domain))].sort();
    const dlg = this.shadowRoot.getElementById("picker");
    dlg.innerHTML = `
      <div class="dlg-head"><h2>${t.pickEntity}</h2><button type="button" class="icon-btn" data-role="pk-close" aria-label="${esc(t.close)}"><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="filters">
        <input type="search" id="pk-search" placeholder="${esc(t.search)}" aria-label="${esc(t.search)}">
        <select id="pk-area" aria-label="${esc(t.allAreas)}"><option value="">${t.allAreas}</option>
          ${areas.map((a) => `<option value="${esc(a.area_id)}">${esc(a.name)}</option>`).join("")}
          <option value="__none">${t.noArea}</option></select>
        <select id="pk-device" aria-label="${esc(t.allDevices)}"></select>
        <select id="pk-domain" aria-label="${esc(t.allTypes)}"><option value="">${t.allTypes}</option>
          ${domains.map((d) => `<option value="${esc(d)}">${esc(DOMAIN_NAMES[this._lang]?.[d] || d)}</option>`).join("")}</select>
        <label class="check"><input type="checkbox" id="pk-all">${t.showHidden}</label>
      </div>
      <div class="pk-list" id="pk-list"></div>
      <div class="dlg-foot"><button type="button" class="btn" data-role="pk-none">${t.noEntity}</button></div>`;
    this._renderDeviceOptions();
    this._renderEntityList();
    dlg.showModal();
    this.shadowRoot.getElementById("pk-search").focus();
  }

  get _lang() {
    return (this._hass?.locale?.language || this._hass?.language || "en").slice(0, 2) === "de" ? "de" : "en";
  }

  _renderDeviceOptions() {
    const t = this.t;
    const p = this._picker;
    const devices = new Map();
    for (const info of this._pickerEntities) {
      if (!info.deviceId || (p.area && (p.area === "__none" ? info.areaId : info.areaId !== p.area))) continue;
      devices.set(info.deviceId, info.device);
    }
    const sorted = [...devices.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    if (p.device && !devices.has(p.device)) p.device = "";
    this.shadowRoot.getElementById("pk-device").innerHTML =
      `<option value="">${t.allDevices}</option>` +
      sorted.map(([id, name]) => `<option value="${esc(id)}" ${id === p.device ? "selected" : ""}>${esc(name || id)}</option>`).join("");
  }

  _renderEntityList() {
    const t = this.t;
    const p = this._picker;
    const words = p.search.toLowerCase().split(/\s+/).filter(Boolean);
    const matches = this._pickerEntities
      .filter((i) => p.all || !i.hidden)
      .filter((i) => !p.area || (p.area === "__none" ? !i.areaId : i.areaId === p.area))
      .filter((i) => !p.device || i.deviceId === p.device)
      .filter((i) => !p.domain || i.domain === p.domain)
      .filter((i) => {
        const hay = `${i.name} ${i.id} ${i.area} ${i.device}`.toLowerCase();
        return words.every((w) => hay.includes(w));
      })
      .sort((a, b) => (a.area || "~").localeCompare(b.area || "~") || a.name.localeCompare(b.name));
    const limit = 250;
    let html = "";
    let lastArea = null;
    for (const i of matches.slice(0, limit)) {
      if (i.area !== lastArea) {
        html += `<div class="pk-group">${esc(i.area || t.noArea)}</div>`;
        lastArea = i.area;
      }
      html += `<button type="button" class="pk-row" data-role="pk-pick" data-entity="${esc(i.id)}">
        <ha-state-icon data-entity="${esc(i.id)}"></ha-state-icon>
        <span class="pick-text"><span class="pick-main">${esc(i.name)}</span><span class="pick-sub">${esc([i.device, i.id].filter(Boolean).join(" · "))}</span></span>
        <span class="pk-state">${esc(this._stateText(i.state))}</span>
      </button>`;
    }
    if (!matches.length) html = `<p class="empty">${t.noResults}</p>`;
    else if (matches.length > limit) html += `<p class="help">${t.moreResults}</p>`;
    const list = this.shadowRoot.getElementById("pk-list");
    list.innerHTML = html;
    this._hydrateStateIcons(list);
  }

  _iconSuggestions() {
    const key = this._key(this.selected);
    const domain = key?.entity_id?.split(".")[0];
    return [...(ICON_SUGGESTIONS[domain] || []), ...ICON_SUGGESTIONS._common];
  }

  _openIconPicker(target) {
    const t = this.t;
    this._picker = { kind: "icon", target, search: "" };
    const dlg = this.shadowRoot.getElementById("picker");
    dlg.innerHTML = `
      <div class="dlg-head"><h2>${t.pickIcon}</h2><button type="button" class="icon-btn" data-role="pk-close" aria-label="${esc(t.close)}"><ha-icon icon="mdi:close"></ha-icon></button></div>
      <div class="filters"><input type="search" id="ic-search" placeholder="${esc(t.iconSearch)}" aria-label="${esc(t.iconSearch)}"></div>
      <div class="ic-grid" id="ic-grid"></div>
      <div class="dlg-foot"><button type="button" class="btn" data-role="ic-auto">${t.autoIcon}</button></div>`;
    this._renderIconGrid();
    dlg.showModal();
    this.shadowRoot.getElementById("ic-search").focus();
  }

  _renderIconGrid() {
    const t = this.t;
    const words = this._picker.search.toLowerCase().split(/[\s,]+/).filter(Boolean);
    let names;
    let heading = "";
    if (!words.length) {
      names = [...new Set(this._iconSuggestions())].filter((n) => this.icons.includes(n));
      heading = `<div class="pk-group ic-head">${t.suggestions}</div>`;
    } else {
      names = this.icons
        .filter((n) => words.every((w) => n.includes(w)))
        .sort((a, b) => Number(!a.startsWith(words[0])) - Number(!b.startsWith(words[0])) || a.length - b.length);
    }
    const limit = 180;
    const current = this._getTarget(this._picker.target);
    const grid = this.shadowRoot.getElementById("ic-grid");
    grid.innerHTML =
      heading +
      (names.length
        ? names
            .slice(0, limit)
            .map(
              (n) => `<button type="button" class="ic-cell ${current === `mdi:${n}` ? "selected" : ""}" data-role="ic-pick" data-icon="mdi:${esc(n)}" title="${esc(n)}">
                <ha-icon icon="mdi:${esc(n)}"></ha-icon><span>${esc(n)}</span></button>`
            )
            .join("")
        : `<p class="empty">${t.noResults}</p>`) +
      (names.length > limit ? `<p class="help ic-head">${t.moreResults}</p>` : "");
  }

  _closePicker() {
    this.shadowRoot.getElementById("picker")?.close();
    this._picker = null;
  }

  // Events

  _onClick(ev) {
    const target = ev.target.closest("[data-role]");
    if (!target) {
      // Click on the dialog backdrop closes it
      if (ev.target.id === "picker") this._closePicker();
      return;
    }
    const role = target.dataset.role;
    if (role === "test") {
      this._test(target.dataset.long === "1");
    } else if (role === "view") {
      // Leaving the info view drops unsaved behaviour; leaving the keys keeps the key draft
      const leavingInfo = this.view === "info";
      if (this.view !== target.dataset.view && (!leavingInfo || !this.behaviorDirty || confirm(this.t.leaveUnsaved))) {
        this._showView(target.dataset.view);
      }
    } else if (role === "save-behavior") {
      this._saveBehavior();
    } else if (role === "new-template") {
      this._openTemplateDialog();
    } else if (role === "tpl-create") {
      this._createTemplate();
    } else if (role === "save-as-template") {
      this._saveAsTemplate();
    } else if (role === "open-template") {
      if (this._confirmLeave()) this._loadTarget("template", this.info.template_id);
    } else if (role === "detach") {
      this._detach();
    } else if (role === "rename-template") {
      this._renameTemplate();
    } else if (role === "delete-template") {
      this._deleteTemplate();
    } else if (role === "pick-entity") {
      this._openEntityPicker(target.dataset.target);
    } else if (role === "pick-icon") {
      this._openIconPicker(target.dataset.target);
    } else if (role === "pick-clear") {
      this._setTarget(target.dataset.target, null);
    } else if (role === "pk-close") {
      this._closePicker();
    } else if (role === "pk-pick" || role === "pk-none") {
      const { target: field } = this._picker;
      this._closePicker();
      this._setTarget(field, role === "pk-pick" ? target.dataset.entity : null);
    } else if (role === "ic-pick" || role === "ic-auto") {
      const { target: field } = this._picker;
      this._closePicker();
      this._setTarget(field, role === "ic-pick" ? target.dataset.icon : null);
    } else if (role === "key") {
      this.selected = Number(target.dataset.key);
      this._renderDeck();
      this._renderForm();
    } else if (role === "page") {
      this.pageId = target.dataset.page;
      this.selected = null;
      this.images = [];
      this._renderTabs();
      this._renderDeck();
      this._renderForm();
      this._schedulePreview(0);
    } else if (role === "add-folder") {
      this._addFolder();
    } else if (role === "rename") {
      this._renamePage();
    } else if (role === "delete-page") {
      this._deletePage();
    } else if (role === "show") {
      this._showOnDeck();
    } else if (role === "save") {
      this._save();
    } else if (role === "discard") {
      this._discard();
    } else if (role === "clear-key") {
      delete this.page.keys[String(this.selected)];
      this._changed();
      this._renderDeck();
      this._renderForm();
    }
  }

  _onInput(ev) {
    const el = ev.target;
    if (el.dataset.bfield && el.type !== "checkbox" && el.tagName !== "SELECT") {
      this._onBehaviorInput(el);
      return;
    }
    if (el.id === "pk-search" && this._picker) {
      this._picker.search = el.value;
      this._renderEntityList();
      return;
    }
    if (el.id === "ic-search" && this._picker) {
      this._picker.search = el.value;
      this._renderIconGrid();
      return;
    }
    if (el.dataset.field && this.selected !== null) {
      const key = this._ensureKey(this.selected);
      key[el.dataset.field] = el.value;
      if (el.dataset.field === "icon") {
        const preview = this.shadowRoot.getElementById("icon-preview");
        if (preview) preview.icon = el.value || "mdi:help-box-outline";
      }
      this._changed();
    } else if (el.dataset.slot && el.dataset.afield !== "type" && el.dataset.afield !== "page") {
      const key = this._ensureKey(this.selected);
      const action = key[el.dataset.slot];
      if (el.dataset.afield === "data") {
        const errorKey = `${el.dataset.slot}`;
        try {
          action.data = el.value.trim() ? JSON.parse(el.value) : {};
          delete this._jsonErrors[errorKey];
          el.classList.remove("invalid");
        } catch (_err) {
          this._jsonErrors[errorKey] = true;
          el.classList.add("invalid");
        }
      } else {
        action[el.dataset.afield] = el.value;
      }
      this._changed();
    }
  }

  _onChange(ev) {
    const el = ev.target;
    if (el.dataset.bfield && (el.type === "checkbox" || el.tagName === "SELECT")) {
      this._onBehaviorInput(el);
      // The redraw fills every field from the (valid) draft again
      this._behaviorErrors.clear();
      this._renderAll();
      return;
    }
    if (this._picker?.kind === "entity" && ["pk-area", "pk-device", "pk-domain", "pk-all"].includes(el.id)) {
      const p = this._picker;
      if (el.id === "pk-area") {
        p.area = el.value;
        this._renderDeviceOptions();
      } else if (el.id === "pk-device") p.device = el.value;
      else if (el.id === "pk-domain") p.domain = el.value;
      else p.all = el.checked;
      this._renderEntityList();
      return;
    }
    if (el.dataset.role === "entry") {
      const [kind, ...rest] = el.value.split(":");
      if (this._confirmLeave()) this._loadTarget(kind, rest.join(":"));
      else this._renderAll();
    } else if (el.dataset.role === "link") {
      this._link(el.value);
    } else if (el.dataset.role === "auto-text") {
      const key = this._ensureKey(this.selected);
      key.text_color = el.checked ? null : "#ffffff";
      this._changed();
      this._renderForm();
    } else if (el.dataset.field === "second_line") {
      this._renderForm();
    } else if (el.dataset.slot && (el.dataset.afield === "type" || el.dataset.afield === "page")) {
      const key = this._ensureKey(this.selected);
      if (el.dataset.afield === "type") {
        key[el.dataset.slot] = { type: el.value };
        delete this._jsonErrors[el.dataset.slot];
      } else {
        key[el.dataset.slot].page = el.value;
      }
      this._changed();
      this._renderForm();
    }
  }
}

const STYLE = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display: flex; align-items: center; height: var(--header-height, 56px); padding: 0 12px; background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); border-bottom: var(--app-header-border-bottom, none); box-sizing: border-box; }
  .main-title { margin-left: 12px; font-size: 20px; }
  .content { padding: 16px; max-width: 1400px; margin: 0 auto; box-sizing: border-box; }
  .card { background: var(--card-background-color, #fff); border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--divider-color, #e0e0e0); box-sizing: border-box; }
  .empty { padding: 24px; color: var(--secondary-text-color); }
  .topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 16px; }
  .spacer { flex: 1 1 auto; }
  .inline { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: var(--secondary-text-color); }
  select, input, textarea { font: inherit; font-size: 14px; color: var(--primary-text-color); background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #ccc); border-radius: 8px; padding: 8px 10px; min-height: 40px; box-sizing: border-box; width: 100%; }
  .inline select { width: auto; }
  textarea { min-height: 64px; resize: vertical; font-family: monospace; }
  input[type=color] { padding: 2px; height: 40px; cursor: pointer; }
  input:disabled { opacity: 0.4; }
  .invalid { border-color: var(--error-color, #db4437); }
  .chip { padding: 4px 12px; border-radius: 999px; font-size: 13px; font-weight: 500; }
  .chip.ok { background: rgba(67, 160, 71, 0.15); color: var(--success-color, #2e7d32); }
  .chip.bad { background: rgba(219, 68, 55, 0.15); color: var(--error-color, #c62828); }
  .status-text { font-size: 13px; color: var(--secondary-text-color); }
  .status-text.warn { color: var(--warning-color, #e65100); }
  .btn { height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); background: transparent; color: var(--primary-text-color); font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; }
  .btn.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: var(--primary-color); }
  .btn.danger { color: var(--error-color, #c62828); }
  .btn.small { height: 36px; padding: 0 12px; font-size: 13px; }
  .layout { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-start; }
  .left { flex: 999 1 560px; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
  .right { flex: 1 1 360px; min-width: 0; padding: 16px 20px; }
  .tabs { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .tab { display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 14px; margin-left: calc(var(--depth, 0) * 4px); border-radius: 8px; border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color, #fff); color: var(--primary-text-color); font: inherit; font-size: 14px; cursor: pointer; }
  .tab ha-icon { --mdc-icon-size: 18px; }
  .tab.active { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .tab.add { border-style: dashed; color: var(--secondary-text-color); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success-color, #43a047); }
  .deck-card { padding: 24px; display: flex; flex-direction: column; align-items: center; gap: 12px; }
  .deck { display: grid; grid-template-columns: repeat(var(--cols, 5), minmax(0, 96px)); gap: 12px; padding: 20px; background: #17181a; border-radius: 22px; max-width: 100%; box-sizing: border-box; }
  .key { width: 100%; aspect-ratio: 1; padding: 0; border: 2px solid transparent; border-radius: 12px; background: #000; overflow: hidden; cursor: pointer; outline-offset: 3px; }
  .key img { width: 100%; height: 100%; display: block; }
  .key.blank { border: 2px dashed #4a4d52; }
  .key.selected { outline: 3px solid var(--primary-color); }
  .key:focus-visible { outline: 3px solid var(--accent-color, #ff9800); }
  .hint { margin: 0; font-size: 13px; color: var(--secondary-text-color); text-align: center; }
  .form-head { display: flex; align-items: baseline; gap: 12px; }
  h2 { margin: 0; font-size: 18px; font-weight: 500; }
  .sub { font-size: 13px; color: var(--secondary-text-color); }
  .section { display: flex; flex-direction: column; gap: 10px; margin-top: 18px; }
  h3 { margin: 0; font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
  label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--secondary-text-color); }
  label.check { flex-direction: row; align-items: center; gap: 6px; }
  label.check input { width: auto; min-height: 0; }
  .help { margin: -4px 0 0; font-size: 12px; color: var(--secondary-text-color); }
  .grid2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
  .icon-input { display: flex; align-items: center; gap: 8px; }
  .color-auto { display: flex; align-items: center; gap: 8px; }
  .form-foot { display: flex; justify-content: flex-end; margin-top: 20px; }
  .header-views { display: flex; align-self: stretch; margin-left: auto; gap: 4px; }
  .header-tab { display: inline-flex; align-items: center; gap: 6px; padding: 0 14px; border: none; border-bottom: 2px solid transparent; background: transparent; color: inherit; opacity: 0.75; font: inherit; font-size: 14px; font-weight: 500; cursor: pointer; }
  .header-tab ha-icon { --mdc-icon-size: 20px; }
  .header-tab:hover { opacity: 1; }
  .header-tab.active { opacity: 1; border-bottom-color: currentColor; }
  @media (max-width: 600px) { .header-tab span { display: none; } }
  .info-card { flex: 1 1 420px; min-width: 0; padding: 16px 20px; }
  .facts { display: grid; grid-template-columns: minmax(140px, max-content) minmax(0, 1fr); gap: 6px 16px; margin: 12px 0 0; font-size: 14px; }
  .facts dt { color: var(--secondary-text-color); }
  .facts dd { margin: 0; overflow-wrap: anywhere; }
  .facts .fact-group { grid-column: 1 / -1; margin-top: 10px; font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--primary-text-color); }
  .toggle { font-size: 15px; color: var(--primary-text-color); font-weight: 500; }
  .disabled { opacity: 0.5; }
  .linkbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 16px; margin-bottom: 16px; font-size: 14px; }
  .linkbar ha-icon { color: var(--secondary-text-color); }
  .linkbar select { width: auto; }
  .link-text { min-width: 0; }
  .warn-text { color: var(--warning-color, #e65100); margin-left: 6px; }
  .chip.neutral { background: var(--secondary-background-color, rgba(0,0,0,0.06)); color: var(--secondary-text-color); }
  .dlg-body { display: flex; flex-direction: column; gap: 12px; padding: 8px 24px 16px; }
  .action-row { display: flex; gap: 8px; align-items: center; }
  .action-row select { flex: 1 1 auto; min-width: 0; }
  .btn.test { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 4px; height: 40px; }
  .btn.test ha-icon { --mdc-icon-size: 18px; }
  .field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .field-label { font-size: 13px; color: var(--secondary-text-color); }
  .pick { display: flex; align-items: center; gap: 4px; min-width: 0; }
  .pick-btn { flex: 1 1 auto; min-width: 0; display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 6px 10px; border: 1px solid var(--divider-color, #ccc); border-radius: 8px; background: var(--card-background-color, #fff); color: var(--primary-text-color); font: inherit; text-align: left; cursor: pointer; }
  .pick-btn:hover { border-color: var(--primary-color); }
  .pick-text { display: flex; flex-direction: column; min-width: 0; }
  .pick-main { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pick-sub { font-size: 12px; color: var(--secondary-text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .muted { color: var(--secondary-text-color); }
  .icon-btn { width: 40px; height: 40px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border: none; border-radius: 50%; background: transparent; color: var(--secondary-text-color); cursor: pointer; }
  .icon-btn:hover { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
  .dlg { width: min(720px, calc(100vw - 32px)); max-height: calc(100vh - 64px); padding: 0; border: none; border-radius: var(--ha-dialog-border-radius, 16px); background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 8px 32px rgba(0,0,0,0.3); }
  .dlg[open] { display: flex; flex-direction: column; }
  .dlg::backdrop { background: rgba(0, 0, 0, 0.45); }
  .dlg-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 16px 8px 24px; }
  .filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 24px 12px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
  .filters input[type=search] { flex: 1 1 100%; }
  .filters select { flex: 1 1 160px; width: auto; }
  .pk-list, .ic-grid { overflow-y: auto; padding: 8px 16px 16px; min-height: 200px; }
  .pk-group { padding: 12px 8px 4px; font-size: 12px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--secondary-text-color); }
  .pk-row { width: 100%; display: flex; align-items: center; gap: 12px; min-height: 48px; padding: 4px 8px; border: none; border-radius: 8px; background: transparent; color: var(--primary-text-color); font: inherit; text-align: left; cursor: pointer; }
  .pk-row:hover, .pk-row:focus-visible { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
  .pk-row .pick-text { flex: 1 1 auto; }
  .pk-state { flex: 0 0 auto; font-size: 13px; color: var(--secondary-text-color); max-width: 35%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ic-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 6px; align-content: start; }
  .ic-head { grid-column: 1 / -1; }
  .ic-cell { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 4px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--primary-text-color); font: inherit; cursor: pointer; }
  .ic-cell:hover, .ic-cell:focus-visible { background: var(--secondary-background-color, rgba(0,0,0,0.06)); }
  .ic-cell.selected { border-color: var(--primary-color); }
  .ic-cell ha-icon { --mdc-icon-size: 28px; }
  .ic-cell span { font-size: 11px; color: var(--secondary-text-color); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dlg-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 24px 16px; border-top: 1px solid var(--divider-color, #e0e0e0); }
  @media (max-width: 600px) { .grid2, .grid3 { grid-template-columns: minmax(0, 1fr); } .content { padding: 8px; } }
`;

// An open tab keeps the old version until it is reloaded; defining twice would throw
if (!customElements.get("stream-assistant-panel")) {
  customElements.define("stream-assistant-panel", StreamAssistantPanel);
}
