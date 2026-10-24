# Changelog

All notable changes to Stream Assistant. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are those of the
Home Assistant integration (`manifest.json`); the bridge has its own version, noted
where it changed. Nothing has been released yet.

## [Unreleased]

### Added
- Bridge: **desktop program** (`stream-assistant-bridge-desktop`, Avalonia) with a window
  showing the Home Assistant connection and the pairing code, and **virtual decks** of
  any grid (1–12 × 1–8). Home Assistant drives them like real decks; keys are clicked or
  held in the window, brightness dims them, *identify* makes the deck flash.
- Bridge: virtual decks are stored in `bridge.json` and come back after a restart.
- Bridge: headless UI tests that also save screenshots.
- `CHANGELOG.md` and `CLAUDE.md` (commands and architecture for Claude Code).
- MIT license (`LICENSE`); the bundled fonts stay under Apache 2.0.
- CI on every pull request: integration checks with both self tests, bridge tests,
  hassfest, HACS validation, and a release check for pull requests into `main`.
- Release pipeline. Every merge into `main` builds the integration zip and the console
  and desktop bridge for Windows, macOS and Linux, tags `vX.Y.Z` and publishes a GitHub
  release with the changelog section and SHA-256 checksums. `a`/`b`/`rc` versions become
  pre-releases.
- `scripts/release_info.py`: checks that `manifest.json`, `const.py` and `CHANGELOG.md` agree.

### Changed
- The repository moved from Bitbucket to GitHub (`remostirnimann/StreamAssistant`), with its full history.
- `develop` and `main` are protected: changes only through pull requests. Release tags are protected.
- HACS installs the release zip (`zip_release`) and needs Home Assistant 2026.10 or later.
- One version for the integration and the bridge per release.
- Bridge split into `StreamAssistant.Bridge.Core` (library), the console program and the
  desktop program; `BridgeHost` builds and prepares the bridge for both.
