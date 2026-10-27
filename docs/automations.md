# Automations

Most keys need no automation: their action is set in the [key editor](editor.md). Use
automations when a press should do more than one action, depend on conditions, or when a
dial, the touch strip or an NFC tag should start something.

## Event entities

Every key, dial, touch strip and page button has an **event entity** (see the list in
[Setup](setup.md#what-you-get-in-home-assistant)). When something happens its state becomes
the current time and the attribute `event_type` says what happened:

| Entity | `event_type` | Extra attributes |
|---|---|---|
| Key | `pressed`, `released`, `short_press`, `long_press` | `key`, `row`, `column` (from 0) |
| Dial | `rotate_left`, `rotate_right`, `pressed`, `released`, `short_press`, `long_press` | `dial`; `steps` when turned |
| Touch strip | `tap`, `long_press`, `swipe_left`, `swipe_right` | `x`, `y`, `dial` (the dial below); `x2`, `y2` for swipes |
| Page button | `pressed`, `released`, `short_press`, `long_press` | `button` |

A short press fires `pressed`, `released`, `short_press`; a long press fires `pressed`,
`long_press` (after 0.5 s) and `released`.

Trigger on the entity's state and check the event type. `not_from` / `not_to` keep the
automation from running when the deck goes offline and comes back:

```yaml
triggers:
  - trigger: state
    entity_id: event.stream_deck_mk_2_key_1
    not_from: unavailable
    not_to: unavailable
conditions:
  - condition: state
    entity_id: event.stream_deck_mk_2_key_1
    attribute: event_type
    state: long_press
actions:
  - action: scene.turn_on
    target:
      entity_id: scene.movie_night
```

<!-- TODO image: images/ha-automation-event.png – optional: automation editor with a state trigger on a key's event entity (list: docs/images/README.md) -->

A dial turned to the right, as many times as it was turned:

```yaml
triggers:
  - trigger: state
    entity_id: event.stream_deck_plus_dial_1
    not_from: unavailable
    not_to: unavailable
conditions:
  - "{{ trigger.to_state.attributes.event_type == 'rotate_right' }}"
actions:
  - repeat:
      count: "{{ trigger.to_state.attributes.steps }}"
      sequence:
        - action: media_player.media_next_track
          target:
            entity_id: media_player.living_room
```

A swipe on the touch strip:

```yaml
triggers:
  - trigger: state
    entity_id: event.stream_deck_plus_touch_strip
    not_from: unavailable
    not_to: unavailable
conditions:
  - "{{ trigger.to_state.attributes.event_type == 'swipe_left' }}"
actions:
  - action: script.previous_room
```

The events fire for every press, also when the key has an action in the editor, and also
when you use **Run** in the editor. A press that only woke a dimmed deck fires nothing
(see *First press only wakes* in [behaviour](editor.md#info-and-behaviour)).

## Change what a key shows

The action **Stream Assistant: Set key** (`stream_assistant.set_key`) changes a key on the
page currently shown, for example to show a value the layout does not cover. Target the key's
event entity:

```yaml
action: stream_assistant.set_key
target:
  entity_id: event.stream_deck_mk_2_key_5
data:
  text: "Washing\ndone"
  background_color: [32, 128, 64]
  text_color: "#ffffff"
  font_size: 14
  image: /config/www/streamdeck/washer.png   # optional, a file on the Home Assistant host
```

The change is stored in the layout like an edit in the editor. **Stream Assistant: Clear key**
(`stream_assistant.clear_key`) empties the key. For keys that should follow an entity, an
entity in the editor is simpler and updates by itself.

## Brightness

Each deck with a display has a `number` entity for its brightness (0–100 %). Set it from an
automation or show it on a dashboard. For night brightness and fading out when idle there
are ready-made settings in the editor ([behaviour](editor.md#info-and-behaviour)).

```yaml
action: number.set_value
target:
  entity_id: number.stream_deck_mk_2_brightness
data:
  value: 40
```

## NFC tags (Stream Deck Studio)

A tag read by the Studio is a normal Home Assistant **tag scan**, with the Studio as the
device. It shows up under *Settings → Tags* and works with the usual tag trigger:

```yaml
triggers:
  - trigger: tag
    tag_id: 04A2B3C4D5
actions:
  - action: lock.unlock
    target:
      entity_id: lock.front_door
```

This needs the **Tags** integration, which is part of Home Assistant's default
configuration. Without it the integration writes a warning to the log.

## Connection state

`binary_sensor.<deck>_connected` and `binary_sensor.<dock or bridge>_connected` tell
whether a deck is reachable, for example for a notification:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.stream_deck_mk_2_connected
    to: "off"
    for: "00:05:00"
actions:
  - action: notify.notify
    data:
      message: "The Stream Deck in the living room has been offline for 5 minutes."
```
