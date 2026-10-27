# Stream Assistant Bridge Protocol, version 1 (draft)

The bridge is a program that drives control surfaces (Stream Decks and, later,
devices of other manufacturers) on a computer and offers them to Home Assistant
over the network. This document defines how Home Assistant (the **client**)
talks to a bridge (the **server**). It is independent of programming
languages, so other clients and bridges can be written against it.

Key words MUST, SHOULD and MAY are used as in RFC 2119.

## Design goals

- **Vendor-neutral.** The client only sees capabilities (a grid of image keys,
  dials, a touch strip), never vendor protocols. Vendor drivers live in the bridge.
- **Upright and simple.** The client sends upright images at the advertised
  size. Rotation, mirroring and pixel formats are the bridge's job.
- **Many devices, one connection.** A bridge serves any number of devices over
  a single connection; devices come and go (USB hot-plug).
- **Robust.** Stable device ids across replugging and restarts, keepalive,
  full state resync after every reconnect.

## 1. Transport

- WebSocket (RFC 6455) over TCP, path `/ws`. Default port **5390**, configurable.
- **Text frames** carry one JSON object each (UTF-8).
- **Binary frames** carry image data in a binary envelope (section 6).
- Plain `ws://` in version 1, for use inside a trusted LAN or on the same host.
  The bridge authenticates clients with a token (section 3). TLS (`wss://`) is
  reserved for a later version.

## 2. Discovery

The bridge SHOULD announce itself via mDNS/DNS-SD:

| Field    | Value                                      |
|----------|--------------------------------------------|
| Service  | `_stream-assistant._tcp.local.`            |
| Port     | the WebSocket port                         |
| TXT `id` | bridge id (stable, see below)              |
| TXT `name` | human-readable name, e.g. the computer name |
| TXT `version` | bridge software version              |
| TXT `proto` | highest protocol version supported (`1`) |
| TXT `path` | WebSocket path (`/ws`)                    |

The **bridge id** is generated once (e.g. 16 random hex characters), stored,
and never changes. Clients identify a bridge by this id, never by its address,
and follow address changes through new announcements.

## 3. Session

### 3.1 Handshake

The first message on a new connection MUST be `hello` from the client.

```json
{"type": "hello", "protocol": 1, "client": "Home Assistant", "client_version": "0.7.0", "token": "…"}
```

`token` is omitted when the client is not paired yet. The bridge answers with
`welcome`, followed immediately by `devices` (section 4):

```json
{"type": "welcome", "protocol": 1,
 "bridge": {"id": "3f9a1c0be2d44a17", "name": "Office PC", "version": "0.1.0", "platform": "windows-x64"},
 "features": ["key_images", "key_colors", "brightness", "dials", "touch", "buttons", "screen", "dial_leds", "nfc", "update"]}
```

`features` lists optional parts of this protocol the bridge implements; a
client MUST NOT rely on anything not listed. Unknown features MUST be ignored.

If the handshake fails, the bridge sends `error` (section 8) and closes the
connection:

- `unsupported_protocol`: no common protocol version; the error carries
  `"supported": [1]`.
- `unauthorized`: token missing or unknown; the client may pair (3.2).

### 3.2 Pairing

A bridge accepts only paired clients. Pairing is a one-time step:

1. The bridge shows a 6-digit **pairing code** in its window, tray menu or log.
   A bridge MAY show it only while pairing mode is enabled (e.g. for 5 minutes
   after the user clicks "Pair").
2. The client sends `hello` without a token, receives `unauthorized`, then
   (on a new connection) sends:
   ```json
   {"type": "pair", "protocol": 1, "client": "Home Assistant", "code": "482913"}
   ```
3. On success the bridge answers `paired` with a long-lived token and keeps
   the connection open as if `welcome` had been sent (welcome and devices follow):
   ```json
   {"type": "paired", "token": "…"}
   ```
   On failure: `error` with code `invalid_code` and the connection is closed.
   After 5 failed attempts the bridge SHOULD refuse pairing for a minute.

Tokens MUST be at least 128 bits of randomness. The bridge stores them and lets
the user revoke them. A bridge running as a Home Assistant add-on MAY skip
pairing for connections from the Supervisor network.

### 3.3 One active client

A bridge serves one client at a time. When a second client authenticates, the
bridge sends `error` with code `replaced` to the first one and closes it.
This makes a restarted client take over a half-open old connection at once.

### 3.4 Keepalive

