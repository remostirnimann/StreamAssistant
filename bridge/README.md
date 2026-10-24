# Stream Assistant Bridge

Offers control surfaces attached to a computer (Stream Decks, later devices of
other manufacturers) to Home Assistant over the network, without an Elgato
Network Dock. Protocol: [docs/bridge-protocol.md](../docs/bridge-protocol.md).

Status: protocol, pairing, discovery and a simulated deck are done. The Elgato
USB driver comes next.

## Run

```text
stream-assistant-bridge [--port 5390] [--name "Office PC"] [--config-dir <dir>]
                        [--simulate 5x3[,8x4...]] [--mdns false] [--unpair-all]
```

- `http://localhost:5390/` shows the status and the **pairing code** (only on
  the computer itself). Home Assistant finds the bridge via mDNS; enter the
  code when adding it.
- `--simulate 5x3` adds a simulated deck; `http://localhost:5390/sim` shows
  it, presses keys (hold for a long press) and plugs it in and out.
- Settings (bridge id, paired clients) live in `bridge.json` in the config
  folder (default: `%APPDATA%\stream-assistant-bridge` on Windows,
  `~/.config/stream-assistant-bridge` elsewhere). Only one bridge can use a folder.
- `--unpair-all` forgets all paired clients; Home Assistant then asks to pair again.

## Build and test

```bash
dotnet test bridge
dotnet publish bridge/src/StreamAssistant.Bridge -c Release -r win-x64 -o dist/bridge-win-x64
```

Runtime identifiers: `win-x64`, `osx-arm64`, `osx-x64`, `linux-x64`,
`linux-arm64`, `linux-musl-arm64` / `linux-musl-x64` (Home Assistant add-on).
Each publish is one self-contained file; no .NET installation needed.

`scripts/selftest_bridge.py` tests the integration's bridge client against a
locally built bridge.
