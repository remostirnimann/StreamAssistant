"""Updating a bridge from Home Assistant: the update entity, the install, automatic updates."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.stream_assistant.bridge_hub import BridgeHub
from custom_components.stream_assistant.const import CONF_AUTO_UPDATE, VERSION
from custom_components.stream_assistant.protocol.bridge import BridgeError

from .common import SetupEntry, bridge_entry, entity_id, virtual_entry, wait_for
from .fake_bridge import BRIDGE_ID, FakeBridge

UPDATE = f"bridge-{BRIDGE_ID}_update"
# Older than any version the integration can have
OLD = "0.1.0"


async def _hub(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, **options: bool) -> BridgeHub:
    fake_bridge.version = OLD
    entry = bridge_entry(fake_bridge)
    if options:
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, options=options)
        hass.config_entries._entries.pop(entry.entry_id)
    entry = await setup_entry(entry)
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: hub.connected)
    await hass.async_block_till_done()
    return hub


async def test_update_entity_installs_the_matching_version(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    hub = await _hub(hass, setup_entry, fake_bridge)
    update = entity_id(hass, "update", UPDATE)
    state = hass.states.get(update)
    assert state.state == "on"
    assert state.attributes["installed_version"] == OLD
    assert state.attributes["latest_version"] == VERSION
    assert state.attributes["release_url"].endswith(f"/v{VERSION}")
    assert state.attributes["auto_update"] is False

    await hass.services.async_call("update", "install", {"entity_id": update}, blocking=True)
    assert fake_bridge.updates == [VERSION]
    assert hub.bridge_version == VERSION and not hub.update_in_progress
    await hass.async_block_till_done()
    assert hass.states.get(update).state == "off"


async def test_failures_and_bridges_that_cannot_update(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = await _hub(hass, setup_entry, fake_bridge)
    update = entity_id(hass, "update", UPDATE)

    fake_bridge.on_update = "fail"
    with pytest.raises(HomeAssistantError, match="Checksum does not match"):
        await hass.services.async_call("update", "install", {"entity_id": update}, blocking=True)

    fake_bridge.on_update = "refuse"
    with pytest.raises(HomeAssistantError, match="cannot update"):
        await hass.services.async_call("update", "install", {"entity_id": update}, blocking=True)

    # The bridge does not come back in time
    fake_bridge.on_update = "ignore"
    monkeypatch.setattr("custom_components.stream_assistant.bridge_hub.BRIDGE_UPDATE_TIMEOUT", 0.2)
    with pytest.raises(BridgeError, match="did not come back"):
        await hub.async_update_bridge(VERSION)

    # One at a time
    monkeypatch.setattr("custom_components.stream_assistant.bridge_hub.BRIDGE_UPDATE_TIMEOUT", 5)
    task = hass.async_create_task(hub.async_update_bridge(VERSION))
    await wait_for(lambda: hub.update_in_progress)
    assert hass.states.get(update).attributes["in_progress"] is True
    with pytest.raises(BridgeError, match="already running"):
        await hub.async_update_bridge(VERSION)
    task.cancel()

    # An older bridge without the feature: shown, but nothing to install
    fake_bridge.features = ["key_images"]
    await fake_bridge.drop()
    await wait_for(lambda: hub.connected and not hub.can_update)
    await hass.async_block_till_done()
    assert hass.states.get(update).attributes["supported_features"] == 0
    with pytest.raises(BridgeError, match="cannot update itself"):
        await hub.async_update_bridge(VERSION)


async def test_development_versions_offer_nothing(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("custom_components.stream_assistant.bridge_hub.VERSION", "0.9.0.dev0")
    hub = await _hub(hass, setup_entry, fake_bridge, **{CONF_AUTO_UPDATE: True})
    state = hass.states.get(entity_id(hass, "update", UPDATE))
    assert state.state == "off"
    assert state.attributes["latest_version"] == OLD
    assert state.attributes["release_url"] is None
    assert not hub.needs_update and fake_bridge.updates == []


async def test_automatic_updates(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge) -> None:
    hub = await _hub(hass, setup_entry, fake_bridge, **{CONF_AUTO_UPDATE: True})
    await wait_for(lambda: hub.bridge_version == VERSION)
    assert fake_bridge.updates == [VERSION]
    assert hass.states.get(entity_id(hass, "update", UPDATE)).attributes["auto_update"] is True

    # A failed automatic update is not tried again for the same version
    fake_bridge.on_update = "fail"
    fake_bridge.version = OLD
    await fake_bridge.drop()
    await wait_for(lambda: hub.connected and hub.bridge_version == OLD)
    await hass.async_block_till_done()
    assert fake_bridge.updates == [VERSION]


async def test_turning_on_automatic_updates_applies_right_away(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    hub = await _hub(hass, setup_entry, fake_bridge)
    assert fake_bridge.updates == []
    result = await hass.config_entries.options.async_init(hub.entry.entry_id)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_AUTO_UPDATE: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await wait_for(lambda: hub.bridge_version == VERSION)
    assert fake_bridge.updates == [VERSION]


async def test_only_bridges_have_options(hass: HomeAssistant, setup_entry: SetupEntry) -> None:
    entry = await setup_entry(virtual_entry(2, 2))
    assert not entry.supports_options
