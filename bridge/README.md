# Stream Assistant Bridge

Offers control surfaces attached to a computer (Stream Decks, later devices of
other manufacturers) to Home Assistant over the network, without an Elgato
Network Dock. Protocol: [docs/bridge-protocol.md](../docs/bridge-protocol.md).

Status: protocol, pairing, discovery, simulated decks, the desktop app with
virtual decks and the Elgato USB driver are done. The USB driver still has to be
verified with a real deck.

## Projects

| Project | What |
|---|---|
| `src/StreamAssistant.Bridge.Core` | The bridge: protocol, devices, discovery, local pages |
| `src/StreamAssistant.Bridge` | Console program (`stream-assistant-bridge`), e.g. for servers and the HA add-on |
| `src/StreamAssistant.Bridge.Desktop` | Desktop program with a window (`stream-assistant-bridge-desktop`, Avalonia) |
| `tests/…` | Protocol tests and headless UI tests (xUnit v3, `dotnet test bridge`) |

## Desktop app

Same options as the console program. The window shows the connection to Home
Assistant and the pairing code, and hosts **virtual decks**: choose a name,
columns and rows; the deck appears in Home Assistant like a real Stream Deck
(keys, pages, templates, behaviour are set up there) and is pressed in the
window (hold for a long press). Virtual decks are stored in `bridge.json`.

## Run

```text
stream-assistant-bridge [--port 5390] [--name "Office PC"] [--config-dir <dir>]
                        [--simulate 5x3[,8x4...]] [--mdns false] [--usb false]
                        [--unpair-all]
```

- `http://localhost:5390/` shows the status and the **pairing code** (only on
  the computer itself). Home Assistant finds the bridge via mDNS; enter the
  code when adding it.
- `--simulate 5x3` adds a simulated deck; `http://localhost:5390/sim` shows
  it, presses keys (hold for a long press) and plugs it in and out.
- Settings (bridge id, paired clients) live in `bridge.json` in the config
  folder (default: `%APPDATA%\stream-assistant-bridge` on Windows,
  `~/.config/stream-assistant-bridge` elsewhere). Only one bridge can use a folder.
- `--usb false` turns the Stream Deck USB driver off.
- `--unpair-all` forgets all paired clients; Home Assistant then asks to pair again.

## Stream Decks on USB

Supported: Stream Deck MK.2, Original v2 and XL. Plug them in at any time; they
appear in Home Assistant as `elgato-<serial>`. The Elgato Stream Deck app must
not run at the same time (only one program can drive a deck). When a deck cannot
be opened, the bridge keeps trying and picks it up once it is free.

On Linux the user running the bridge needs access to the hidraw devices, e.g. with
`/etc/udev/rules.d/70-streamdeck.rules`:

```text
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0fd9", MODE="0660", TAG+="uaccess"
```

Then `sudo udevadm control --reload-rules && sudo udevadm trigger` and plug
the deck in again. The bridge also needs `libudev` (Alpine: `eudev-libs`).

## Build and test

```bash
dotnet test bridge
dotnet publish bridge/src/StreamAssistant.Bridge -c Release -r win-x64 -o dist/bridge-win-x64
dotnet publish bridge/src/StreamAssistant.Bridge.Desktop -c Release -r win-x64 -o dist/bridge-desktop-win-x64
```

Runtime identifiers: `win-x64`, `osx-arm64`, `osx-x64`, `linux-x64`,
`linux-arm64`, `linux-musl-arm64` / `linux-musl-x64` (Home Assistant add-on).
Each publish is one self-contained file; no .NET installation needed.

`scripts/selftest_bridge.py` tests the integration's bridge client against a
locally built bridge.
