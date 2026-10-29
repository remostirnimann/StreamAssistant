# Changelog

All notable changes to Stream Assistant. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are those of the
Home Assistant integration (`manifest.json`); since 0.8.0b1 the bridge is released with
the same version. Versions before 0.8.0b1 were not released.

## [0.9.0] - 2026-10-29

The first release that is not a beta: everything from 0.8.0b1 to 0.9.0b4 below. HACS
now offers it without *Show beta versions*. Elgato decks on USB are still untested on real
hardware (see [devices](https://github.com/remostirnimann/StreamAssistant/blob/main/docs/devices.md)).

### Changed

- Installation guide: HACS offers releases without beta versions turned on; how to get
  betas, and not to install a commit id HACS may offer instead of a version.

## [0.9.0b4] - 2026-10-29

### Added

- An icon: a deck with a house key and a dial. Home Assistant shows it for the
  integration (from 2026.3 on, in `brand/`, light and dark), and so does HACS.
- An icon for the bridge: the same keys with a badge of two arrows. The programs, their
  windows, the start menu entry and *Apps & features* show it.

## [0.9.0b3] - 2026-10-29

### Added

- Terms of use (`docs/terms.md`, in English and German): the bridge is meant for the local
  network, other use is at your own risk, and the software comes without warranty or
  liability. The Windows installer shows them with the licence to accept, `install.sh`
  asks for them (`--accept-terms` for installs without a terminal), and the status page
  links them.

### Changed

- The bridge only accepts connections from the local network: loopback, private and
  link-local addresses and `100.64.0.0/10` (VPNs such as Tailscale). Others get
  *403 Forbidden*. `--allow-public true` lifts this, at your own risk.

## [0.9.0b2] - 2026-10-28

### Fixed

- Bridge updates from Home Assistant failed with "Could not load file or assembly" when the
  bridge does not run as a service: the bridge replaced its own program file and then could
  not load the parts it still needed for the restart. It now loads them before, and puts the
  old files back if the update fails after all.

## [0.9.0b1] - 2026-10-27

### Added
- Bridge installers:
  - Windows: `stream-assistant-bridge-<version>-win-x64.msi` installs the bridge for all
    users as the service *Stream Assistant Bridge* (starts with Windows, restarts on
    failure), with a firewall rule and a start menu entry for the status page. Settings in
    `C:\ProgramData\Stream Assistant Bridge`, logged to `bridge.log` there.
  - Linux and macOS: `bridge/install.sh` downloads the matching release, checks its
    checksum and sets up a systemd service with its own user and udev rule (Linux) or a
    LaunchAgent (macOS); `--version`, `--uninstall`, `--purge`.
- Bridge updates from Home Assistant: an update entity per bridge offers the bridge
  version that matches the integration and installs it. The bridge downloads the release,
  checks it against `SHA256SUMS.txt`, replaces itself (or runs the new installer) and
  restarts; Home Assistant shows the progress and waits until it is back. The bridge's
  options can turn on automatic updates. Protocol: the `update` feature and command and the
  `update_status` event.
- User documentation in `docs/`: installation, setup, the bridge (download, start, pairing,
  autostart), devices with their test status, virtual and simulated panels, the key editor,
  automations and troubleshooting, with screenshots. `docs/images/README.md` lists every
  image, the ones still to take on a real Home Assistant or hardware, and how to make the
  others again (`scripts/docs_demo.py`, `scripts/docs-pages/`, English desktop screenshots
  with `SAB_TEST_LANGUAGE=en`).
- Bridge: USB drivers for the Stream Deck Neo and Studio (not yet tried on real hardware):
  - Neo: the two page buttons turn to the previous and next page and are lit when there is
    one; the info screen shows the page name and its number. Event entities per page button.
  - Studio: 32 keys of 144×112 (Home Assistant draws them square, the bridge centres them on
    black), two dials whose LED rings show the dial's colour and its entity's level, and the
    NFC reader: tags read there are Home Assistant tag scans (Tags integration).
  - Protocol: `buttons`, `screen`, `dials.ring` and `nfc` capabilities, the commands
    `set_button_color`, `set_screen_image` and `set_dial_leds`, the inputs `button` and `nfc`.
  - `--simulate` takes Elgato models by name (`mk2`, `xl`, `plus`, `mini`, `original`,
    `pedal`, `neo`, `studio`); the simulator page shows page buttons, screen, LED rings and
    can read NFC tags.
  - Free grids and templates can have up to 16 columns; templates for the Neo and Studio.
- Bridge: USB drivers for more Stream Decks, following the reference implementation
  node-elgato-stream-deck (not yet tried on real hardware):
  - Stream Deck +: keys, four dials (turn and push) and the touch strip (images per area;
    tap, hold and swipe).
  - Stream Deck Mini and 6 Module, and the first Stream Deck: BMP images, first-generation
    reports, the first Stream Deck's keys counted from the right.
  - Stream Deck Pedal: three keys without display.
  - The 15 and 32 key modules (like the MK.2 and XL).
  - Colours fill keys with one small report on decks that can, instead of an image.
- Keys without a display (pedals) in the protocol and the integration: they only press,
  get no images and no brightness entity, and pressing never only wakes the deck.
  `--simulate pedal` simulates one.
- Dials and touch strips (the groundwork for the Stream Deck +):
  - Every page has dials next to its keys. A dial shows its part of the touch strip (icon,
    title, state and a level bar for brightness, volume, position, temperature or values)
    and either adjusts its entity directly when turned (lights, covers, fans, media players,
    climate, numbers, selects; step per detent configurable) or runs one action per detent
    to the left or right. Pushing the dial or tapping/holding its segment runs the short
    and long actions. Fast turning is collected into one service call, starting from the
    value just set until the entity reports it.
  - Event entities per dial (turned left/right with the number of detents, pressed,
    released, short and long press) and for the touch strip (tap, long press, swipe left
    or right, with position and dial).
  - Editor: touch strip and dials below the keys, a dial form with turning mode, step and
    test buttons for both directions. Templates keep dials (`grid_4x2_d4`, `plus`).
  - Bridge: touch images (`set_touch_image`) and touch input; `--simulate plus` or
    `--simulate 4x2:4` simulate decks with dials, the simulator page turns, pushes, taps,
    holds and swipes; desktop virtual decks can have up to 6 dials.
- Bridge: Elgato USB driver for the Stream Deck MK.2, Original v2 and XL (HidSharp). Decks
  are found on their own and follow USB plugging (scan on plug events and every 5 s), several
  per computer. Key images are scaled, turned by 180° and sent as JPEG (StbImageSharp, fully
  managed, so the single-file builds need no native libraries), only the newest image per
  key is sent, and on exit the decks show the Elgato logo again. `--usb false` turns it off.
  Not yet verified with a real deck.
- Unit tests for the integration (pytest-homeassistant-custom-component, 91 tests, 94 %
  coverage) with a fake bridge and the simulated dock as real local servers.
- More bridge tests: mDNS packets and announcement, status and simulator pages, idle
  reset, driver failures and capability checks (47 tests, 93 % coverage).
- Quality checks in CI, required for every pull request: tests with at least 90 %
  coverage for the integration and the bridge, ruff (lint and format), .NET analyzers
  with warnings as errors and `dotnet format`.

### Changed
- mDNS packet code moved into `MdnsService`, separate from the socket handling.
- Line endings are LF everywhere (`.gitattributes`).

### Fixed
- Bridge as a service (systemd, launchd): it no longer hangs at start watching the whole
  disk. The working directory there is `/`, which ASP.NET took as its content root; the
  bridge now always uses its own folder.
- Up to 16 columns everywhere: the virtual panel form still said 1–12, the template dialog
  allowed 12 columns and no dials, and virtual decks in the bridge window allowed 12 columns.
- Key editor: the title of a dial's form no longer breaks over two lines.
- Pairing with a bridge on another port than 5390: the dialog pointed to `localhost:5390`
  instead of the bridge's port.
- The dashboard card's name in the card picker follows Home Assistant's language, not the
  browser's.
- A key that switches the page no longer runs the key at its place on the new page when it
  is released.
- The pairing connection to a bridge left a heartbeat timer running.
- Stored layouts are validated when loaded; a damaged one starts empty instead of failing
  later.
- Bridge on Windows: an unreachable mDNS asker no longer stops the announcements.
- Bridge: when mDNS multicast fails (no multicast route, e.g. in containers), direct
  queries are still answered instead of stopping mDNS.
- Bridge simulator page: closing the page's connection is confirmed properly.
- Bridge: the pairing code and simulator key ids are formatted culture independent.
- Release archives no longer contain native debug symbols (about 100 MB in the Windows
  desktop zip) or the empty static web assets list.

## [0.8.0b1] - 2026-10-24

First release on GitHub, as a beta (pre-release).

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
- `manifest.json` no longer lists Pillow; Home Assistant ships it (hassfest requires this).
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
