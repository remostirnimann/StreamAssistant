# Troubleshooting

## Network Dock

**The dock is not found / "Cannot connect to the dock".**
- Is another program connected to it? The Elgato Stream Deck app (on any computer in the
  network) or Companion keeps the dock busy; close it. A dock accepts one client only.
- Add it by IP address (*Stream Deck Network Dock* in the menu). The dock's address is in
  your router's device list.
- Home Assistant and the dock must be in the same network for discovery (mDNS). By address
  it also works across networks, as long as TCP port 5343 of the dock is reachable.

**The dock is connected, but the deck stays unavailable.**
The deck is not plugged in or not supported by the dock (see [Devices](devices.md)). Plug it
in again; the entry picks it up within a few seconds.

**The dock got a new IP address.**
Nothing to do: the integration follows the dock by its serial number (mDNS and DHCP).

## Bridge

**Home Assistant does not find the bridge.**
- Is the bridge running? `http://localhost:5390` on that computer shows its status.
- Firewall: allow the bridge in *private* networks (TCP 5390 and mDNS, UDP 5353).
- Different networks or VLANs: mDNS does not cross them. Add the bridge by address
  (*Stream Assistant Bridge* in the menu).

**"Wrong pairing code".**
Use the code currently shown by the bridge. After 5 wrong codes it waits a minute.

**Home Assistant asks to pair again.**
The bridge forgot Home Assistant: its settings folder was deleted or moved, or it was started
with `--unpair-all`. Enter the new code. Keep the settings folder when updating the bridge.

**"Another bridge is already running with the settings in …".**
Only one bridge can use a settings folder. Close the other one (also check the tray /
background), or start a second one with its own `--config-dir` and `--port`.

**A deck on USB does not appear.**
- Close the Elgato Stream Deck app, also in the tray / menu bar, and Companion. The bridge
  takes the deck over as soon as it is free and writes a warning to its log meanwhile.
- Linux: set up the udev rule ([bridge](bridge.md#desktop-version-and-manual-install); the install script does this itself) and plug the deck in again.
- Is the model supported? See [Devices](devices.md). Unsupported models are ignored.
- The bridge log lists every deck it attaches: `Device attached: Stream Deck MK.2 (elgato-…)`.

**Two Home Assistant instances keep taking the bridge from each other.**
A bridge serves one Home Assistant at a time. Pair it with one only.

## Keys and editor

**A key shows "unavailable".**
Its entity is unavailable or does not exist (renamed?). Choose the entity again in the editor.

**The editor shows an old version after an update.**
Reload the browser page (on phones: close and reopen the app).

**"The layout was changed elsewhere".**
Someone saved the same deck or template in another window. *Discard* loads the current
version; your unsaved changes there are lost.

**A press does nothing the first time.**
*Fade out when idle* with *First press only wakes* is on: the first press only lights the
deck up. Turn the option off in [behaviour](editor.md#info-and-behaviour) if you do not want it.

**A dial does not change the entity.**
*Turning* must be *Adjust the entity*, and the dial needs an entity that can be adjusted
(light, media player, cover, fan, climate, number, select). The editor tells you when it
cannot.

**Images or icons look wrong on a deck.**
Please [open an issue](https://github.com/remostirnimann/StreamAssistant/issues) with the
model and a photo: most models are not tested on real hardware yet ([status](devices.md)).

## Logs

For a bug report, turn on debug logging for a while (*Settings → Devices & services →
Stream Assistant → Enable debug logging*) or in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.stream_assistant: debug
```

The bridge writes its log to the console (console version) or the terminal it was started
from; as a service, see `journalctl -u stream-assistant-bridge`.
