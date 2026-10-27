"""Decks without a display (Stream Deck Pedal) behind a bridge: keys only press."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.stream_assistant.bridge_hub import BridgeHub
from custom_components.stream_assistant.layout import empty_layout, validate_layout
from custom_components.stream_assistant.protocol.bridge import BridgeDevice

from .common import SetupEntry, bridge_entry, entity_id, wait_for
from .fake_bridge import BRIDGE_ID, FakeBridge, deck, pedal

UNIQUE = f"{BRIDGE_ID}-pedal-1"


def test_pedal_round_trip() -> None:
    device = BridgeDevice.from_json(pedal())
    assert (device.cols, device.rows, device.key_size, device.colors, device.brightness) == (3, 1, 0, False, False)
    data = device.to_json()
    assert "image" not in data["capabilities"]["keys"] and "colors" not in data["capabilities"]["keys"]
    assert BridgeDevice.from_json(data) == device
    pads = BridgeDevice.from_json(deck("pads", capabilities={"keys": {"cols": 8, "rows": 8, "colors": True}}))
    assert pads.colors and BridgeDevice.from_json(pads.to_json()) == pads


async def test_pedal_presses_without_display(
    hass: HomeAssistant, hass_ws_client, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    fake_bridge.devices = {"pedal-1": pedal()}
    entry = await setup_entry(bridge_entry(fake_bridge))
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: "pedal-1" in hub.devices and hub.devices["pedal-1"].deck_connected)
    await hass.async_block_till_done()
    device = hub.devices["pedal-1"]
    assert not device.model.has_display

    # Nothing is painted, no brightness is sent, there is no brightness entity
    assert not fake_bridge.images
    assert not any(c["type"] == "set_brightness" for c in fake_bridge.commands)
    assert hass.states.get(f"number.{UNIQUE}_brightness") is None
    assert not [s for s in hass.states.async_all("number") if "pedal" in s.entity_id]

    calls = async_mock_service(hass, "script", "turn_on")
    layout = empty_layout()
    layout["pages"][0]["keys"] = {
        "1": {
            "title": "Mitte",
            "short": {"type": "action", "action": "script.turn_on", "data": {"entity_id": "script.x"}},
        }
    }
    await device.async_set_layout(validate_layout(layout, 3))

    # A "dimmed" deck: pedals have nothing to wake, the press counts right away
    with patch.object(device.behavior, "async_activity", return_value=True):
        await fake_bridge.press("pedal-1", 1, True)
        await fake_bridge.press("pedal-1", 1, False)
        await wait_for(lambda: len(calls) == 1)
    key1 = entity_id(hass, "event", f"{UNIQUE}_key_1")
    await wait_for(lambda: hass.states.get(key1).attributes.get("event_type") == "short_press")
    assert not fake_bridge.images

    # The editor still shows the keys
    client = await hass_ws_client(hass)

    async def call(**message: Any) -> dict[str, Any]:
        await client.send_json_auto_id(message)
        return await client.receive_json()

    preview = await call(type="stream_assistant/preview", entry_id=device.key, page=layout["pages"][0])
    assert len(preview["result"]["images"]) == 3 and preview["result"]["dials"] == []