Both sides send WebSocket pings every 10 seconds. A side that receives nothing
(ping, pong or message) for 30 seconds MUST consider the connection dead and
close it. The client then reconnects with backoff (1 s doubling up to 30 s).

### 3.5 Resync

The bridge does not remember what the client showed. After every (re)connect
the client MUST send brightness and all key images again. When the client
disconnects, the bridge SHOULD keep the last images for 30 seconds (to bridge
short reconnects), then reset the devices to their idle screen.

## 4. Devices

### 4.1 Inventory

Right after `welcome` (or `paired`), the bridge sends the full list:

```json
{"type": "devices", "devices": [ DEVICE, … ]}
```

Later changes come as single messages:

```json
{"type": "device_added", "device": DEVICE}
{"type": "device_removed", "device": "elgato-AL12K1A01234"}
```

A device that is unplugged and plugged in again is removed and added again
with the **same id**.

### 4.2 Device object

```json
{
  "id": "elgato-AL12K1A01234",
  "vendor": "Elgato",
  "model": "Stream Deck MK.2",
  "name": "Stream Deck MK.2",
  "serial": "AL12K1A01234",
  "firmware": "1.02.000",
  "virtual": false,
  "capabilities": {
    "keys": {"cols": 5, "rows": 3, "image": {"width": 72, "height": 72, "formats": ["jpeg", "png"]}},
    "brightness": true
  }
}
```

- `id`: stable and unique per bridge, at most 64 characters of `[A-Za-z0-9._-]`.
  Bridges SHOULD derive it from vendor and serial number.
