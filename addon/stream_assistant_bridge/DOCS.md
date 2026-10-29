# Stream Assistant Bridge

The bridge offers the Stream Decks plugged into this Home Assistant host to the
[Stream Assistant](https://github.com/remostirnimann/StreamAssistant) integration. You
design the keys in Home Assistant, in the Stream Assistant editor in the sidebar.

## Setup

1. Install the **Stream Assistant** integration through HACS first, and restart Home
   Assistant ([installation](https://github.com/remostirnimann/StreamAssistant/blob/main/docs/installation.md)).
2. Install this add-on and start it.
3. Under **Settings → Devices & services**, Home Assistant shows *Stream Assistant Bridge
   add-on* as discovered. Choose **Add** and confirm. No pairing code is needed: the
   add-on hands Home Assistant a token through the Supervisor.
4. Plug in a Stream Deck. It appears as a device of the bridge; open the Stream Assistant
   editor in the sidebar to design its keys.

## Options

- **Name**: how the bridge appears in Home Assistant.
- **Simulated decks**: decks for trying without hardware, for example `5x3`, `4x2:4`
  (with four dials) or Elgato models such as `mk2,plus,neo`. Press their keys on the
  add-on's page (**Open Web UI**, then *Open the simulator*).
- **Log level**: `debug` writes every message, useful when reporting a problem.

## The add-on's page

**Open Web UI** (or **Show in sidebar**) shows the bridge's status: whether Home
Assistant is connected, the decks it found, and the pairing code for a Home Assistant on
another computer.

## Stream Decks on USB

The add-on uses raw USB access and follows plugging in and out. All current Elgato
models are supported; see the
[device list](https://github.com/remostirnimann/StreamAssistant/blob/main/docs/devices.md)
for which ones were tried on real hardware. The Elgato Stream Deck software must not be
running for the deck (it is not, on a Home Assistant host).

## Another Home Assistant

This Home Assistant connects to the bridge on the add-on network. For a Home Assistant
on another computer, open the port **5390** in the add-on's network settings, add the
bridge there by address, and pair it with the code on the add-on's page.

## Updates

The add-on is updated like any other add-on. Keep it on the same version as the
integration: both are released together.

## Terms of use

The bridge is meant for the local network; see the
[terms of use](https://github.com/remostirnimann/StreamAssistant/blob/main/docs/terms.md).
