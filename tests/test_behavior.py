"""Night brightness and fading out when idle."""

from __future__ import annotations

from datetime import time, timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.stream_assistant.behavior import BehaviorController, default_behavior, in_window
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


def test_in_window() -> None:
    assert in_window(time(23), time(22), time(7))
    assert in_window(time(6, 59), time(22), time(7))
    assert not in_window(time(7), time(22), time(7))
    assert in_window(time(12), time(8), time(17))
    assert not in_window(time(12), time(8), time(8))


def _controller(hass: HomeAssistant) -> tuple[BehaviorController, list[int]]:
    changes: list[int] = []
    controller = BehaviorController(hass, lambda: changes.append(1))
    return controller, changes


async def test_defaults_do_nothing(hass: HomeAssistant) -> None:
    controller, changes = _controller(hass)
    controller.async_start(None)
    assert controller.settings == default_behavior()
    assert controller.target_brightness(70) == 70
    assert controller.idle_deadline is None
    assert not controller.async_activity()
    controller.async_stop()
    assert changes == [1]


async def test_invalid_settings_fall_back(hass: HomeAssistant) -> None:
    controller, _ = _controller(hass)
    controller.async_start({"night": {"brightness": 500}})
    assert controller.settings == default_behavior()
    controller.async_stop()


async def test_night_by_time_window(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-24 21:59:00+00:00")
    controller, changes = _controller(hass)
    controller.async_start({"night": {"enabled": True, "start": "22:00", "end": "07:00", "brightness": 10}})
    assert not controller.night_active
    freezer.move_to("2026-10-24 22:00:30+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert controller.night_active
    assert controller.target_brightness(70) == 10
    assert len(changes) == 2
    controller.async_stop()


async def test_night_by_sun(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "above_horizon")
    controller, _ = _controller(hass)
    controller.async_start({"night": {"enabled": True, "mode": "sun", "brightness": 5}})
    assert not controller.night_active
    hass.states.async_set("sun.sun", "below_horizon")
    await hass.async_block_till_done()
    assert controller.night_active
    assert controller.target_brightness(70) == 5
    controller.async_stop()


async def test_idle_dims_and_first_press_only_wakes(hass: HomeAssistant) -> None:
    controller, changes = _controller(hass)
    controller.async_start({"idle": {"enabled": True, "timeout": 30, "brightness": 0, "wake_only": True}})
    assert controller.idle_deadline is not None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert controller.dimmed
    assert controller.target_brightness(70) == 0
    assert controller.idle_deadline is None
    # The first press only wakes the deck
    assert controller.async_activity() is True
    assert not controller.dimmed
    assert controller.async_activity() is False
    controller.async_stop()
    assert len(changes) == 3


async def test_wake_without_press(hass: HomeAssistant) -> None:
    controller, _ = _controller(hass)
    controller.async_start({"idle": {"enabled": True, "timeout": 10, "wake_only": False}})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    assert controller.dimmed
    controller.async_wake()
    assert not controller.dimmed
    assert controller.async_activity() is False
    controller.async_stop()


async def test_idle_only_in_its_window(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-24 21:00:00+00:00")
    controller, _ = _controller(hass)
    controller.async_start({"idle": {"enabled": True, "timeout": 10, "when": "time", "start": "22:00", "end": "23:00"}})
    assert not controller.idle_allowed
    freezer.move_to("2026-10-24 22:00:10+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert controller.idle_allowed
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert controller.dimmed
    # The window ends: the deck comes back on and stays on
    freezer.move_to("2026-10-24 23:00:30+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert not controller.idle_allowed
    assert not controller.dimmed
    controller.async_stop()


async def test_idle_only_at_night(hass: HomeAssistant) -> None:
    hass.states.async_set("sun.sun", "below_horizon")
    controller, _ = _controller(hass)
    controller.async_start({"night": {"mode": "sun"}, "idle": {"enabled": True, "when": "night"}})
    assert controller.idle_allowed
    assert not controller.night_active  # night brightness itself is off
    controller.async_stop()