- `virtual`: true for devices that exist only in software (e.g. a window on
  the bridge's desktop).
- `capabilities`: what the device has. Absent members mean "not present".

| Capability | Fields | Meaning |
|---|---|---|
| `keys` | `cols`, `rows`, `image` or `colors` | Grid of keys. With `image` the keys show pictures of `width`×`height` pixels in one of `formats` (`jpeg`, `png`). With `"colors": true` (and no `image`) the keys only show a colour (LED pads). With neither, the keys have no display and only report presses (pedals): images and colours are refused with `unsupported`. |
| `brightness` | `true` | The display brightness can be set. |
| `dials` | `count`, `press`, `ring` | Rotary encoders, left to right; `press` true when they can be pushed; `ring` the number of LEDs around each (0 or missing: none). |
| `touch` | `width`, `height` | A touch display (e.g. strip of the Stream Deck Plus), addressed in pixels. |
| `buttons` | `count`, `colors` | Buttons outside the key grid (e.g. the page buttons of the Stream Deck Neo); `colors` true when they can be lit. |
| `screen` | `width`, `height`, `formats` | A display without touch input (e.g. the info display of the Stream Deck Neo). |
| `nfc` | – | `true` when the device reads NFC tags (Stream Deck Studio). |

Keys are numbered from 0, row by row, starting top left, **as the user sees
the device**. Pixel coordinates (touch) start at the top left as well.

## 5. Output (client → bridge)

Every client message MAY carry an `id` (integer). The bridge then answers with
`result` (section 7). Messages without `id` get no answer unless they fail.

| Message | Fields | Effect |
|---|---|---|
| `set_brightness` | `device`, `percent` (0–100) | Display brightness. |
| `set_key_color` | `device`, `key`, `color` (`#rrggbb`) | Fills a key with a colour. Works on image keys too. |
| `clear_key` | `device`, `key` | Key shows black / off. |
| `reset` | `device` | Device shows its idle screen (vendor logo or blank). |
| `identify` | `device` | Device draws attention for a few seconds (flash), to find it. |
| `set_button_color` | `device`, `button`, `color` (`#rrggbb`) | Lights a button outside the grid; black is off. |
| `set_dial_leds` | `device`, `dial`, `color`, `level` (0–1, default 1) | Lights that share of the dial's LED ring, and its centre, in the colour. |

```json
{"type": "set_brightness", "device": "elgato-AL12K1A01234", "percent": 70, "id": 12}
```

Bridges with the `update` feature can install a release of themselves:

| Message | Fields | Effect |
|---|---|---|
| `update` | `version` (e.g. `0.9.0`) | Downloads that release, checks its checksum, installs it and restarts. Progress comes as `update_status` (section 9); the bridge is back with the new `version` in its next `welcome`. Fails with `error` (`request` = `update`) when it cannot start, for example while another update runs. |

Images are sent as binary frames (section 6): `set_key_image` for a key,
`set_touch_image` for an area of a touch display.

## 6. Binary envelope

A binary frame is:

| Bytes | Content |
|---|---|
| 0–1 | header length `n`, unsigned 16 bit, big-endian |
| 2 … 2+n−1 | header, a JSON object in UTF-8 (same rules as text messages) |
| rest | payload |

```text
00 nn {"type":"set_key_image","device":"elgato-AL12K1A01234","key":7,"format":"jpeg"} FF D8 FF …
```

| Header `type` | Fields | Payload |
|---|---|---|
| `set_key_image` | `device`, `key`, `format` | Encoded image, upright, `width`×`height` from the device's `keys.image`. |
| `set_touch_image` | `device`, `x`, `y`, `width`, `height`, `format` | Encoded image for that area of the touch display. |
| `set_screen_image` | `device`, `format` | Encoded image for the whole screen, upright, `width`×`height` from `screen`. |

The bridge converts images as the device needs (rotation, mirroring, BMP,
scaling when the size differs). For each key only the newest image counts:
when images arrive faster than the device accepts them, the bridge MAY drop
older images that were not shown yet. So the client never has to wait.

## 7. Results

```json
{"type": "result", "id": 12, "ok": true}
{"type": "result", "id": 13, "ok": false, "error": {"code": "unknown_device", "message": "…"}}
```

A failed message without `id` is answered with `error` (section 8) carrying
the `type` of the failed message.

## 8. Errors

```json
{"type": "error", "code": "unknown_device", "message": "No device elgato-XYZ", "request": "set_key_color"}
```

| Code | Meaning |
|---|---|
| `unsupported_protocol` | No common protocol version (handshake). |
| `unauthorized` | Token missing or revoked (handshake). |
| `invalid_code` | Wrong pairing code. |
| `replaced` | Another client took over; the connection closes. |
| `unknown_device` | The device does not exist (any more). |
| `unsupported` | The device lacks the capability (e.g. image on a colour-only key). |
| `invalid_message` | Malformed message or field out of range. |
| `device_error` | The device failed (e.g. USB write error). |

Unknown message types MUST be answered with `invalid_message` and otherwise
ignored, so newer clients can probe older bridges.

## 9. Input (bridge → client)

| Message | Fields | Meaning |
|---|---|---|
| `key` | `device`, `key`, `pressed` | Key went down (`true`) or up (`false`). |
| `dial` | `device`, `dial`, `delta` | Dial turned by `delta` steps, positive = clockwise. |
| `dial_press` | `device`, `dial`, `pressed` | Dial pushed / released. |
| `touch` | `device`, `kind`, `x`, `y` (+ `x2`, `y2` for `swipe`) | `kind` is `tap`, `long` or `swipe`. |
| `button` | `device`, `button`, `pressed` | A button outside the grid went down or up. |
| `nfc` | `device`, `id` | An NFC tag was read; `id` as the reader reports it. |
| `update_status` | `state`, `version`, `message` (on failure) | Progress of an `update`: `downloading`, `installing` (the bridge restarts next) or `failed`. |

```json
{"type": "key", "device": "elgato-AL12K1A01234", "key": 7, "pressed": true}
```

The bridge reports raw events; short/long press, double clicks and actions are
the client's business.

## 10. Versioning

- The protocol version is one integer. Incompatible changes increase it;
  bridges SHOULD support the previous version for a while.
- Compatible additions (new optional fields, messages, capabilities) do not
  change the version. They are announced through `features` or new members in
  `capabilities`. Receivers MUST ignore unknown fields.

## 11. Example session

```text
client → {"type":"hello","protocol":1,"client":"Home Assistant","client_version":"0.7.0","token":"…"}
bridge → {"type":"welcome","protocol":1,"bridge":{…},"features":["key_images","brightness"]}
bridge → {"type":"devices","devices":[{"id":"elgato-AL12K1A01234", … "keys":{"cols":5,"rows":3,…}}]}
client → {"type":"set_brightness","device":"elgato-AL12K1A01234","percent":70}
client → [binary] set_key_image key 0 … key 14
bridge → {"type":"key","device":"elgato-AL12K1A01234","key":3,"pressed":true}
bridge → {"type":"key","device":"elgato-AL12K1A01234","key":3,"pressed":false}
bridge → {"type":"device_removed","device":"elgato-AL12K1A01234"}      (unplugged)
bridge → {"type":"device_added","device":{"id":"elgato-AL12K1A01234", …}} (plugged in again)
client → brightness and all 15 images for that device again
```
