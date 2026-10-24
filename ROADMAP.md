# Roadmap

## Order (decided 2026-10-23)

1. ~~Transport + capabilities layer in the integration~~ — 0.5.1
   (`scripts/fake_dock.py` + `scripts/selftest_transport.py` test it without hardware)
2. ~~Virtual deck in HA with dashboard card~~ — 0.6.0/0.6.1
   (free grid of columns × rows instead of a fixed model; card `custom:stream-assistant-card`;
   templates can use free grids too; removing an entry deletes its layouts)
3. **Bridge with neutral protocol** — mostly done
   - ~~protocol specification~~ [docs/bridge-protocol.md](docs/bridge-protocol.md)
   - ~~.NET bridge~~ (pairing, mDNS, simulated decks, single-instance lock) — bridge 0.1.0
   - ~~integration side~~ (one entry per bridge, decks appear and disappear on their own,
     reauth when the bridge forgets the pairing) — 0.7.0
   - ~~desktop app~~ (Avalonia) with virtual decks of any grid
   - **open: Elgato USB driver** (HidSharp): MK.2 / Original v2 / XL first (JPEG, rotation in
     the bridge), several decks per computer, USB hot-plug. Can be prepared now, needs the
     real deck to verify. The Elgato app must not run at the same time (exclusive USB access).
4. **Home Assistant add-on and platform packages**
   - add-on with the console bridge (linux-musl, USB passthrough), pairing skipped for the
     Supervisor network as the protocol allows
   - packages/installers for Windows, macOS, Linux, Raspberry Pi; autostart; tray icon
5. **Docs and HACS beta**: user documentation (installation, setup, editor, templates,
   actions, bridge, troubleshooting), screenshots, `info.md`, GitHub releases with version
   tags, published first as a beta (pre-release) on github.com/remostirnimann/StreamAssistant.

## Then

- **More manufacturers**: Mirabox/Ajazz "Stream Dock" and Ulanzi D200 (USB HID),
  Loupedeck / Razer Stream Controller (USB serial, dials, touch), MIDI controllers such
  as Novation Launchpad / Akai APC (colour-only LED pads), DIY ESP32 decks. Drivers live in
  the bridge; the protocol already describes image keys, colour-only keys, dials and touch.
  The integration still needs colour-only keys, dials and touch (skipped so far with a warning).
- **More Elgato models**: Stream Deck Plus (dials, touch strip), Neo, Studio, Mini and
  Original v1 (BMP images, done by the bridge)

## Done

- Dock info page and simple dock automations (night brightness by time window or sun,
  fade out when idle with "first press only wakes") — 0.4.0
- Planning without any dock: "Only plan (no hardware yet)" entry in the config flow — 0.5.0

## Later

- Expose the behaviour to HA as well (e.g. a switch "fade out when idle", a "wake" button)
- Library split: move `protocol/` into its own PyPI package (needed for HA core)
- Tests (pytest-homeassistant-custom-component), CI, hassfest/HACS validation
- Bridge: TLS (`wss://`), log view in the desktop app
