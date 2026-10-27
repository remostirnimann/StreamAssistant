// Stream Assistant: dashboard card for virtual panels.
// Shows the key images Home Assistant renders and reports presses; holding a
// key is a long press, exactly like on a real Stream Deck.

const CARD_TYPE = "stream-assistant-card";
const RETRY_MS = 5000;
const RESUBSCRIBE_MS = 1500;

const TEXTS = {
  de: {
    name: "Stream Assistant Panel",
    description: "Virtuelles Stream Deck: Tasten anzeigen und drücken.",
    noPanel: "Kein virtuelles Panel gewählt.",
    unavailable: "Panel nicht verfügbar.",
    panel: "Panel",
    noPanels: "Noch kein virtuelles Panel. Füge es unter Einstellungen → Geräte & Dienste → Stream Assistant hinzu.",
    showTitle: "Titel anzeigen",
    gap: "Abstand zwischen Tasten (px)",
  },
  en: {
    name: "Stream Assistant panel",
    description: "Virtual Stream Deck: show and press keys.",
    noPanel: "No virtual panel selected.",
    unavailable: "Panel not available.",
    panel: "Panel",
    noPanels: "No virtual panel yet. Add one under Settings → Devices & services → Stream Assistant.",
    showTitle: "Show title",
    gap: "Gap between keys (px)",
  },
};

