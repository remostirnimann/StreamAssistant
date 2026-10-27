# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Stream Assistant drives Elgato Stream Decks directly from Home Assistant, with all configuration in HA (no Stream Deck app, no Companion). It has two code bases:

- `custom_components/stream_assistant/`: the HA custom integration (Python, domain `stream_assistant`), shipped through HACS first and possibly HA core later.
- `bridge/`: the Stream Assistant Bridge (C#, .NET 10). It offers decks on a computer to HA over the vendor-neutral protocol in `docs/bridge-protocol.md`. The user chose .NET because Python is often missing on Windows, so do not write bridge code in Python.

`ROADMAP.md` holds the agreed order of work. `CHANGELOG.md` (Keep a Changelog, in English) gets entries with every committed change, under `[Unreleased]` or under the new version.

## Commands

Integration tests use pytest-homeassistant-custom-component (`requirements_test.txt`, Python 3.14 like HA 2026.10). Home Assistant does not run on Windows, so they run in WSL Ubuntu with the venv `~/.venvs/streamassistant`. From Git Bash, set `MSYS_NO_PATHCONV=1`, or paths get rewritten. Coverage must stay at 90 % or more (`pyproject.toml`), and ruff must pass:

```bash
wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/d/Projekte/StreamAssistant && ~/.venvs/streamassistant/bin/pytest'
wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/d/Projekte/StreamAssistant && ~/.venvs/streamassistant/bin/pytest tests/test_layout.py -k remap --no-cov'
wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/d/Projekte/StreamAssistant && ~/.venvs/streamassistant/bin/ruff check --fix . && ~/.venvs/streamassistant/bin/ruff format .'
```

The tests run the simulated dock (`scripts/fake_dock.py`, fixed port 5343) and `tests/fake_bridge.py` as real servers on 127.0.0.1. `tests/common.py` holds the entry helpers and `wait_for`.

Quick checks without HA use the Windows venv (`.venv`, Python 3.13 with Pillow, zeroconf and aiohttp):

```bash
.venv/Scripts/python.exe -m py_compile custom_components/stream_assistant/*.py custom_components/stream_assistant/protocol/*.py
.venv/Scripts/python.exe scripts/selftest_transport.py   # NetworkDockTransport against scripts/fake_dock.py
.venv/Scripts/python.exe scripts/selftest_bridge.py      # bridge client against the real bridge; run `dotnet build bridge` first
node --check custom_components/stream_assistant/frontend/panel.js
```

Bridge (`bridge/global.json` selects Microsoft.Testing.Platform; the tests use xUnit v3, pinned to 3.2.2 because Avalonia.Headless.XUnit needs it, and the coverage extension is pinned to 18.0.4 for the same platform version). Analyzer warnings are errors (`bridge/Directory.Build.props`, `bridge/.editorconfig`), and `dotnet format` must leave no changes:

```bash
dotnet test bridge
dotnet test --project bridge/tests/StreamAssistant.Bridge.Tests --filter-method "*Key_presses_are_reported"
dotnet format bridge --verify-no-changes
dotnet test bridge --coverage --coverage-output-format cobertura --coverage-output coverage.cobertura.xml
MSYS_NO_PATHCONV=1 .venv/Scripts/python.exe scripts/check_coverage.py --exclude /tests/ --exclude /obj/ bridge/tests/*/bin/Debug/net10.0/TestResults/coverage.cobertura.xml
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

## Branches, CI and releases

- `develop` is the default branch and the target of all pull requests; `main` only holds released states.
- Both branches are protected by a ruleset: changes only via PR, no force push, no deletion. Repository admins (the owner) may bypass it.
- Release tags `v*` cannot be moved or deleted.
- `.github/workflows/ci.yml` runs on every PR and push. Its jobs are required checks: *Integration*, *Tests*, *Lint*, *Bridge*, *Hassfest*, *HACS* and *Release check*.
- Every merge into `main` runs `.github/workflows/release.yml`, which builds `stream_assistant.zip` (HACS downloads it, see `hacs.json`) and the console and desktop bridge for all platforms. It tags `vX.Y.Z` and publishes a GitHub release whose notes are the changelog section. Versions like `0.8.0b1` become pre-releases.
- One version covers the integration and the bridge. The bridge is built with that version.
- To release:
  1. On `develop`, set the version in `manifest.json` and `const.py`.
  2. Rename `[Unreleased]` in `CHANGELOG.md` to `## [X.Y.Z] - YYYY-MM-DD`.
  3. Open a PR `develop → main` and merge it with a merge commit (not squash).
- `scripts/release_info.py` checks version and changelog (the *Release check* runs it on PRs into `main`).

## Integration architecture

**Device = one deck.** `device.py` `StreamAssistantDevice` owns:
- the layout (its own, or a linked template remapped to its grid) and its `Store`
- rendering and repainting
- key handling: long press after 0.5 s; a short press runs on press when no long action is set
- `BehaviorController` (night brightness, idle fade, a press that only wakes the deck)
- the entities' dispatcher signals

Dials share the press logic with keys (`_on_press`, keyed `("dial", index)`). Turning either runs `left`/`right` actions or adjusts the dial's entity (`actions.adjust_call`), collected for `DIAL_SETTLE_SECONDS` into one call. Each dial owns an equal part of the touch strip (`render_segment`, `display.page_dial_visual`); taps there run the dial's actions. Decks with LED rings (Studio) show the dial's colour and level there instead. Page buttons (Neo) turn to the previous/next page in layout order and are lit when there is one; the screen shows the page name. NFC reads become tag scans (`tag` is an after-dependency).

It never talks to hardware directly, only through a `DeckTransport` (`transport.py`):
- `NetworkDockTransport` (Elgato Network Dock, Cora over TCP, client in `protocol/`)
- `VirtualTransport` (HA-only virtual panel, consumed by the dashboard card)
- `BridgeDeckTransport` (in `bridge_hub.py`)

**Capabilities, not models.** `capabilities.py` `DeckCapabilities` (grid, key size, format, rotation, dials, touch strip) is what layout, rendering, templates and the editor use:
- Elgato models are mapped to it in the transport.
- Free grids have ids like `grid_5x3`, with dials `grid_4x2_d4` (virtual panels, templates, bridge decks).
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
- **Devices:** `IControlDevice` is implemented by `VirtualDevice` (desktop virtual decks and `--simulate` decks) and `Elgato/ElgatoDeck` (USB). `DeviceManager` raises `Added`/`Removed`/`Input` events. Drivers must return quickly and keep only the newest image per key.
- **USB:** `ElgatoModel` lists the supported Stream Decks; its `ElgatoFamily` (Original, Mini, Gen2, Plus, Pedal, Neo, Studio) decides image format and orientation, report layouts, feature reports and input parsing (`InputParser`), following node-elgato-stream-deck. `ElgatoWatcher` scans through `IHidBackend` (`HidSharpBackend` in production, excluded from coverage; `FakeHidBackend` in the tests) on plug events and every 5 s, and adds, removes and reopens decks. `KeyImages` converts images with StbImageSharp (fully managed; ImageSharp 4 needs a licence key for release builds and 3.x has known vulnerabilities).
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
- Work on a branch and open a PR into `develop` (`"C:/Program Files/GitHub CLI/gh.exe"`, not on the Bash PATH). Commit, push and merge only when the user asks. The main branch is `develop`; `origin` is the public GitHub repository `remostirnimann/StreamAssistant`, and `bitbucket` is the old Bitbucket repository, which is no longer updated.
- The developer has no physical access to the deck right now. Verify with simulations: `fake_dock.py`, `--simulate`, headless UI tests, and the camera `camera.g6_instant_high_resolution_channel` pointed at the real deck.
- Robustness and low support effort matter to the user. Prefer self-healing behaviour (reconnects, address following via mDNS/DHCP, reauth) over quick fixes.
