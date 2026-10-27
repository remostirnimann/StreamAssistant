"""A Network Dock entry end to end: entities, painting, keys, actions, pages and services."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

from custom_components.stream_assistant.const import DOMAIN
from custom_components.stream_assistant.device import StreamAssistantDevice
from custom_components.stream_assistant.layout import empty_layout, validate_layout

from .common import DECK_SERIAL, DOCK_SERIAL, FakeDock, SetupEntry, dock_entry, entity_id, wait_for


async def _setup(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> StreamAssistantDevice:
    entry = await setup_entry(dock_entry())
    device: StreamAssistantDevice = entry.runtime_data
    await wait_for(lambda: device.deck_connected and len(fake_dock.images) == 15)
    return device


def _layout(*folders: dict, **keys: dict) -> dict:
    layout = empty_layout()
    layout["pages"][0]["keys"] = {k.lstrip("k"): v for k, v in keys.items()}
    layout["pages"].extend(folders)
    return validate_layout(layout, 15)


async def test_entities_and_painting(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    await hass.async_block_till_done()

    devices = dr.async_get(hass)
    dock = devices.async_get_device_by_identifier((DOMAIN, DOCK_SERIAL), device.entry.entry_id)
    deck = devices.async_get_device_by_identifier((DOMAIN, DECK_SERIAL), device.entry.entry_id)
    assert dock is not None and deck is not None
    assert deck.via_device_id == dock.id
    assert dock.sw_version == "1.01.013" and deck.sw_version == "1.02.000"

    assert hass.states.get(entity_id(hass, "binary_sensor", f"{DOCK_SERIAL}_dock_connected")).state == "on"
    assert hass.states.get(entity_id(hass, "binary_sensor", f"{DOCK_SERIAL}_deck_connected")).state == "on"
    assert hass.states.get(entity_id(hass, "event", f"{DECK_SERIAL}_key_14")) is not None

    brightness = entity_id(hass, "number", f"{DECK_SERIAL}_brightness")
    await hass.services.async_call("number", "set_value", {ATTR_ENTITY_ID: brightness, "value": 40}, blocking=True)
    await wait_for(lambda: fake_dock.brightness == 40)
    assert hass.states.get(brightness).state == "40"

    info = device.info()
    assert info["kind"] == "dock" and info["dock"]["serial"] == DOCK_SERIAL
    assert info["deck"]["key_count"] == 15 and info["deck"]["connected"]


async def test_keys_fire_events_and_run_actions(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock
) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    toggles = async_mock_service(hass, "light", "toggle")
    scenes = async_mock_service(hass, "scene", "turn_on")
    await device.async_set_layout(
        _layout(
            k0={"entity_id": "light.buero", "short": {"type": "default", "entity_id": "light.buero"}},
            k1={"title": "Szene", "short": {"type": "none"}, "long": {"type": "default", "entity_id": "scene.film"}},
        )
    )
    key1 = entity_id(hass, "event", f"{DECK_SERIAL}_key_1")

    # No long action: runs on press
    fake_dock.set_key(0, True)
    await wait_for(lambda: len(toggles) == 1)
    fake_dock.set_key(0, False)

    # With a long action: hold it
    fake_dock.set_key(1, True)
    await wait_for(lambda: hass.states.get(key1).attributes.get("event_type") == "pressed")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await wait_for(lambda: len(scenes) == 1)
    assert hass.states.get(key1).attributes["event_type"] == "long_press"
    fake_dock.set_key(1, False)
    await wait_for(lambda: hass.states.get(key1).attributes.get("event_type") == "released")

    # Short press on a key with a long action
    fake_dock.set_key(1, True)
    fake_dock.set_key(1, False)
    await wait_for(lambda: hass.states.get(key1).attributes.get("event_type") == "short_press")
    assert len(scenes) == 1


async def test_pages_and_folders(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    folder = {"id": "f1", "name": "Ordner", "parent": "main", "keys": {"3": {"title": "drin"}}}
    await device.async_set_layout(_layout(folder, k2={"title": "Ordner", "short": {"type": "page", "page": "f1"}}))

    fake_dock.set_key(2, True)
    fake_dock.set_key(2, False)
    await wait_for(lambda: device.current_page == "f1")
    # Key 0 of a folder is "back"
    fake_dock.set_key(0, True)
    fake_dock.set_key(0, False)
    await wait_for(lambda: device.current_page == "main")

    await device.async_show_page("missing")
    assert device.current_page == "main"
    # A page that disappears from the layout falls back to the root page
    await device.async_show_page("f1")
    await device.async_set_layout(_layout())
    assert device.current_page == "main"


async def test_entity_changes_repaint(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    hass.states.async_set("light.buero", "off")
    await device.async_set_layout(_layout(k5={"entity_id": "light.buero"}))
    await wait_for(lambda: device._wanted[5].background == "#2b2b2b")
    hass.states.async_set("light.buero", "on")
    await hass.async_block_till_done()
    await wait_for(lambda: device._wanted[5].background == "#f2b134")


async def test_services_set_and_clear_key(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    key3 = entity_id(hass, "event", f"{DECK_SERIAL}_key_3")
    await hass.services.async_call(
        DOMAIN,
        "set_key",
        {
            ATTR_ENTITY_ID: key3,
            "text": "Hallo",
            "background_color": [255, 0, 0],
            "text_color": "white",
            "font_size": 20,
        },
        blocking=True,
    )
    key = device.layout["pages"][0]["keys"]["3"]
    assert (key["title"], key["on_color"], key["text_color"], key["font_size"]) == ("Hallo", "#ff0000", "#ffffff", 20)
    with pytest.raises(Exception, match="colour"):
        await hass.services.async_call(
            DOMAIN, "set_key", {ATTR_ENTITY_ID: key3, "background_color": "nope"}, blocking=True
        )
    await hass.services.async_call(DOMAIN, "clear_key", {ATTR_ENTITY_ID: key3}, blocking=True)
    assert "3" not in device.layout["pages"][0]["keys"]


async def test_reconnect_after_dock_restart(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    sensor = entity_id(hass, "binary_sensor", f"{DOCK_SERIAL}_dock_connected")
    key0 = entity_id(hass, "event", f"{DECK_SERIAL}_key_0")
    fake_dock.images.clear()
    await fake_dock.stop()
    await wait_for(lambda: hass.states.get(sensor).state == "off")
    assert hass.states.get(key0).state == "unavailable"
    await fake_dock.start()
    await wait_for(lambda: device.deck_connected and len(fake_dock.images) == 15)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"


async def test_other_deck_reloads_the_entry(hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock) -> None:
    entry = dock_entry()
    entry = entry.__class__(
        domain=DOMAIN, title=entry.title, unique_id=entry.unique_id, data={**entry.data, "deck_serial": "OLDDECK"}
    )
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await setup_entry(entry)
        await wait_for(lambda: reload.called)
    assert entry.data["deck_serial"] == DECK_SERIAL


async def test_unload_resets_and_remove_deletes_layout(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_dock: FakeDock, hass_storage: dict
) -> None:
    device = await _setup(hass, setup_entry, fake_dock)
    await device.async_set_layout(_layout(k0={"title": "x"}))
    entry = device.entry
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    await wait_for(lambda: fake_dock.resets == 1)
    assert f"{DOMAIN}.{entry.entry_id}" in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage


async def test_layout_survives_restart_and_migrates_v1(
    hass: HomeAssistant, fake_dock: FakeDock, setup_entry: SetupEntry, hass_storage: dict
) -> None:
    entry = dock_entry()
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"keys": {"4": {"text": "Alt", "background_color": "#112233"}}},
    }
    await setup_entry(entry)
    assert entry.runtime_data.layout["pages"][0]["keys"]["4"]["title"] == "Alt"
