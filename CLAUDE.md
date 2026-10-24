# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Stream Assistant drives Elgato Stream Decks directly from Home Assistant, with all configuration in HA (no Stream Deck app, no Companion). It has two code bases:

- `custom_components/stream_assistant/`: the HA custom integration (Python, domain `stream_assistant`), shipped through HACS first and possibly HA core later.
- `bridge/`: the Stream Assistant Bridge (C#, .NET 10). It offers decks on a computer to HA over the vendor-neutral protocol in `docs/bridge-protocol.md`. The user chose .NET because Python is often missing on Windows, so do not write bridge code in Python.

`ROADMAP.md` holds the agreed order of work. `CHANGELOG.md` (Keep a Changelog, in English) gets entries with every committed change, under `[Unreleased]` or under the new version.

## Commands

The integration has no build step and no pytest suite yet. Hardware-free checks use the local venv (`.venv`, Python 3.13 with Pillow, zeroconf and aiohttp):

```bash
.venv/Scripts/python.exe -m py_compile custom_components/stream_assistant/*.py custom_components/stream_assistant/protocol/*.py
.venv/Scripts/python.exe scripts/selftest_transport.py   # NetworkDockTransport against scripts/fake_dock.py
.venv/Scripts/python.exe scripts/selftest_bridge.py      # bridge client against the real bridge; run `dotnet build bridge` first
node --check custom_components/stream_assistant/frontend/panel.js
```

Bridge (`bridge/global.json` selects Microsoft.Testing.Platform; the tests use xUnit v3, pinned to 3.2.2 because Avalonia.Headless.XUnit needs it):

```bash
dotnet test bridge
dotnet test --project bridge/tests/StreamAssistant.Bridge.Tests --filter-method "*Key_presses_are_reported"
dotnet run --project bridge/src/StreamAssistant.Bridge -- --simulate 5x3 --config-dir <dir>
dotnet publish bridge/src/StreamAssistant.Bridge -c Release -r linux-musl-arm64 -o dist/bridge-linux-musl-arm64
dotnet publish bridge/src/StreamAssistant.Bridge.Desktop -c Release -r win-x64 -o dist/bridge-desktop-win-x64
```

A publish with `-r` gives one self-contained file. The desktop UI tests save screenshots to `bridge/tests/StreamAssistant.Bridge.Desktop.Tests/bin/Debug/net10.0/screenshots/`.

### Deploying to the test Home Assistant

The HA host is a Home Assistant Yellow at 172.16.254.2, reached through the SSH add-on with `~/.ssh/id_ed25519_ha`. The SSH add-on runs Alpine on aarch64. Deploy with:

```bash
cd custom_components && tar --exclude=__pycache__ -cf - stream_assistant | ssh -i ~/.ssh/id_ed25519_ha -o IdentitiesOnly=yes -o BatchMode=yes root@172.16.254.2 'tar -xf - -C /config/custom_components && ha core restart'
```

- Python changes need a full core restart.
- Bump `VERSION` in `const.py` and `version` in `manifest.json` together. The panel and card URLs carry `?v=VERSION` for cache busting.
- Read live state on the host with curl against `http://supervisor/core/api` and `$SUPERVISOR_TOKEN`.
- `scripts/ws_probe.py` (copy it to `/tmp` on the host) calls the `stream_assistant/*` WebSocket commands.
- `scripts/sim_probe.py` presses the keys of simulated bridge decks from the command line.
- HA cannot reach the developer PC (different subnet), so a test bridge runs on the HA host as the `linux-musl-arm64` build.
- Stop the test bridge with `kill $(pidof stream-assistant-bridge)`. Never use `pkill -f`, which also kills the SSH session.

## Integration architecture

**Device = one deck.** `device.py` `StreamAssistantDevice` owns:
- the layout (its own, or a linked template remapped to its grid) and its `Store`
- rendering and repainting
- key handling: long press after 0.5 s; a short press runs on press when no long action is set
- `BehaviorController` (night brightness, idle fade, a press that only wakes the deck)
- the entities' dispatcher signals

It never talks to hardware directly, only through a `DeckTransport` (`transport.py`):
- `NetworkDockTransport` (Elgato Network Dock, Cora over TCP, client in `protocol/`)
- `VirtualTransport` (HA-only virtual panel, consumed by the dashboard card)
- `BridgeDeckTransport` (in `bridge_hub.py`)

**Capabilities, not models.** `capabilities.py` `DeckCapabilities` (grid, key size, format, rotation) is what layout, rendering, templates and the editor use:
- Elgato models are mapped to it in the transport.
- Free grids have ids like `grid_5x3` (virtual panels, templates, bridge decks).
- The render cache key includes the key size, because grid ids are shared across sizes.

**Entry kinds** (`CONF_KIND`), set up in `__init__.py`:
- `dock` (default): `runtime_data` is a `StreamAssistantDevice`.
- `virtual`: also a `StreamAssistantDevice`.
- `bridge`: `runtime_data` is a `BridgeHub` holding several devices, created at runtime as decks appear. Known decks are kept in `entry.data["devices"]`, so their entities exist while offline.
- `planner`: `runtime_data` is `None`; the entry only loads the editor.

**Addressing:** a deck is addressed by `device.key`: the entry id, or `"<entry_id>.<device_id>"` for bridge decks. The key is used in dispatcher signals, `Store` keys and the WebSocket field `entry_id`. Platforms obtain decks through `entity.async_setup_decks()`, which also handles decks added later (`signal_new_device`).

**WebSocket API** (`websocket.py`):
- Editor commands are `require_admin`. They target `entry_id` (deck key) or `template_id`, and saves carry a layout `revision` for conflict detection.
- `panel/*` commands serve the dashboard card and are open to all users, but only for virtual panels.

**Templates** (`templates.py`) are integration-wide layouts with a model:
- Linked decks subscribe and edit the template.
- `remap_layout` and `merge_into_template` (`layout.py`) move keys between grids by row and column.

**Frontend:**
- `frontend/panel.js`: the editor (sidebar panel, admins only).
- `frontend/card.js`: `custom:stream-assistant-card`, registered via `add_extra_js_url`.
- Both are plain web components without a build step. They use HA CSS variables and German/English text tables.

Use `via_device_id` instead of the `via_device`/`async_get_device` APIs deprecated in HA 2026.10. Removing an entry deletes its layout stores (`async_remove_entry`).

## Bridge architecture

The code is split into three projects:
- `StreamAssistant.Bridge.Core`: everything that matters. `Hosting/BridgeHost` builds the ASP.NET app, and `Prepare()` takes the settings lock, attaches devices and logs the pairing code.
- `StreamAssistant.Bridge`: thin console program, also intended for the HA add-on.
- `StreamAssistant.Bridge.Desktop`: Avalonia 12 window, code-only (no XAML). It hosts `BridgeHost` in-process and shows `VirtualDecks`.

A self-contained exe cannot reference another exe, so shared code goes into Core.

Inside Core:
- **Devices:** `IControlDevice` is implemented by `VirtualDevice` (desktop virtual decks and `--simulate` decks), and later by vendor USB drivers. `DeviceManager` raises `Added`/`Removed`/`Input` events. Drivers must return quickly and keep only the newest image per key.
- **Protocol:**
  - `BridgeServer` keeps one active `ClientSession`; a new client replaces the old one, and devices reset to the idle screen 30 s after the client left.
  - `ClientSession` does the handshake, pairing or token check, commands and binary image envelopes.
  - `PairingService` stores token hashes in `bridge.json` and locks pairing after 5 wrong codes.
- **Settings:** `SettingsStore` writes `bridge.json` atomically and holds `bridge.lock`, so one instance per config folder.
- **Discovery:** `MdnsAdvertiser` is a minimal mDNS responder. It skips virtual adapters and answers with the address in the asker's subnet.
- **Local pages:** `/` (status; the pairing code appears only for loopback) and `/sim` (simulator, loopback only).

Integration side of the protocol: `protocol/bridge.py` holds `BridgeClient`, `fetch_info` and `pair` (aiohttp, HA-independent), and `bridge_hub.py` maps the client onto devices.

## Working conventions

- The user writes Swiss German (no ß). Answer in German. Code, comments and repo docs are in English.
- Commit and push only when the user asks. The main branch is `develop`; `origin` is the public GitHub repository `remostirnimann/StreamAssistant`, and `bitbucket` is the old Bitbucket repository, which is no longer updated.
- The developer has no physical access to the deck right now. Verify with simulations: `fake_dock.py`, `--simulate`, headless UI tests, and the camera `camera.g6_instant_high_resolution_channel` pointed at the real deck.
- Robustness and low support effort matter to the user. Prefer self-healing behaviour (reconnects, address following via mDNS/DHCP, reauth) over quick fixes.
