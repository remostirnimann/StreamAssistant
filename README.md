# Stream Assistant

Home Assistant integration that drives an **Elgato Stream Deck** attached to an
**Elgato Stream Deck Network Dock** directly over the network: no Stream Deck app,
no Companion, no extra computer.

> Early development. Tested with: Network Dock (firmware 1.01.013) + Stream Deck MK.2.

## Features (so far)

- **Key editor** in the sidebar (*Stream Assistant*, admins only): pages and folders,
  per key an entity (drives colours and second line), title, MDI icon, on/off colours,
  and actions for short and long press (toggle/run, open folder/page, back, any action
  with data). The preview shows the real rendered keys with live states.
- Keys follow their entity live (light brightness, cover position, sensor values …)
- Short press runs instantly when no long-press action is set
- Auto discovery (mDNS `_elg._tcp`) or manual setup by IP, one config entry per dock;
  address changes are followed via mDNS and DHCP
- One `event` entity per key: `pressed`, `released`, `short_press`, `long_press`
- Brightness (`number`), restored after restarts
- Connection state of dock and deck (`binary_sensor`)
- Actions `stream_assistant.set_key` and `stream_assistant.clear_key` (act on the page shown)
- Automatic reconnect, deck hot-plug (a different deck triggers a reload)

Bundled assets: Material Design Icons font (Pictogrammers, Apache 2.0) and
Roboto Medium (Apache 2.0), see `assets/`.

Only one client can be connected to a dock at a time. Close the Stream Deck app
or Companion before using this integration.

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

- `custom_components/stream_assistant/protocol/`: Home Assistant independent dock/deck client
  (Cora TCP framing, Gen2 HID reports). Will move to its own PyPI package.
- `custom_components/stream_assistant/frontend/panel.js`: the editor panel (plain web component, no build step).
- `poc/`: Node.js proof of concept used to validate the protocol.
- `scripts/`: live test against a dock, key render sheet, WebSocket probe for the HA host.

Protocol knowledge based on [node-elgato-stream-deck](https://github.com/Julusian/node-elgato-stream-deck) (MIT).
