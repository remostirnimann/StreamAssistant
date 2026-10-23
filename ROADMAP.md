# Roadmap

## Next

- **Documentation and HACS beta release**: user documentation (installation, setup,
  editor, templates, actions, troubleshooting), screenshots, `info.md`/README for HACS,
  GitHub releases with version tags, published first as a **beta** (pre-release) to
  collect feedback while development continues.

- **Stream Assistant Bridge ("virtual dock")**: software that emulates the Network Dock
  so no extra hardware is needed. It speaks the dock's Cora TCP protocol towards Home
  Assistant (port 5343 + a port per deck, keepalives, dock/deck info reports, mDNS
  `_elg._tcp` with `dt=215`) and passes HID reports verbatim to a USB Stream Deck
  (hidapi). The integration needs no changes; discovery, editor, templates and
  behaviour work as with a real dock.
  1. Proof of concept on Windows (deck via USB on the PC, HA sees a second "dock")
  2. Proper bridge: service/autostart, several decks, logging, config
  3. Home Assistant add-on with USB passthrough (deck plugged into the HA host)
  4. Packages for Windows, macOS, Linux and Raspberry Pi, plus docs
  Several decks per computer: one virtual dock per USB deck (own port pair and mDNS
  record; the deck's serial is the dock serial, so each deck stays the same HA device
  across USB ports and reboots), USB hot-plug announces/withdraws docks. Real docks
  and bridge decks can be mixed freely.
  Notes: the Elgato app must not run at the same time (exclusive USB access);
  Gen1 decks (Original v1, Mini) would also need BMP image support in the integration.

- **More manufacturers** (future): Mirabox/Ajazz "Stream Dock" and Ulanzi D200 (USB HID),
  Loupedeck / Razer Stream Controller (USB serial, dials, touch), MIDI controllers such
  as Novation Launchpad / Akai APC (colour-only LED pads), DIY ESP32 decks.
  Needs a driver layer: devices describe capabilities (image keys vs colour-only keys,
  image size/format/rotation, dials, touch areas) instead of fixed Elgato models; the
  renderer, editor and templates work from these capabilities. Same groundwork as
  Stream Deck Plus (dials, touch strip).
  Impact on the bridge: with several manufacturers planned, the bridge should speak a
  vendor-neutral Stream Assistant protocol (device capabilities, show image/colour on
  key N, key/dial/touch events) with the vendor drivers inside the bridge, instead of
  only emulating the Elgato Network Dock. **Decided 2026-10-23: neutral protocol.**
  **Bridge language: .NET (C#, .NET 10 LTS)**, published as self-contained single-file
  builds (win-x64, osx-arm64/x64, linux-x64/arm64, linux-musl for the HA add-on);
  HidSharp for USB HID, Avalonia for the virtual deck window. The neutral protocol is
  written down as a language-independent specification first.
- **Virtual Stream Deck**: a deck that exists only in software.
  - In Home Assistant: config entry "virtual Stream Deck" with a chosen model and all
    entities/layout/templates/behaviour like a real deck, shown as a dashboard card or a
    full-screen page (wall tablets, phones). Needs live push of key images and scoped,
    non-admin commands (view and press only, no configuration).
  - In the bridge: a desktop window (Windows/macOS/Linux) acting as a bridge device.
  - Uses: old tablet as wall panel, try before buying hardware, demos, tests without hardware.

### Proposed order (2026-10-23)

1. ~~Transport + capabilities layer in the integration~~ done in 0.5.1 (Network Dock
   transport; `scripts/fake_dock.py` + `scripts/selftest_transport.py` test it without hardware)
2. Virtual deck in HA with dashboard card
3. Bridge with neutral protocol + Elgato USB driver (several decks per computer, hot-plug)
4. HA add-on and platform packages, then more manufacturers
5. Docs + HACS beta (possibly already after step 2)

## Done

- Dock info page and simple dock automations (night brightness by time window or sun,
  fade out when idle with "first press only wakes") — 0.4.0
- Planning without any dock: "Only plan (no hardware yet)" entry in the config flow — 0.5.0

## Later

- Expose the behaviour to HA as well (e.g. a switch "fade out when idle", a "wake" button)

- Library split: move `protocol/` into its own PyPI package (needed for HA core)
- More models: Stream Deck Plus (dials, touch strip), Neo, Studio
- Tests (pytest-homeassistant-custom-component), CI, hassfest/HACS validation
