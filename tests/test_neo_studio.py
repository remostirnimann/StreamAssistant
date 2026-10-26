"""Stream Deck Neo (page buttons, screen) and Studio (wide keys, LED rings, NFC) behind a bridge."""

from __future__ import annotations

import io

from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from PIL import Image
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.stream_assistant.bridge_hub import BridgeHub
from custom_components.stream_assistant.capabilities import find_capabilities
from custom_components.stream_assistant.const import DOMAIN
from custom_components.stream_assistant.layout import empty_layout, validate_layout
from custom_components.stream_assistant.protocol.bridge import BridgeDevice

from .common import SetupEntry, bridge_entry, entity_id, wait_for
from .fake_bridge import BRIDGE_ID, FakeBridge, neo, studio


async def _deck(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, data: dict):
    fake_bridge.devices = {data["id"]: data}
    entry = await setup_entry(bridge_entry(fake_bridge))
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: data["id"] in hub.devices and hub.devices[data["id"]].deck_connected)
    await hass.async_block_till_done()
    return hub.devices[data["id"]]


def _three_pages() -> dict:
    layout = empty_layout()
    layout["pages"] += [
        {"id": "a", "name": "Licht", "parent": "main"},
        {"id": "b", "name": "Musik", "parent": "main"},
    ]
    return validate_layout(layout, 8)


def test_round_trips_and_catalog() -> None:
    for data in (neo(), studio()):
        device = BridgeDevice.from_json(data)
        assert BridgeDevice.from_json(device.to_json()) == device
    found = BridgeDevice.from_json(studio())
    assert (found.key_size, found.dial_ring, found.nfc) == (112, 24, True)
    assert find_capabilities("studio").cols == 16 and find_capabilities("grid_16x2_d2") is not None
    assert find_capabilities("neo").has_screen


async def test_neo_page_buttons_and_screen(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    device = await _deck(hass, setup_entry, fake_bridge, neo())
    assert (device.model.buttons, device.model.screen_width) == (2, 248)

    def lights() -> list[str]:
        colors = {c["button"]: c["color"] for c in fake_bridge.commands if c["type"] == "set_button_color"}
        return [colors.get(0), colors.get(1)]

    # One page: nowhere to go, both buttons dark; the screen shows the page
    await wait_for(lambda: "neo-1" in fake_bridge.screen_images and lights() == ["#000000", "#000000"])
    screen = Image.open(io.BytesIO(fake_bridge.screen_images["neo-1"]))
    assert screen.size == (248, 58)

    await device.async_set_layout(_three_pages())
    await wait_for(lambda: lights() == ["#000000", "#ffffff"])

    # The right button goes to the next page, the left one back
    before = fake_bridge.screen_images["neo-1"]
    await fake_bridge.button("neo-1", 1, True)
    await fake_bridge.button("neo-1", 1, False)
    await wait_for(lambda: device.current_page == "a")
    await wait_for(lambda: lights() == ["#ffffff", "#ffffff"] and fake_bridge.screen_images["neo-1"] != before)
    button1 = entity_id(hass, "event", f"{BRIDGE_ID}-neo-1_button_1")
    await wait_for(lambda: hass.states.get(button1).attributes.get("event_type") == "released")
    await fake_bridge.button("neo-1", 1, True)
    await fake_bridge.button("neo-1", 1, False)
    await wait_for(lambda: device.current_page == "b" and lights() == ["#ffffff", "#000000"])
    # At the end: nothing happens
    await fake_bridge.button("neo-1", 1, True)
    await fake_bridge.button("neo-1", 1, False)
    await fake_bridge.button("neo-1", 0, True)
    await fake_bridge.button("neo-1", 0, False)
    await wait_for(lambda: device.current_page == "a")


async def test_studio_rings_and_tags(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge) -> None:
    assert await async_setup_component(hass, "tag", {})
    device = await _deck(hass, setup_entry, fake_bridge, studio())
    assert (device.model.key_size, device.model.dial_ring, device.model.nfc) == (112, 24, True)

    def rings() -> dict[int, tuple[str, float]]:
        return {c["dial"]: (c["color"], c["level"]) for c in fake_bridge.commands if c["type"] == "set_dial_leds"}

    # Unassigned dials are dark
    await wait_for(lambda: rings() == {0: ("#000000", 1.0), 1: ("#000000", 1.0)})

    hass.states.async_set("light.desk", "on", {"brightness": 128})
    layout = empty_layout()
    layout["pages"][0]["dials"] = {"0": {"entity_id": "light.desk", "rotate": "adjust", "on_color": "#ff8800"}}
    await device.async_set_layout(validate_layout(layout, 32, 2))
    await wait_for(lambda: rings().get(0) == ("#ff8800", 0.502))
    hass.states.async_set("light.desk", "on", {"brightness": 255})
    await wait_for(lambda: rings().get(0) == ("#ff8800", 1.0))

    # Turning works without a touch strip
    calls = async_mock_service(hass, "light", "turn_on")
    await fake_bridge.turn("studio-1", 0, 1)
    await wait_for(lambda: len(calls) == 1)

    # NFC: a tag scan from this deck
    scans: list[Event] = []
    hass.bus.async_listen("tag_scanned", scans.append)
    await fake_bridge.tag("studio-1", "04A2B3C4D5")
    await wait_for(lambda: len(scans) == 1)
    registered = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{BRIDGE_ID}-studio-1"), device.entry.entry_id
    )
    assert scans[0].data["tag_id"] == "04A2B3C4D5" and scans[0].data["device_id"] == registered.id


async def test_tags_need_the_tag_integration(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge, caplog
) -> None:
    await _deck(hass, setup_entry, fake_bridge, studio())
    await fake_bridge.tag("studio-1", "04A2")
    await wait_for(lambda: "Tags integration is not set up" in caplog.text)