const texts = (hass) => TEXTS[(hass?.language || "en").split("-")[0]] || TEXTS.en;

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class StreamAssistantCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._panel = null; // {title, cols, rows, brightness}
    this._images = {}; // key index -> base64 JPEG, kept across re-renders
    this._unsub = null;
    this._subscribing = false;
    this._retry = null;
    this._error = false;
    this._down = new Set();
  }

  static getConfigElement() {
    return document.createElement(`${CARD_TYPE}-editor`);
  }

  static async getStubConfig(hass) {
    const panels = await hass.callWS({ type: "stream_assistant/panel/list" }).catch(() => []);
    return { entry_id: panels[0]?.entry_id || "" };
  }

  setConfig(config) {
    const changed = config.entry_id !== this._config?.entry_id;
    this._config = { show_title: false, gap: 8, ...config };
    if (changed) this._resubscribe(0);
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._resubscribe(0);
  }

  getCardSize() {
    return (this._panel?.rows || 3) * 2 + (this._config?.show_title ? 1 : 0);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 3 };
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._resubscribe(0);
  }

  disconnectedCallback() {
    this._unsubscribe();
    clearTimeout(this._retry);
    this._retry = null;
  }

  // Subscription

  _unsubscribe() {
    const unsub = this._unsub;
    this._unsub = null;
    if (unsub) unsub.then((fn) => fn()).catch(() => {});
  }

  _resubscribe(delay) {
    this._unsubscribe();
    clearTimeout(this._retry);
    this._retry = setTimeout(() => this._subscribe(), delay);
  }

  _subscribe() {
    this._retry = null;
    if (!this._hass || !this._config?.entry_id || !this.isConnected) return;
    const promise = this._hass.connection.subscribeMessage((msg) => this._onMessage(msg), {
      type: "stream_assistant/panel/subscribe",
      entry_id: this._config.entry_id,
    });
    this._unsub = promise;
    promise.then(
      () => {
        this._error = false;
      },
      () => {
        if (this._unsub !== promise) return;
        this._unsub = null;
        this._error = true;
        this._panel = null;
        this._render();
        this._resubscribe(RETRY_MS);
      },
    );
  }

  _onMessage(msg) {
    if (msg.stopped) {
      // The panel reloads (e.g. new grid) or was removed
      this._resubscribe(RESUBSCRIBE_MS);
      return;
    }
    if (msg.cols) {
      this._panel = { title: msg.title, cols: msg.cols, rows: msg.rows, brightness: msg.brightness };
      this._images = { ...msg.images };
      this._render();
      return;
    }
    if (msg.image !== undefined) this._setImage(msg.key, msg.image);
    if (msg.brightness !== undefined && this._panel) {
      this._panel.brightness = msg.brightness;
      this._applyBrightness();
    }
  }

  // Rendering

  _render() {
    if (!this._config) return;
    const t = texts(this._hass);
    const panel = this._panel;
    let body;
    if (!this._config.entry_id) body = `<div class="msg">${esc(t.noPanel)}</div>`;
    else if (!panel) body = this._error ? `<div class="msg">${esc(t.unavailable)}</div>` : `<div class="msg"></div>`;
    else {
      const keys = Array.from({ length: panel.cols * panel.rows }, (_, i) => `<button class="key" data-key="${i}" aria-label="${i + 1}"><img alt=""></button>`).join("");
      body = `<div class="grid" style="--cols:${panel.cols};--gap:${Number(this._config.gap) || 0}px">${keys}</div>`;
    }
    const title = this._config.show_title && panel ? `<div class="title">${esc(panel.title)}</div>` : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 12px; box-sizing: border-box; }
        .title { font-size: 16px; font-weight: 500; margin: 0 4px 10px; color: var(--primary-text-color); }
        .grid { display: grid; grid-template-columns: repeat(var(--cols), minmax(0, 1fr)); gap: var(--gap); transition: filter 0.4s; }
        .key { aspect-ratio: 1; padding: 0; border: 0; border-radius: 14%; overflow: hidden; background: #111;
          cursor: pointer; touch-action: manipulation; user-select: none; -webkit-user-select: none;
          -webkit-touch-callout: none; -webkit-tap-highlight-color: transparent; transition: transform 0.08s, filter 0.08s; }
        .key img { display: block; width: 100%; height: 100%; object-fit: cover; pointer-events: none; }
        .key img:not([src]) { visibility: hidden; }
        .key.down { transform: scale(0.94); filter: brightness(0.8); }
        .key:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        .msg { padding: 16px; color: var(--secondary-text-color); text-align: center; min-height: 20px; }
      </style>
      <ha-card>${title}${body}</ha-card>`;
    this._bindKeys();
    this._applyBrightness();
    for (const [index, image] of Object.entries(this._images)) this._setImage(Number(index), image);
  }

  _setImage(index, image) {
    this._images[index] = image;
    const img = this.shadowRoot.querySelector(`.key[data-key="${index}"] img`);
    if (img) img.src = `data:image/jpeg;base64,${image}`;
  }

  _applyBrightness() {
    const grid = this.shadowRoot.querySelector(".grid");
    if (grid && this._panel) grid.style.filter = `brightness(${Math.max(0, Math.min(100, this._panel.brightness)) / 100})`;
  }

  // Presses

  _bindKeys() {
    for (const key of this.shadowRoot.querySelectorAll(".key")) {
      const index = Number(key.dataset.key);
      const up = () => this._release(key, index);
      key.addEventListener("pointerdown", (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        key.setPointerCapture?.(ev.pointerId);
        this._press(key, index);
      });
      key.addEventListener("pointerup", up);
      key.addEventListener("pointercancel", up);
      key.addEventListener("lostpointercapture", up);
      key.addEventListener("contextmenu", (ev) => ev.preventDefault());
      // Keyboard: Enter/Space behave like a short press
      key.addEventListener("keydown", (ev) => {
        if ((ev.key === "Enter" || ev.key === " ") && !ev.repeat) {
          ev.preventDefault();
          this._press(key, index);
        }
      });
      key.addEventListener("keyup", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") up();
      });
    }
  }

  _press(key, index) {
    if (this._down.has(index)) return;
    this._down.add(index);
    key.classList.add("down");
    navigator.vibrate?.(10);
    this._send(index, true);
  }

  _release(key, index) {
    if (!this._down.delete(index)) return;
    key.classList.remove("down");
    this._send(index, false);
  }

  _send(index, pressed) {
    this._hass
      ?.callWS({ type: "stream_assistant/panel/press", entry_id: this._config.entry_id, key: index, pressed })
      .catch(() => {});
  }
}

class StreamAssistantCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._panels = null;
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      hass.callWS({ type: "stream_assistant/panel/list" }).then(
        (panels) => {
          this._panels = panels;
          this._render();
        },
        () => {
          this._panels = [];
          this._render();
        },
      );
    }
  }

  _render() {
    if (!this._hass || this._panels === null) return;
    const t = texts(this._hass);
    const c = this._config;
    if (!this._panels.length) {
      this.innerHTML = `<p>${esc(t.noPanels)}</p>`;
      return;
    }
    const options = this._panels
      .map((p) => `<option value="${esc(p.entry_id)}" ${p.entry_id === c.entry_id ? "selected" : ""}>${esc(p.title)} (${p.cols} × ${p.rows})</option>`)
      .join("");
    this.innerHTML = `
      <style>
        .sa-editor { display: grid; gap: 12px; }
        .sa-editor label { display: grid; gap: 4px; color: var(--primary-text-color); }
        .sa-editor label.check { display: flex; align-items: center; gap: 8px; }
        .sa-editor select, .sa-editor input[type=number] { font: inherit; padding: 8px; border-radius: 6px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
      </style>
      <div class="sa-editor">
        <label>${esc(t.panel)}<select data-field="entry_id">${c.entry_id ? "" : "<option value=''></option>"}${options}</select></label>
        <label class="check"><input type="checkbox" data-field="show_title" ${c.show_title ? "checked" : ""}>${esc(t.showTitle)}</label>
        <label>${esc(t.gap)}<input type="number" min="0" max="40" data-field="gap" value="${esc(c.gap ?? 8)}"></label>
      </div>`;
    for (const input of this.querySelectorAll("[data-field]")) {
      input.addEventListener("change", () => this._changed(input));
    }
  }

  _changed(input) {
    const field = input.dataset.field;
    let value = input.type === "checkbox" ? input.checked : input.value;
    if (field === "gap") value = value === "" ? 8 : Math.max(0, Math.min(40, Number(value)));
    this._config = { ...this._config, [field]: value };
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
  }
}

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, StreamAssistantCard);
  customElements.define(`${CARD_TYPE}-editor`, StreamAssistantCardEditor);
  window.customCards = window.customCards || [];
  // The card picker shows this text: Home Assistant's language, else the browser's
  const t = texts({ language: document.querySelector("home-assistant")?.hass?.language || navigator.language });
  window.customCards.push({ type: CARD_TYPE, name: t.name, description: t.description, preview: false });
}