- Bridge: `bridge.json` keeps umlauts readable.
- Bridge: test projects moved to xUnit v3 (needed by Avalonia's headless tests).
- README and roadmap describe the Network Dock, the bridge, the desktop app and virtual
  panels; the roadmap was reordered with the current status.

### Removed
- `poc/`: the Node.js proof of concept of the dock protocol; the Python client,
  `scripts/fake_dock.py` and `scripts/live_test.py` replace it.

## [0.7.0] - 2026-10-24

### Added
- **Bridge protocol specification** ([docs/bridge-protocol.md](docs/bridge-protocol.md)),
  version 1, vendor-neutral:
  - WebSocket transport, with JSON for commands and a binary envelope for images.
  - Pairing with a 6-digit code and a long-lived token.
  - mDNS discovery (`_stream-assistant._tcp`).
  - Capabilities: image keys, colour-only keys, dials, touch.
  - Hot-plug with stable device ids, one active client, full resync after reconnecting.
- **Stream Assistant Bridge 0.1.0** (.NET 10, single-file builds):
  - Pairing service: tokens are stored as hashes; pairing locks for a minute after 5 wrong codes.
  - mDNS advertiser.
  - Status page; the pairing code is shown only on the computer itself.
  - Simulated decks (`--simulate 5x3`) with a simulator page for pressing keys and
    plugging decks in and out.
  - Decks fall back to their idle screen 30 s after the client left.
  - 17 protocol tests.
- Integration: **bridge config entries**:
  - Found via mDNS or added by address; paired with the code the bridge shows.
  - Home Assistant asks for a new code (reauth) when the bridge no longer accepts the token.
  - One entry per bridge. Every deck on it is its own device with its own layout,
    entities and behaviour, below a bridge device with its own connection sensor.
  - Decks appear at runtime when they are plugged in. Known decks are remembered, so
    their entities exist while the bridge is offline.
  - The editor's info page shows the bridge name, version, address and connection.
- `scripts/selftest_bridge.py`: tests the integration's bridge client against the real bridge.
- `scripts/sim_probe.py`: shows and presses simulated keys from the command line on the HA host.

### Changed
- Decks are addressed by a key (the entry id, or `<entry id>.<device id>` for bridge
  decks) in signals, storage and the WebSocket API, so one entry can hold several decks.
- The render cache also tells key sizes apart, because free grids share ids across sizes.

### Fixed
- Bridge: a second instance using the same settings folder is refused (it shared the port
  on Linux).
- Bridge: shutting down closes open connections at once instead of waiting up to 30 s.
- Bridge: mDNS no longer offers container, VM and VPN addresses. Answers use the address
  in the asker's network, so Home Assistant no longer picks an unreachable one.

## [0.6.1] - 2026-10-24

### Added
- Removing a config entry also deletes its stored layout and behaviour.

## [0.6.0] - 2026-10-24

### Added
- **Virtual panel** config entry: a deck that only exists in Home Assistant.
  - Any grid of columns × rows (1–12 × 1–8) instead of a fixed model.
  - Keys, pages, templates and behaviour work as on a real deck.
  - The grid can be changed later (*Reconfigure*). Keys keep their row and column, and
    key entities outside the new grid are removed.
- **Dashboard card** `custom:stream-assistant-card`, loaded automatically and listed in the
  card picker, with a card editor:
  - Live key images and brightness.
  - Press or hold keys; holding is a long press.
  - Reconnects by itself when the panel is reloaded.
- WebSocket commands `panel/list`, `panel/subscribe` and `panel/press` for the card, open to
  all users (view and press only).
- Templates can use a free grid.
- The editor's info page shows the grid of virtual panels.

## [0.5.1] - 2026-10-23

### Added
- Capabilities layer (`capabilities.py`): a vendor-neutral deck description (grid, key size,
  image format, rotation). Rendering, templates, the editor and the WebSocket API use it.
- Transport layer (`transport.py`): the `DeckTransport` interface, with the Network Dock as
  its first implementation.
- `scripts/fake_dock.py`: a simulated Network Dock with an MK.2 that speaks the real
  Cora protocol.
- `scripts/selftest_transport.py`: a hardware-free test of the transport against the fake dock.

### Changed
- Roadmap: the bridge gets a neutral protocol and is written in .NET (C#).

## [0.5.0] - 2026-10-23

### Added
- Planning without hardware: the config flow starts with a menu (dock or *only plan*).
  The planning entry only loads the editor so templates can be designed before any
  hardware exists.
- The editor's empty state points to templates when no dock exists.

### Changed
- Roadmap: bridge ("virtual dock"), vendor-neutral protocol, virtual Stream Deck and more
  manufacturers.

## [0.4.3] - 2026-10-23

### Fixed
- The info view hid the key *Save/Discard* buttons by mistake; behaviour has its own save.
- Unsaved behaviour is no longer lost without asking when switching deck, template or view.
- Empty or out-of-range number and time fields are flagged instead of becoming 0.
- Invalid stored behaviour falls back to defaults instead of breaking setup.
- Reconnecting wakes the deck and restarts the idle time.
- All `stream_assistant/*` WebSocket commands are admin-only.

## [0.4.2] - 2026-10-23

### Added
- **Info & behaviour** view per dock, in the header tabs and refreshed live:
  - Facts: serials, firmware, IP/MAC, connection and uptime, brightness (set/now), layout.
  - Night brightness by time window (also across midnight) or by sunset.
  - Fade out when idle: dim or turn off after a timeout, always, only at night or in an
    own time window.
  - Optionally the first press only wakes the deck (no action, no events).
- WebSocket commands `info` and `behavior/set`.

## [0.3.0] - 2026-10-23

### Added
- **Templates** (planned decks): layouts with a model but no hardware, edited in the panel
  with live preview and *run* buttons.
- Decks can be linked to a template (shared layout) or detached into their own copy.
  Deleting a template leaves the linked decks a copy.
- Layouts move between deck sizes by row and column. Edits on a smaller deck only replace
  the visible part of a bigger template.
- Shared render cache for decks and templates.
- `ROADMAP.md`.

## [0.2.3] - 2026-10-23

### Added
- **Key editor** panel in the sidebar (admins only):
  - Entity picker with area, device and type filters.
  - Visual icon picker and live preview of the real rendered keys.
  - Page management.
  - *Run* buttons that simulate a key press, also for unsaved edits.
  - Conflict detection when saving.
- **Layout model** with pages and folders (the first key of a folder is *back*). Per key:
  entity, title, icons for on and off, second line, colours, and short and long press
  actions. Storage version 2 migrates the `set_key` data.
- Keys follow their entity live, with default icons per domain and state.
- Bundled MDI font and Roboto Medium (Apache 2.0) for rendering.
- Actions:
  - Automatic per domain (toggle, trigger, play/pause …).
  - Any action with data.
  - Open page or folder, and back.
  - A short press runs on press when no long press is set.
- WebSocket API `stream_assistant/*` for the panel.
- Scripts: key render sheet, and a stdlib WebSocket probe for the HA host.

### Changed
- Replaced the deprecated `via_device` and `async_get_device` (HA 2026.10).

## [0.1.1] - 2026-10-22

### Added
- The dock gets its own *Connected* sensor; the deck sensor moved to the deck device.
- The dock MAC is taken from the mDNS announcement and attached to the dock device.
- DHCP discovery for registered devices follows new leases of a known dock. mDNS keeps
  host and MAC up to date as well.

## [0.1.0] - 2026-10-22

### Added
- First version: Home Assistant custom integration that talks to an Elgato Stream Deck
  Network Dock directly over TCP (Cora framing), without the Stream Deck app or Companion.
- Home Assistant independent protocol client:
  - Dock and attached deck, with keepalives, reconnect and hot-plug.
  - Gen2 models MK.2 (tested), Original v2 and XL.
- Config flow with mDNS discovery (`_elg._tcp`, `dt=215`) and manual IP.
- One event entity per key (`pressed`, `released`, `short_press`, `long_press`), a
  brightness number and a connectivity sensor.
- Actions `set_key` and `clear_key`; the layout is stored and repainted after reconnects.
- Node.js proof of concept (`poc/`) and a live test script.
