// A pretend Home Assistant for documentation screenshots of the editor and the card.
// URL parameters: deck=mk2|plus|neo|studio, select=<key>|d<dial>, view=keys|info,
// dialog=template|entity|icon, page=<page id>, lang=en|de

const params = new URLSearchParams(location.search);
const lang = params.get("lang") || "en";

// ha-icon / ha-state-icon: draw MDI icons with the integration's bundled font
const mdiReady = fetch("mdi.json").then((r) => r.json());
class FakeIcon extends HTMLElement {
  static get observedAttributes() { return ["icon"]; }
  set icon(value) { this._icon = value; this._draw(); }
  get icon() { return this._icon; }
  set stateObj(state) { this._icon = state?.attributes?.icon || "mdi:shape-outline"; this._draw(); }
  set hass(_v) {}
  attributeChangedCallback() { this._icon = this.getAttribute("icon"); this._draw(); }
  connectedCallback() { this._draw(); }
  async _draw() {
    const codes = await mdiReady;
    const name = (this._icon || this.getAttribute("icon") || "").replace("mdi:", "");
    const code = codes[name];
    this.style.display = "inline-flex";
    this.style.alignItems = "center";
    this.style.justifyContent = "center";
    this.style.width = "var(--mdc-icon-size, 24px)";
    this.style.height = "var(--mdc-icon-size, 24px)";
    this.style.fontFamily = "mdi";
    this.style.fontSize = "var(--mdc-icon-size, 24px)";
    this.style.lineHeight = "1";
    this.textContent = code ? String.fromCodePoint(code) : "";
  }
}
customElements.define("ha-icon", FakeIcon);
customElements.define("ha-state-icon", class extends FakeIcon {});

const MODELS = {
  mk2: { id: "mk2", name: "Stream Deck MK.2", cols: 5, rows: 3, key_count: 15, key_size: 72, dials: 0, touch_width: 0, touch_height: 0 },
  plus: { id: "grid_4x2_d4", name: "Stream Deck +", cols: 4, rows: 2, key_count: 8, key_size: 120, dials: 4, touch_width: 800, touch_height: 100 },
  neo: { id: "grid_4x2", name: "Stream Deck Neo", cols: 4, rows: 2, key_count: 8, key_size: 96, dials: 0, touch_width: 0, touch_height: 0 },
  studio: { id: "grid_16x2_d2", name: "Stream Deck Studio", cols: 16, rows: 2, key_count: 32, key_size: 112, dials: 2, touch_width: 0, touch_height: 0 },
  panel: { id: "grid_4x3", name: "4 × 3", cols: 4, rows: 3, key_count: 12, key_size: 144, dials: 0, touch_width: 0, touch_height: 0 },
};
const ENTRIES = [
  { entry_id: "dock", deck: "mk2", title: "Stream Deck MK.2 (Living room)", kind: "dock", host: "192.168.1.40" },
  { entry_id: "bridge.plus", deck: "plus", title: "Stream Deck + (Office)", kind: "bridge", host: "192.168.1.20:5390" },
  { entry_id: "bridge.neo", deck: "neo", title: "Stream Deck Neo (Kitchen)", kind: "bridge", host: "192.168.1.20:5390" },
  { entry_id: "bridge.studio", deck: "studio", title: "Stream Deck Studio (Studio)", kind: "bridge", host: "192.168.1.20:5390" },
  { entry_id: "panel", deck: "panel", title: "Hallway tablet", kind: "virtual", host: null },
].map((e) => ({
  ...e,
  virtual: e.kind === "virtual",
  model: MODELS[e.deck],
  dock_connected: true,
  deck_connected: true,
  current_page: "main",
  template_id: null,
  template_dropped: 0,
}));
const TEMPLATES = [{ template_id: "tpl1", title: "Living room", model: MODELS.mk2, linked: ["Stream Deck MK.2 (Living room)"] }];

const state = (id, value, attributes) => ({ entity_id: id, state: value, attributes, last_updated: "1", last_changed: "1", context: {} });
const STATES = Object.fromEntries([
  state("light.living_room", "on", { friendly_name: "Living room", brightness: 166, icon: "mdi:lightbulb-on" }),
  state("light.kitchen", "off", { friendly_name: "Kitchen", icon: "mdi:lightbulb-outline" }),
  state("cover.blinds", "open", { friendly_name: "Blinds", current_position: 40, icon: "mdi:window-shutter-open" }),
  state("scene.movie", "scening", { friendly_name: "Movie", icon: "mdi:movie-open" }),
  state("media_player.radio", "playing", { friendly_name: "Radio", volume_level: 0.3, icon: "mdi:speaker" }),
  state("climate.living_room", "heat", { friendly_name: "Heating", temperature: 21.5, icon: "mdi:thermostat" }),
  state("lock.front_door", "locked", { friendly_name: "Front door", icon: "mdi:lock" }),
  state("cover.garage", "closed", { friendly_name: "Garage", icon: "mdi:garage" }),
  state("fan.office", "on", { friendly_name: "Fan", percentage: 50, icon: "mdi:fan" }),
  state("switch.coffee", "off", { friendly_name: "Coffee machine", icon: "mdi:coffee" }),
  state("sensor.washer", "done", { friendly_name: "Washer", icon: "mdi:washing-machine" }),
  state("sensor.outside", "14.2", { friendly_name: "Outside", unit_of_measurement: "°C", icon: "mdi:thermometer" }),
  state("script.good_night", "off", { friendly_name: "Good night", icon: "mdi:weather-night" }),
  state("alarm_control_panel.home", "armed_home", { friendly_name: "Alarm", icon: "mdi:shield-home" }),
].map((s) => [s.entity_id, s]));
const AREAS = { living: { area_id: "living", name: "Living room" }, kitchen: { area_id: "kitchen", name: "Kitchen" }, outside: { area_id: "outside", name: "Outside" } };
const ENTITIES = {
  "light.living_room": { area_id: "living" }, "climate.living_room": { area_id: "living" }, "media_player.radio": { area_id: "living" },
  "scene.movie": { area_id: "living" }, "cover.blinds": { area_id: "living" }, "light.kitchen": { area_id: "kitchen" },
  "switch.coffee": { area_id: "kitchen" }, "cover.garage": { area_id: "outside" }, "lock.front_door": { area_id: "outside" },
  "sensor.outside": { area_id: "outside" },
};

