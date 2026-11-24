# Roadmap

## Order (decided 2026-10-23, updated 2026-10-29)

1. ~~Transport + capabilities layer in the integration~~ — 0.5.1
   (`scripts/fake_dock.py` + `scripts/selftest_transport.py` test it without hardware)
2. ~~Virtual deck in HA with dashboard card~~ — 0.6.0/0.6.1
   (free grid of columns × rows instead of a fixed model; card `custom:stream-assistant-card`;
   templates can use free grids too; removing an entry deletes its layouts)
3. **Bridge with neutral protocol** — done except the hardware test
   - ~~protocol specification~~ [docs/bridge-protocol.md](docs/bridge-protocol.md)
   - ~~.NET bridge~~ (pairing, mDNS, simulated decks, single-instance lock) — bridge 0.1.0
   - ~~integration side~~ (one entry per bridge, decks appear and disappear on their own,
     reauth when the bridge forgets the pairing) — 0.7.0
   - ~~desktop app~~ (Avalonia) with virtual decks of any grid
   - ~~Elgato USB drivers~~ (HidSharp) for all current families: Original, Mini, MK.2 /
     Original v2 / XL, Stream Deck +, Pedal, Neo, Studio; several decks per computer, USB
     hot-plug — 0.9.0b1
   - **open: verify the USB drivers with real decks**, first the MK.2 (the Elgato app must
     not run at the same time)
4. **Packages and updates**
   - ~~Windows installer~~ (MSI, service, firewall rule, licence dialog) — 0.9.0b1/0.9.0b3
   - ~~Linux and macOS~~ (`install.sh` with systemd or LaunchAgent; Raspberry Pi through
     linux-arm64) — 0.9.0b1
   - ~~bridge updates from Home Assistant~~ (update entity, checksum, rollback) —
     0.9.0b1/0.9.0b2
   - ~~local network only~~ and terms of use — 0.9.0b3
   - **open: try the MSI on a clean Windows and `install.sh` on macOS**
   - ~~Home Assistant add-on~~ with the console bridge: own repository
     (StreamAssistant-addon, filled by the release workflow), Supervisor discovery with a
     token instead of a pairing code, status page and simulator through ingress, USB through
     hidapi/libusb — 0.10.0
   - open: tray icon for the desktop app
5. **Docs and HACS** — beta published
   - ~~user documentation~~ in `docs/` — 0.9.0b1
   - ~~GitHub releases~~ with version tags, built by `release.yml`; pre-releases since
     0.8.0b1; installable in HACS as a custom repository
   - ~~icon~~ in `brand/` of the integration (HA 2026.3 and later; no brands PR needed)
   - **open: missing screenshots and photos** (see `docs/images/README.md`)
   - ~~the HACS default list~~: submitted 2026-10-29 (hacs/default#12924), waiting for review
   - open: first stable 1.0.0 after the hardware test

## Then

- **More manufacturers**: Mirabox/Ajazz "Stream Dock" and Ulanzi D200 (USB HID),
  Loupedeck / Razer Stream Controller (USB serial, dials, touch), MIDI controllers such
  as Novation Launchpad / Akai APC (colour-only LED pads), DIY ESP32 decks. Drivers live in
  the bridge; the protocol already describes image keys, colour-only keys, dials and touch.
  The integration handles dials and touch strips; colour-only keys are still skipped with
  a warning.
- **More Elgato models**: Stream Deck + XL. The Studio can also be reached over the network
  (like the Network Dock); not used yet.

## Done

- Dock info page and simple dock automations (night brightness by time window or sun,
  fade out when idle with "first press only wakes") — 0.4.0
- Planning without any dock: "Only plan (no hardware yet)" entry in the config flow — 0.5.0
- Tests (pytest-homeassistant-custom-component, xUnit), CI with required checks,
  hassfest and HACS validation — 0.9.0b1

## Later

- Expose the behaviour to HA as well (e.g. a switch "fade out when idle", a "wake" button)
- Library split: move `protocol/` into its own PyPI package (needed for HA core)
- Bridge: TLS (`wss://`), log view in the desktop app
- Optional legal check of the terms of use
