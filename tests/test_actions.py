"""What a key press does in Home Assistant."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.stream_assistant.actions import async_run_action
from homeassistant.core import HomeAssistant


@pytest.mark.parametrize(
    ("entity_id", "state", "expected"),
    [
        ("light.a", "on", ("light", "toggle")),
        ("media_player.tv", "playing", ("media_player", "media_play_pause")),
        ("scene.film", "unknown", ("scene", "turn_on")),
        ("lock.door", "locked", ("lock", "unlock")),
        ("lock.door", "unlocked", ("lock", "lock")),
        ("vacuum.robi", "cleaning", ("vacuum", "return_to_base")),
        ("vacuum.robi", "docked", ("vacuum", "start")),
        ("input_select.x", "a", ("homeassistant", "toggle")),
    ],
)
async def test_default_action(hass: HomeAssistant, entity_id: str, state: str, expected: tuple[str, str]) -> None:
    hass.states.async_set(entity_id, state)
    calls = async_mock_service(hass, *expected)
    await async_run_action(hass, {"type": "default", "entity_id": entity_id})
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == entity_id


async def test_call_action_with_data_and_target(hass: HomeAssistant) -> None:
    calls = async_mock_service(hass, "light", "turn_on")
    await async_run_action(
        hass,
        {"type": "action", "action": "light.turn_on", "data": {"brightness": 10}, "target": {"entity_id": "light.a"}},
    )
    assert calls[0].data == {"brightness": 10, "entity_id": "light.a"}


async def test_failures_are_logged_not_raised(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    await async_run_action(hass, {"type": "action", "action": "nothing.here", "data": {}, "target": {}})
    assert "failed" in caplog.text
    # Navigation is handled by the device, nothing happens here
    await async_run_action(hass, {"type": "page", "page": "x"})
