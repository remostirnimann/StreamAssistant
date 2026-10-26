# Stream Assistant Bridge

The bridge is a small program for a computer with Stream Decks attached by USB. It offers
them to Home Assistant over the network, using the vendor-neutral
[bridge protocol](bridge-protocol.md). It does not draw anything itself: Home Assistant
decides what every key shows and does.

There are two versions, with the same features:

| Version | For |
|---|---|
| **Console** (`stream-assistant-bridge`) | Servers, Raspberry Pi, running in the background; no window |
| **Desktop** (`stream-assistant-bridge-desktop`) | Windows, macOS and Linux desktops; a window with the connection state, the pairing code and [virtual decks](virtual-panels.md#virtual-decks-in-the-bridge-window) |

Each is a single file and needs nothing else installed (no .NET, no Python).

## Download

Download the file for your computer from the
[releases page](https://github.com/remostirnimann/StreamAssistant/releases), in the same
version as the integration:

| Computer | Console | Desktop |
|---|---|---|
| Windows (64 bit) | `stream-assistant-bridge-<version>-win-x64.zip` | `stream-assistant-bridge-desktop-<version>-win-x64.zip` |
| macOS, Apple silicon | `…-osx-arm64.tar.gz` | `…-desktop-…-osx-arm64.tar.gz` |
| macOS, Intel | `…-osx-x64.tar.gz` | `…-desktop-…-osx-x64.tar.gz` |
| Linux, PC (64 bit) | `…-linux-x64.tar.gz` | `…-desktop-…-linux-x64.tar.gz` |
| Linux, Raspberry Pi (64 bit) and other ARM | `…-linux-arm64.tar.gz` | `…-desktop-…-linux-arm64.tar.gz` |
| Alpine Linux (e.g. Home Assistant OS add-ons) | `…-linux-musl-x64.tar.gz` / `…-linux-musl-arm64.tar.gz` | – |

`SHA256SUMS.txt` lists the checksums of all files.

## Install and start

### Windows

1. Unpack the zip into a folder of your choice, for example `C:\Program Files\Stream Assistant Bridge`.
2. Start `stream-assistant-bridge-desktop.exe` (or `stream-assistant-bridge.exe` in a
   terminal).
3. The files are not signed yet: Windows SmartScreen may warn. Choose *More info → Run anyway*.
4. When the Windows firewall asks, allow access for **private networks**. Home Assistant
   connects on TCP port 5390, and the bridge announces itself via mDNS (UDP 5353).

### macOS

```bash
mkdir -p ~/Applications/StreamAssistantBridge
tar -xzf stream-assistant-bridge-desktop-<version>-osx-arm64.tar.gz -C ~/Applications/StreamAssistantBridge
xattr -dr com.apple.quarantine ~/Applications/StreamAssistantBridge
~/Applications/StreamAssistantBridge/stream-assistant-bridge-desktop
```

The `xattr` line is needed because the files are not signed yet; without it macOS refuses
to start them. If macOS asks for permission to accept incoming network connections, allow it.

### Linux

```bash
sudo mkdir -p /opt/stream-assistant-bridge
sudo tar -xzf stream-assistant-bridge-<version>-linux-x64.tar.gz -C /opt/stream-assistant-bridge
/opt/stream-assistant-bridge/stream-assistant-bridge
```

For Stream Decks on USB the bridge needs access to the HID devices. Create
`/etc/udev/rules.d/70-streamdeck.rules` with:

```text
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0fd9", MODE="0660", TAG+="uaccess"
```

then run `sudo udevadm control --reload-rules && sudo udevadm trigger` and plug the
decks in again. `TAG+="uaccess"` gives the logged-in user access; for a bridge running
as a service under its own user, use `MODE="0666"` or a group (`GROUP="plugdev"`)
instead. The bridge also needs `libudev` (installed on almost every distribution;
Alpine: `apk add eudev-libs`).

## First start and pairing

When the bridge starts, it

- creates its settings (`bridge.json`) with a unique bridge id,
- shows a **6-digit pairing code**: in the desktop window, in the console log, and on the
  status page `http://localhost:5390` (only on that computer),
- announces itself in the network, so Home Assistant finds it.

![The bridge window with the pairing code](images/bridge-desktop-pairing.png)

Add it in Home Assistant as described in [Setup](setup.md#stream-assistant-bridge).
After 5 wrong codes the bridge waits a minute before it accepts codes again.

One Home Assistant is connected at a time. If a second one connects, it takes over and
the first one is disconnected and tries again later, so two Home Assistant instances would
keep taking turns: pair a bridge with one Home Assistant only.

## Options

Options are given on the command line (also for the desktop version, for example in a
shortcut):

| Option | Default | What it does |
|---|---|---|
| `--name "Office PC"` | computer name | Name shown in Home Assistant |
| `--port 5390` | 5390 | TCP port for Home Assistant and the status page |
| `--config-dir <folder>` | see below | Where `bridge.json` is kept. Only one bridge can use a folder at a time |
| `--usb false` | on | Turns the Stream Deck USB driver off (for example on a computer that only offers virtual decks) |
| `--mdns false` | on | Turns the network announcement off; add the bridge in Home Assistant by address |
| `--simulate 5x3,plus` | – | Adds [simulated decks](virtual-panels.md#simulated-decks) for testing |
| `--unpair-all` | – | Forgets all paired Home Assistant instances; they must pair again |

The settings folder is `%APPDATA%\stream-assistant-bridge` on Windows and
`~/.config/stream-assistant-bridge` on macOS and Linux. It holds the bridge id, the
paired clients (only hashes of their tokens), the bridge name and the virtual decks. Keep
it when you update the bridge, otherwise Home Assistant has to pair again and sees a new bridge.

## Stream Decks on USB

- Plug decks in or out at any time; they appear in Home Assistant within a few seconds.
- Several decks per computer are fine. Each deck is known by its serial number, so it
  keeps its layout when it moves to another USB port.
- **Close the Elgato Stream Deck app** (also in the tray / menu bar) and Companion: a deck
  can be driven by only one program. When a deck is busy, the bridge keeps trying and takes
  it over once it is free.
- When the bridge ends, the decks show the Elgato logo again.

Which models are supported, and how far they are tested, is listed in
[Devices and status](devices.md).

## Start automatically

### Windows

Press <kbd>Win</kbd>+<kbd>R</kbd>, enter `shell:startup` and put a shortcut to
`stream-assistant-bridge-desktop.exe` into the folder that opens. Add options to the
shortcut's target if needed.

### macOS

Save as `~/Library/LaunchAgents/ch.streamassistant.bridge.plist` (adjust the path):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ch.streamassistant.bridge</string>
  <key>ProgramArguments</key>
  <array><string>/Users/YOU/Applications/StreamAssistantBridge/stream-assistant-bridge</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

Then `launchctl load ~/Library/LaunchAgents/ch.streamassistant.bridge.plist`.

### Linux (systemd)

Save as `/etc/systemd/system/stream-assistant-bridge.service`:

```ini
[Unit]
Description=Stream Assistant Bridge
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/stream-assistant-bridge/stream-assistant-bridge --config-dir /var/lib/stream-assistant-bridge
Restart=always
DynamicUser=yes
StateDirectory=stream-assistant-bridge
SupplementaryGroups=plugdev

[Install]
WantedBy=multi-user.target
```

Then `sudo systemctl enable --now stream-assistant-bridge`. With `DynamicUser` the udev
rule needs a group the service is in, for example `GROUP="plugdev"` (see above; create the
group if your distribution has none). The pairing code is in the log:
`journalctl -u stream-assistant-bridge`.

## Status page

`http://<computer>:5390/` shows the bridge name and id, whether Home Assistant is
connected, and the decks. The pairing code and the settings folder are shown only when the
page is opened on the computer itself.

![The bridge status page](images/bridge-status-page.png)

`http://localhost:5390/sim` is the
[simulator](virtual-panels.md#simulated-decks) (only on that computer).
