# Stream Assistant

Home Assistant integration that drives an **Elgato Stream Deck** attached to an
**Elgato Stream Deck Network Dock** directly over the network: no Stream Deck app,
no Companion, no extra computer.

> Early development. Tested with: Network Dock (firmware 1.01.013) + Stream Deck MK.2.

## Features (so far)

- Auto discovery (mDNS `_elg._tcp`) or manual setup by IP, one config entry per dock
- One `event` entity per key: `pressed`, `released`, `short_press`, `long_press`
- Brightness (`number`), restored after restarts
- Connection state (`binary_sensor`)
- Actions `stream_assistant.set_key` (text, colours, font size, image) and
  `stream_assistant.clear_key`; the layout is stored and repainted on reconnect
- Automatic reconnect, deck hot-plug (a different deck triggers a reload)

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
- `poc/`: Node.js proof of concept used to validate the protocol.

Protocol knowledge based on [node-elgato-stream-deck](https://github.com/Julusian/node-elgato-stream-deck) (MIT).
