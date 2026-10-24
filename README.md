# Stream Assistant

Home Assistant integration that drives **Elgato Stream Decks** directly, with
all configuration in Home Assistant: no Stream Deck app, no Companion. A deck
can be connected in three ways:

- **Elgato Stream Deck Network Dock**: over the network, no extra computer
- **Stream Assistant Bridge**: decks on a computer (Windows, macOS, Linux, later
  a Home Assistant add-on); the desktop version also offers **virtual decks** in a window
- **Virtual panel** in Home Assistant: a deck that only exists as a dashboard card
  (wall tablets, phones), with any number of columns and rows

> Early development. Tested with: Network Dock (firmware 1.01.013) + Stream Deck MK.2.
> The bridge's Elgato USB driver is not written yet; the bridge is tested with
> simulated and virtual decks.

## Features (so far)

- **Key editor** in the sidebar (*Stream Assistant*, admins only): pages and folders,
  per key an entity (drives colours and second line), title, MDI icon, on/off colours,
  and actions for short and long press (toggle/run, open folder/page, back, any action
  with data). The preview shows the real rendered keys with live states.
- **Templates / planned decks**: layouts for a model or a free grid but no hardware,
  designed in the same editor with live preview. Decks can be linked to a template
  (shared layout, also across different sizes by row/column) or detached into their own copy.
- **Info & behaviour** per deck: serials, firmware, address, connection, brightness, layout
  facts; night brightness (time window or sunset) and fading out when idle (dim or off,
  optionally the first press only wakes the deck)
- **Run** buttons simulate a key press (events + action), also for unsaved edits
- Keys follow their entity live (light brightness, cover position, sensor values …)
- Short press runs instantly when no long-press action is set
- One `event` entity per key: `pressed`, `released`, `short_press`, `long_press`
- Brightness (`number`), restored after restarts; connection state (`binary_sensor`)
- Actions `stream_assistant.set_key` and `stream_assistant.clear_key` (act on the page shown)
- Removing an entry also deletes its stored layouts

### Network Dock

- Auto discovery (mDNS `_elg._tcp`) or manual setup by IP, one config entry per dock;
  address changes are followed via mDNS and DHCP
- Automatic reconnect, deck hot-plug (a different deck triggers a reload)
- Only one client can be connected to a dock at a time. Close the Stream Deck app
  or Companion before using this integration.

### Stream Assistant Bridge

- Found via mDNS (`_stream-assistant._tcp`) or added by address, paired once with the
  6-digit code the bridge shows; Home Assistant asks for a new code if the bridge forgets it
- One config entry per bridge; every deck on it is its own device, decks appear and
  disappear with USB hot-plug and keep their identity
- Vendor-neutral protocol: [docs/bridge-protocol.md](docs/bridge-protocol.md);
  the bridge itself: [bridge/README.md](bridge/README.md)

### Virtual panel and dashboard card

- *Settings → Devices & services → Add → Stream Assistant → Virtual panel*: name,
  columns (1–12) and rows (1–8); the grid can be changed later (*Reconfigure*)
- Dashboard card `custom:stream-assistant-card` (loaded automatically, appears in the
  card picker): shows the keys live, press or hold to use them. Every user can view and
  press; configuring stays with admins.

Bundled assets: Material Design Icons font (Pictogrammers, Apache 2.0) and
Roboto Medium (Apache 2.0), see `assets/`.

## Installation

Copy `custom_components/stream_assistant` into your Home Assistant `config/custom_components`
folder (or add this repository to HACS as a custom repository), restart Home Assistant,
then add the integration under *Settings → Devices & services*.

## Example

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: event.stream_deck_mk_2_key_1
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type == 'short_press' }}"
    actions:
      - action: light.toggle
        target:
          entity_id: light.wohnzimmer
```

## Repository layout

- `custom_components/stream_assistant/`: the integration
  - `protocol/`: Home Assistant independent clients for the Network Dock (Cora TCP,
    Gen2 HID reports) and the bridge (`bridge.py`). Will move to its own PyPI package.
  - `transport.py`, `capabilities.py`: how a deck is reached and what it can do
  - `bridge_hub.py`: bridge entries with several decks
  - `frontend/panel.js` (editor) and `frontend/card.js` (dashboard card): plain web
    components, no build step
- `bridge/`: the Stream Assistant Bridge (.NET 10: core library, console and desktop program, tests)
- `docs/bridge-protocol.md`: the bridge protocol specification
- `scripts/`: tests without hardware (`selftest_transport.py` with a simulated dock,
  `selftest_bridge.py` against the real bridge), live test against a dock, render sheet,
  WebSocket and simulator probes for the HA host

Protocol knowledge based on [node-elgato-stream-deck](https://github.com/Julusian/node-elgato-stream-deck) (MIT).

## License

MIT, see [LICENSE](LICENSE). The bundled fonts are licensed under Apache 2.0.
