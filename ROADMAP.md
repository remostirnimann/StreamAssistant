# Roadmap

## Next

- **Documentation and HACS beta release**: user documentation (installation, setup,
  editor, templates, actions, troubleshooting), screenshots, `info.md`/README for HACS,
  GitHub releases with version tags, published first as a **beta** (pre-release) to
  collect feedback while development continues.

## Done

- Dock info page and simple dock automations (night brightness by time window or sun,
  fade out when idle with "first press only wakes") — 0.4.0
- Planning without any dock: "Only plan (no hardware yet)" entry in the config flow — 0.5.0

## Later

- Expose the behaviour to HA as well (e.g. a switch "fade out when idle", a "wake" button)

- Library split: move `protocol/` into its own PyPI package (needed for HA core)
- More models: Stream Deck Plus (dials, touch strip), Neo, Studio
- Tests (pytest-homeassistant-custom-component), CI, hassfest/HACS validation