const KEY_ENTITIES = ["light.living_room", "light.kitchen", "cover.blinds", "scene.movie", "media_player.radio", "climate.living_room",
  "lock.front_door", "cover.garage", "fan.office", null, "switch.coffee", "sensor.washer", "sensor.outside", "script.good_night", "alarm_control_panel.home"];
const COLORS = ["#f2b134", "#f2b134", "#2f6fb0", "#6b4aa8", "#1e6b4a", "#a8432f", "#2f6fb0", "#2f6fb0", "#2f6fb0", "#3a3a3a", "#8a5a2b", "#1e6b4a", "#3a3a3a", "#6b4aa8", "#a8432f"];

function layoutFor(model) {
  const keys = {};
  for (let i = 0; i < model.key_count; i += 1) {
    const n = i % KEY_ENTITIES.length;
    keys[String(i)] = {
      title: n === 9 ? "Lights" : "", icon: n === 9 ? "mdi:folder-outline" : null, icon_off: null,
      entity_id: KEY_ENTITIES[n], second_line: "state", second_text: "",
      on_color: COLORS[n], off_color: "#2b2b2b", text_color: null, font_size: null, image: null,
      short: n === 9 ? { type: "page", page: "lights" } : KEY_ENTITIES[n] ? { type: "default" } : { type: "none" },
      long: n === 0 ? { type: "action", action: "light.turn_on", data: { entity_id: "light.living_room", brightness_pct: 100 }, target: {} } : { type: "none" },
    };
  }
  const dialEntities = ["light.living_room", "media_player.radio", "cover.blinds", "climate.living_room"];
  const dials = {};
  for (let i = 0; i < model.dials; i += 1) {
    dials[String(i)] = {
      title: "", icon: null, icon_off: null, entity_id: dialEntities[i % 4], second_line: "state", second_text: "",
      on_color: COLORS[[0, 4, 2, 5][i % 4]], off_color: "#2b2b2b", text_color: null, font_size: null, image: null,
      short: { type: "default" }, long: { type: "none" }, rotate: "adjust", step: i === 0 ? 10 : null,
      left: { type: "none" }, right: { type: "none" },
    };
  }
  return {
    pages: [
      { id: "main", name: "Home", parent: null, keys, dials },
      { id: "lights", name: "Lights", parent: "main", keys: {}, dials: {} },
      { id: "media", name: "Media", parent: "main", keys: {}, dials: {} },
    ],
  };
}

const INFO = {
  kind: "dock",
  virtual: false,
  dock: { name: null, serial: "A00XA4302KN7G", firmware: "1.01.013", host: "192.168.1.40", mac: "a4:c1:38:1e:22:7f", connected: true },
  deck: { model: "Stream Deck MK.2", serial: "AL21K2C04711", firmware: "1.02.000", connected: true, connected_since: new Date(Date.now() - 3 * 3600e3).toISOString(), key_count: 15, dial_count: 0 },
  brightness: { base: 70, current: 70, night_active: false, dimmed: false, dims_at: new Date(Date.now() + 40e3).toISOString() },
  layout: { template_id: null, pages: 3, folders: 2, keys: 15, current_page: "main" },
  behavior: {
    night: { enabled: true, mode: "sun", start: "22:00", end: "07:00", brightness: 15 },
    idle: { enabled: true, timeout: 120, brightness: 0, wake_only: true, when: "night", start: "22:00", end: "07:00" },
  },
};

window.fakeHass = {
  language: lang,
  locale: { language: lang },
  states: STATES,
  entities: ENTITIES,
  devices: {},
  areas: AREAS,
  services: { light: { turn_on: {}, toggle: {} }, script: { turn_on: {} }, scene: { turn_on: {} } },
  formatEntityState: (s) => s.state,
  connection: {
    subscribeMessage(callback, msg) {
      const images = Object.fromEntries(window.SA_IMAGES.panel.keys.map((img, i) => [String(i), img]));
      setTimeout(() => callback({ title: "Hallway tablet", cols: 4, rows: 3, brightness: 100, images }), 50);
      return Promise.resolve(() => {});
    },
  },
  async callWS(msg) {
    const target = ENTRIES.find((e) => e.entry_id === msg.entry_id) || ENTRIES[0];
    switch (msg.type) {
      case "stream_assistant/entries": return { entries: ENTRIES, templates: TEMPLATES };
      case "stream_assistant/icons": return Object.keys(await mdiReady);
      case "stream_assistant/models": return Object.values(MODELS).filter((m) => !m.id.startsWith("grid"));
      case "stream_assistant/layout/get": return { ...target, layout: layoutFor(target.model), revision: "r1" };
      case "stream_assistant/preview": {
        const set = window.SA_IMAGES[target.deck];
        return { images: msg.page?.id === "main" ? set.keys : [], dials: msg.page?.id === "main" ? set.dials : [] };
      }
      case "stream_assistant/info": return INFO;
      case "stream_assistant/panel/list": return [{ entry_id: "panel", title: "Hallway tablet", cols: 4, rows: 3 }];
      default: return {};
    }
  },
};
