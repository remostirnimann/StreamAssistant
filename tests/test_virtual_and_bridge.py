"""Virtual panels and bridge entries with the decks a bridge reports."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stream_assistant.bridge_hub import BridgeHub
from custom_components.stream_assistant.const import CONF_COLS, CONF_DEVICES, DOMAIN
from custom_components.stream_assistant.layout import empty_layout
from custom_components.stream_assistant.transport import VirtualTransport

from .common import SetupEntry, bridge_entry, entity_id, virtual_entry, wait_for
from .fake_bridge import BRIDGE_ID, FakeBridge, deck


async def test_virtual_panel(hass: HomeAssistant, setup_entry: SetupEntry) -> None:
    entry = await setup_entry(virtual_entry(4, 2))
    device = entry.runtime_data
    transport: VirtualTransport = device.transport
    assert device.virtual and device.model.key_count == 8 and device.brightness == 100
    await wait_for(lambda: len(transport.images) == 8)

    events: list[tuple[str, int | None]] = []
    unsubscribe = transport.subscribe(lambda kind, index: events.append((kind, index)))
    brightness = entity_id(hass, "number", "virtual-test_brightness")
    await hass.services.async_call("number", "set_value", {ATTR_ENTITY_ID: brightness, "value": 20}, blocking=True)
    assert transport.brightness == 20 and ("brightness", None) in events
    unsubscribe()

    transport.press(1, True)
    transport.press(1, False)
    transport.press(99, True)  # outside the grid: ignored
    await hass.async_block_till_done()
    key1 = hass.states.get(entity_id(hass, "event", "virtual-test_key_1"))
    assert key1.attributes["event_type"] == "short_press"

    registered = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, "virtual-test"), entry.entry_id)
    assert registered.model == "Virtual panel 4 × 2" and registered.name == "Wall panel"
    # No connection sensors for a panel that is always there
    assert not [
        e for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) if e.domain == "binary_sensor"
    ]
    assert device.info()["kind"] == "virtual"


async def test_virtual_grid_change_keeps_row_and_column(
    hass: HomeAssistant, setup_entry: SetupEntry, hass_storage: dict[str, Any]
) -> None:
    entry = virtual_entry(4, 2)
    layout = empty_layout()
    layout["pages"][0]["keys"] = {"5": {"title": "row 1 col 1"}, "3": {"title": "row 0 col 3"}}
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 2,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {**layout, "template_id": None, "behavior": None, "grid": [4, 2]},
    }
    # Pretend the panel had 8 key entities and is now 3x2
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("event", DOMAIN, "virtual-test_key_7", config_entry=entry)
    hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_COLS: 3})
    hass.config_entries._entries.pop(entry.entry_id)
    await setup_entry(entry)
    keys = entry.runtime_data.layout["pages"][0]["keys"]
    assert set(keys) == {"4"}
    assert keys["4"]["title"] == "row 1 col 1"
    assert registry.async_get_entity_id("event", DOMAIN, "virtual-test_key_7") is None


async def test_bridge_decks_appear_and_work(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    entry = await setup_entry(bridge_entry(fake_bridge))
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: "sim-1" in hub.devices and hub.devices["sim-1"].deck_connected)
    await wait_for(lambda: len([k for k in fake_bridge.images if k[0] == "sim-1"]) == 15)
    await hass.async_block_till_done()
    device = hub.devices["sim-1"]
    assert device.key == f"{entry.entry_id}.sim-1"
    assert device.title == "Deck sim-1"
    assert entry.data[CONF_DEVICES]["sim-1"]["id"] == "sim-1"

    unique = f"{BRIDGE_ID}-sim-1"
    assert hass.states.get(entity_id(hass, "binary_sensor", f"bridge-{BRIDGE_ID}_connected")).state == "on"
    assert hass.states.get(entity_id(hass, "binary_sensor", f"{unique}_deck_connected")).state == "on"
    registered = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, unique), entry.entry_id)
    bridge_device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, f"bridge-{BRIDGE_ID}"), entry.entry_id)
    assert registered.via_device_id == bridge_device.id
    assert bridge_device.sw_version == "0.8.0"

    await fake_bridge.press("sim-1", 2, True)
    await fake_bridge.press("sim-1", 2, False)
    key2 = entity_id(hass, "event", f"{unique}_key_2")
    await wait_for(lambda: hass.states.get(key2).attributes.get("event_type") == "short_press")

    info = device.info()
    assert info["kind"] == "bridge"
    assert info["dock"]["name"] == "Test bridge" and info["dock"]["serial"] == BRIDGE_ID

    # Plug in a second deck: new device with entities
    await fake_bridge.plug(deck("sim-2", 3, 1))
    await wait_for(lambda: "sim-2" in hub.devices and hub.devices["sim-2"].deck_connected)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "event", f"{BRIDGE_ID}-sim-2_key_2")) is not None

    # Unplug: unavailable, entities stay
    await fake_bridge.unplug("sim-2")
    await wait_for(lambda: not hub.devices["sim-2"].deck_connected)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "event", f"{BRIDGE_ID}-sim-2_key_0")).state == "unavailable"

    # Bridge restart: offline, then everything is painted again
    fake_bridge.images.clear()
    await fake_bridge.drop()
    await wait_for(lambda: not hub.connected)
    await wait_for(lambda: hub.connected and len([k for k in fake_bridge.images if k[0] == "sim-1"]) == 15)
    assert any(c["type"] == "set_brightness" for c in fake_bridge.commands)


async def test_known_decks_exist_while_offline(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    await fake_bridge.stop()
    entry = await setup_entry(bridge_entry(fake_bridge, devices={"old": deck("old", 2, 2)}))
    hub: BridgeHub = entry.runtime_data
    assert "old" in hub.devices and not hub.connected
    assert hass.states.get(entity_id(hass, "event", f"{BRIDGE_ID}-old_key_3")).state == "unavailable"


async def test_unsupported_and_changed_decks(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    colour_only = deck("pads", capabilities={"keys": {"cols": 8, "rows": 8, "colors": True}})
    fake_bridge.devices["pads"] = colour_only
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        entry = await setup_entry(bridge_entry(fake_bridge, devices={"sim-1": deck("sim-1", 3, 3)}))
        hub: BridgeHub = entry.runtime_data
        await wait_for(lambda: reload.called)
    assert "pads" not in hub.devices
    # The stored deck had 3x3, the bridge now reports 5x3: stored and reloaded
    assert entry.data[CONF_DEVICES]["sim-1"]["capabilities"]["keys"]["cols"] == 5


async def test_refused_token_starts_reauth(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    entry = await setup_entry(bridge_entry(fake_bridge, token="revoked"))
    await wait_for(
        lambda: any(f["context"]["source"] == SOURCE_REAUTH for f in hass.config_entries.flow.async_progress())
    )
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH)
    assert flow["context"]["entry_id"] == entry.entry_id


async def test_removing_a_bridge_deletes_all_deck_layouts(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, hass_storage: dict[str, Any]
) -> None:
    entry = await setup_entry(bridge_entry(fake_bridge))
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: "sim-1" in hub.devices and hub.devices["sim-1"].deck_connected)
    await hub.devices["sim-1"].async_set_layout(empty_layout())
    await hass.config_entries.async_unload(entry.entry_id)
    await wait_for(lambda: any(c == {"type": "reset", "device": "sim-1"} for c in fake_bridge.commands))
    assert f"{DOMAIN}.{entry.entry_id}.sim-1" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}.sim-1" not in hass_storage


async def test_planner_entry(hass: HomeAssistant, setup_entry: SetupEntry) -> None:
    entry = await setup_entry(MockConfigEntry(domain=DOMAIN, unique_id="planner", data={"kind": "planner"}))
    assert entry.runtime_data is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_remove(entry.entry_id)
