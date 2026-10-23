# Roadmap

## Next

- **Documentation and HACS beta release**: user documentation (installation, setup,
  editor, templates, actions, troubleshooting), screenshots, `info.md`/README for HACS,
  GitHub releases with version tags, published first as a **beta** (pre-release) to
  collect feedback while development continues.
- **Dock info page** in the editor: the most important facts per dock: model, serial
  numbers, firmware of dock and deck, IP/MAC, connection state and uptime, brightness,
  linked template, key count, current page.
- **Simple dock automations** configurable per dock, without writing HA automations:
  - lower the brightness at night (time window or sun based)
  - screen off until a key is pressed: first press only wakes the deck (no action),
    then it fades out again after a configurable time
- Planning without any dock: allow using the editor (templates) before the first dock
  is set up.

## Later

- Library split: move `protocol/` into its own PyPI package (needed for HA core)
- More models: Stream Deck Plus (dials, touch strip), Neo, Studio
- Tests (pytest-homeassistant-custom-component), CI, hassfest/HACS validation
