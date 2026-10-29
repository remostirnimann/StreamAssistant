# Installation

## Requirements

- **Home Assistant 2026.10** or later.
- One way to reach a deck (see [Devices and status](devices.md)):
  - an **Elgato Stream Deck Network Dock** with a Stream Deck, or
  - a **computer** (Windows, macOS or Linux) for the [Stream Assistant Bridge](bridge.md),
    with Stream Decks plugged in by USB, or
  - nothing at all, for a **virtual panel** on a dashboard.
- The Elgato Stream Deck app, Bitfocus Companion or other software must **not** use the
  same deck at the same time. A dock or a deck can only be driven by one program.

## Install with HACS (recommended)

Stream Assistant is not in the HACS default list yet; add it as a custom repository:

1. In Home Assistant open **HACS**.
2. Open the menu (⋮, top right) and choose **Custom repositories**.
3. Repository: `https://github.com/remostirnimann/StreamAssistant`, type: **Integration**. Add it.

   ![Adding the repository in HACS](images/ha-hacs-custom-repository.png)

4. Search for **Stream Assistant** in HACS, open it and choose **Download**. HACS
   offers the newest release (for example `v0.9.0`).

   To try beta versions as well (for example `v0.10.0b1`), turn on **Show beta
   versions** in the download dialog, or later in HACS with menu ⋮ → **Redownload**.
   HACS keeps this setting, so later betas show up as updates on their own. If HACS
   ever offers a commit id such as `51bd232` instead of a version, do not install it:
   that is the state of the development branch, not a release.
5. **Restart Home Assistant** (*Settings → System → Restart*).

Then continue with the [Setup](setup.md).

## Install by hand

1. Download `stream_assistant.zip` from the
   [releases page](https://github.com/remostirnimann/StreamAssistant/releases).
2. Unpack it into `config/custom_components/stream_assistant/` on your Home Assistant
   (the folder must contain `manifest.json` directly).
3. Restart Home Assistant.

## Updating

- **HACS:** HACS shows an update for Stream Assistant; install it and restart Home
  Assistant.
- **By hand:** replace the folder `config/custom_components/stream_assistant/` with the
  new release and restart.

Layouts, templates, behaviour settings and pairings are stored in Home Assistant and
kept across updates. After an update, reload the browser page once if the key editor
still shows the old version.

If you use the [bridge](bridge.md), update it to the same version: the integration and
the bridge are released together. Home Assistant offers the bridge update as an update
entity and can install it, also automatically (see [Updates](bridge.md#updates)).

## Removing

1. *Settings → Devices & services → Stream Assistant*: delete each entry. This also
   deletes the stored layouts of its decks. Templates are not part of an entry and stay
   stored; delete them in the key editor first if you no longer want them.
2. Remove the integration in HACS (or delete `config/custom_components/stream_assistant/`).
3. Restart Home Assistant.

The decks show the Elgato logo again when Home Assistant lets go of them.
