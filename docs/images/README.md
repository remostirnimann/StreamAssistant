# Images of the documentation

Every screenshot and picture the documentation uses or still needs. ✅ = done (made without
Home Assistant or hardware, can be made again, see below), 📷 = still to take on a real
Home Assistant or with real hardware.

## Done

| File | Shows | Used in | Made with |
|---|---|---|---|
| `keys-gallery.png` | 15 typical keys as Home Assistant draws them | [README](../README.md) | renderer |
| `touch-strip.png` | Stream Deck + touch strip with four dials' entities and level bars | [editor](../editor.md#dials-and-touch-strip) | renderer |
| `neo-screen.png` | Stream Deck Neo info screen with the page name | [editor](../editor.md#page-buttons-and-screen-stream-deck-neo) | renderer |
| `editor-keys.png` | Key editor, MK.2 with a key selected | [editor](../editor.md) | editor test page |
| `editor-dial.png` | Key editor, Stream Deck + with a dial selected (turning, step, test buttons) | [editor](../editor.md#dials-and-touch-strip) | editor test page |
| `editor-studio.png` | Key editor, Stream Deck Studio (16×2 keys, two dials) | [devices](../devices.md) | editor test page |
| `editor-info.png` | Info & behaviour view | [editor](../editor.md#info-and-behaviour) | editor test page |
| `editor-template-dialog.png` | New template dialog | [editor](../editor.md#templates) | editor test page |
| `editor-entity-picker.png` | Entity picker with areas | [editor](../editor.md#keys) | editor test page |
| `editor-icon-picker.png` | Icon picker with suggestions | [editor](../editor.md#keys) | editor test page |
| `card-virtual-panel.png` | Dashboard card of a virtual panel (4×3) | [virtual panels](../virtual-panels.md) | card test page |
| `bridge-desktop-pairing.png` | Bridge desktop window, not paired, pairing code | [bridge](../bridge.md#first-start-and-pairing) | desktop UI tests |
| `bridge-desktop-add-deck.png` | Adding a virtual deck in the bridge window | [virtual panels](../virtual-panels.md#virtual-decks-in-the-bridge-window) | desktop UI tests |
| `bridge-desktop-virtual-deck.png` | A virtual deck in the bridge window | [virtual panels](../virtual-panels.md#virtual-decks-in-the-bridge-window) | desktop UI tests |
| `bridge-desktop-dials.png` | A virtual deck with dials and touch strip | [virtual panels](../virtual-panels.md#virtual-decks-in-the-bridge-window) | desktop UI tests |
| `bridge-status-page.png` | Bridge status page (`http://localhost:5390`) | [bridge](../bridge.md#status-page) | headless browser |
| `simulator-page.png` | Simulator page with several decks | [virtual panels](../virtual-panels.md#simulated-decks) | headless browser |
| `sim-mk2.png` | Simulated Stream Deck MK.2 | [devices](../devices.md) | headless browser |
| `sim-plus.png` | Simulated Stream Deck + with touch strip and dials | [devices](../devices.md) | headless browser |
| `sim-neo.png` | Simulated Stream Deck Neo with page buttons and screen | [devices](../devices.md) | headless browser |
| `sim-studio.png` | Simulated Stream Deck Studio with LED rings and NFC field | [devices](../devices.md) | headless browser |
| `sim-pedal.png` | Simulated Stream Deck Pedal | [devices](../devices.md) | headless browser |
| `ha-hacs-custom-repository.png` | HACS → ⋮ → Custom repositories, with the repository URL and type *Integration* filled in | [installation](../installation.md#install-with-hacs-recommended) | test Home Assistant |
| `ha-add-menu.png` | *Add integration → Stream Assistant*: the menu with Dock / Bridge / Virtual panel / Only plan | [setup](../setup.md) | test Home Assistant |
| `ha-discovered.png` | *Devices & services* with "Discovered: Stream Deck Network Dock" and/or "Stream Assistant Bridge" | [setup](../setup.md#network-dock) | test Home Assistant |
| `ha-bridge-pairing.png` | The pairing step asking for the 6-digit code | [setup](../setup.md#stream-assistant-bridge) | test Home Assistant |
| `ha-virtual-panel-form.png` | The virtual panel form (name, columns, rows) | [setup](../setup.md#virtual-panel) | test Home Assistant |
| `ha-device-page.png` | A deck's device page with its entities (keys, brightness, connection) | [setup](../setup.md#what-you-get-in-home-assistant) | test Home Assistant |
| `ha-sidebar.png` | The sidebar with the *Stream Assistant* entry | [editor](../editor.md) | test Home Assistant |

## Still to take

Every place in the documentation that still needs one of these images has a hidden marker
(an HTML comment, not shown on GitHub). Search the repository for **`TODO image`** to find
them all; replace the marker with the image once it exists.

Screenshots of Home Assistant itself (its dialogs cannot be shown without a running
Home Assistant) and photos of real hardware. Take Home Assistant screenshots in English,
light theme, about 1280 px wide; crop to the dialog.

| File | Shows | For | Notes |
|---|---|---|---|
| `ha-card-picker.png` | 📷 Dashboard *Add card* with the *Stream Assistant panel* card and its editor (after the next update: before 0.9 the card's text followed the browser language) | [virtual panels](../virtual-panels.md#virtual-panels-in-home-assistant) | |
| `ha-bridge-update.png` | 📷 *Settings → Updates* (or the bridge's device page) with the bridge update offered | [bridge](../bridge.md#updates) | Needs a bridge one version behind |
| `bridge-msi-start-menu.png` | 📷 Windows start menu entry *Stream Assistant Bridge* and the status page with the pairing code | [bridge](../bridge.md#windows) | On a Windows PC with the installer |
| `ha-automation-event.png` | 📷 Automation editor: state trigger on a key's event entity | [automations](../automations.md) | Optional |
| `photo-dock-mk2.jpg` | 📷 Photo: Network Dock with a Stream Deck MK.2 showing a layout | [README](../README.md), [devices](../devices.md) | Daylight, no reflections; about 1600 px wide |
| `photo-wall-tablet.jpg` | 📷 Photo: a wall tablet showing a virtual panel | [virtual panels](../virtual-panels.md) | Optional |
| `photo-<model>.jpg` | 📷 Photos of the other models once they are tested | [devices](../devices.md) | When the hardware is available |
| `logo.png` / `icon.png` | 📷 Logo for the README and icon for HACS / Home Assistant brands (256 × 256 and 512 × 512) | README, brands repository | To decide: design |

## Making the done images again

- **Renderer images** (`keys-gallery.png`, `touch-strip.png`, `neo-screen.png`): drawn with
  `custom_components/stream_assistant/render.py`, using the demo layout of `scripts/docs_demo.py`.
- **Simulator and status page:** start the bridge with
  `dotnet run --project bridge/src/StreamAssistant.Bridge -- --simulate mk2,plus,neo,studio,pedal --usb false --name "Office PC"`,
  run `.venv/Scripts/python.exe scripts/docs_demo.py` (keeps running; it paints the demo
  layout and keeps the decks from resetting), then capture `http://localhost:5390/sim` and
  `http://localhost:5390/` with a headless browser, for example
  `msedge --headless=new --hide-scrollbars --window-size=820,2560 --force-device-scale-factor=2 --virtual-time-budget=5000 --screenshot=sim.png http://localhost:5390/sim`,
  and crop each deck.
- **Bridge window:** `SAB_TEST_LANGUAGE=en dotnet test --project bridge/tests/StreamAssistant.Bridge.Desktop.Tests`
  writes English screenshots to `bin/Debug/net10.0/screenshots/` (`01-empty`, `02-add-form`,
  `03-deck`, `05-dials`).
- **Editor and card:** `scripts/docs-pages/` (see its `build.py`) loads `frontend/panel.js` or `frontend/card.js`
  with a pretend Home Assistant connection (no real Home Assistant needed) and the demo
  images; captured with the headless browser at 1400 px width.
