"""Simple per-dock automations: night brightness and dimming when idle.

Settings (stored with the dock's layout):

    {
      "night": {"enabled": false, "mode": "time", "start": "22:00", "end": "07:00", "brightness": 10},
      "idle": {"enabled": false, "timeout": 60, "brightness": 0, "wake_only": true,
               "when": "always", "start": "22:00", "end": "07:00"}
    }

- night: while active, the deck uses the night brightness instead of the normal one.
  mode "time" uses the window start..end (may cross midnight), mode "sun" uses sun.sun.
- idle: after `timeout` seconds without a key press the deck dims to `brightness`
  (0 = off). With `wake_only`, the press that wakes it does nothing else.
  `when` limits this to the night (as defined above, even if night brightness is off)
  or to its own window start..end; outside of it the deck stays on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

MODE_TIME = "time"
MODE_SUN = "sun"
WHEN_ALWAYS = "always"
WHEN_NIGHT = "night"
WHEN_TIME = "time"
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
CHECK_INTERVAL = timedelta(seconds=30)

PERCENT = vol.All(vol.Coerce(int), vol.Range(min=0, max=100))

BEHAVIOR_SCHEMA = vol.Schema(
    {
        vol.Optional("night", default=dict): {
            vol.Optional("enabled", default=False): bool,
            vol.Optional("mode", default=MODE_TIME): vol.In([MODE_TIME, MODE_SUN]),
            vol.Optional("start", default="22:00"): vol.Match(TIME_PATTERN),
            vol.Optional("end", default="07:00"): vol.Match(TIME_PATTERN),
            vol.Optional("brightness", default=10): PERCENT,
        },
        vol.Optional("idle", default=dict): {
            vol.Optional("enabled", default=False): bool,
            vol.Optional("timeout", default=60): vol.All(vol.Coerce(int), vol.Range(min=5, max=86400)),
            vol.Optional("brightness", default=0): PERCENT,
            vol.Optional("wake_only", default=True): bool,
            vol.Optional("when", default=WHEN_ALWAYS): vol.In([WHEN_ALWAYS, WHEN_NIGHT, WHEN_TIME]),
            vol.Optional("start", default="22:00"): vol.Match(TIME_PATTERN),
            vol.Optional("end", default="07:00"): vol.Match(TIME_PATTERN),
        },
    }
)


def default_behavior() -> dict[str, Any]:
    """All automations off."""
    return BEHAVIOR_SCHEMA({})


def _parse(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def in_window(now: time, start: time, end: time) -> bool:
    """True if now lies in [start, end), also when the window crosses midnight."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


class BehaviorController:
    """Tracks night and idle state of one dock and tells it when brightness changes."""

    def __init__(self, hass: HomeAssistant, on_change: Callable[[], None]) -> None:
        """Initialize."""
        self.hass = hass
        self.settings = default_behavior()
        self._on_change = on_change
        self.night_active = False
        # Whether fading out is allowed right now (idle enabled and inside its time range)
        self.idle_allowed = False
        self.dimmed = False
        self.last_activity: datetime | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._idle_timer: CALLBACK_TYPE | None = None
        self._running = False

    # Lifecycle

    @callback
    def async_start(self, settings: dict[str, Any] | None = None) -> None:
        """(Re)start with the given settings."""
        self.async_stop()
        if settings is not None:
            try:
                self.settings = BEHAVIOR_SCHEMA(settings)
            except vol.Invalid as err:
                # E.g. data from another version: fall back instead of breaking the dock
                _LOGGER.warning("Ignoring invalid behaviour settings (%s), using defaults", err)
                self.settings = default_behavior()
        self._running = True
        night, idle = self.settings["night"], self.settings["idle"]
        if night["enabled"] or (idle["enabled"] and idle["when"] != WHEN_ALWAYS):
            self._unsubs.append(async_track_time_interval(self.hass, self._check_schedule, CHECK_INTERVAL))
        uses_night = night["enabled"] or (idle["enabled"] and idle["when"] == WHEN_NIGHT)
        if uses_night and night["mode"] == MODE_SUN:
            self._unsubs.append(async_track_state_change_event(self.hass, ["sun.sun"], self._check_schedule))
        self.dimmed = False
        self._evaluate(notify=False)
        self._restart_idle_timer()
        self._on_change()

    @callback
    def async_stop(self) -> None:
        """Cancel all timers and listeners."""
        self._running = False
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._idle_timer:
            self._idle_timer()
            self._idle_timer = None

    # State

    def target_brightness(self, base: int) -> int:
        """Brightness the deck should have right now."""
        if self.dimmed:
            return self.settings["idle"]["brightness"]
        if self.night_active:
            return self.settings["night"]["brightness"]
        return base

    @property
    def idle_deadline(self) -> datetime | None:
        """When the deck will dim if nothing is pressed."""
        if not self.idle_allowed or self.dimmed or self.last_activity is None:
            return None
        return self.last_activity + timedelta(seconds=self.settings["idle"]["timeout"])

    @callback
    def async_activity(self) -> bool:
        """A key was pressed. Returns True if this press only woke the display."""
        self.last_activity = dt_util.utcnow()
        was_dimmed = self.dimmed
        self.dimmed = False
        self._restart_idle_timer()
        if was_dimmed:
            self._on_change()
            return self.settings["idle"]["wake_only"]
        return False

    @callback
    def async_wake(self) -> None:
        """Wake without a key press (e.g. after reconnecting)."""
        self.last_activity = dt_util.utcnow()
        if self.dimmed:
            self.dimmed = False
            self._on_change()
        self._restart_idle_timer()

    # Internals

    @callback
    def _restart_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer()
            self._idle_timer = None
        if not self._running or not self.idle_allowed:
            return
        if self.last_activity is None:
            self.last_activity = dt_util.utcnow()
        self._idle_timer = async_call_later(self.hass, self.settings["idle"]["timeout"], self._on_idle)

    @callback
    def _on_idle(self, _now: Any) -> None:
        self._idle_timer = None
        if not self.dimmed:
            self.dimmed = True
            self._on_change()

    @callback
    def _check_schedule(self, *_args: Any) -> None:
        self._evaluate(notify=True)

    def _is_night(self) -> bool:
        """The night as configured, whether or not night brightness is enabled."""
        night = self.settings["night"]
        if night["mode"] == MODE_SUN:
            sun = self.hass.states.get("sun.sun")
            return sun is not None and sun.state == "below_horizon"
        return in_window(dt_util.now().time(), _parse(night["start"]), _parse(night["end"]))

    def _idle_in_range(self) -> bool:
        idle = self.settings["idle"]
        if not idle["enabled"]:
            return False
        if idle["when"] == WHEN_NIGHT:
            return self._is_night()
        if idle["when"] == WHEN_TIME:
            return in_window(dt_util.now().time(), _parse(idle["start"]), _parse(idle["end"]))
        return True

    @callback
    def _evaluate(self, *, notify: bool) -> None:
        changed = False
        night_active = self.settings["night"]["enabled"] and self._is_night()
        if night_active != self.night_active:
            self.night_active = night_active
            changed = True

        allowed = self._idle_in_range()
        if allowed != self.idle_allowed:
            self.idle_allowed = allowed
            if allowed:
                # Range starts: count idle time from now
                self.last_activity = dt_util.utcnow()
                self._restart_idle_timer()
            else:
                # Range ends: the deck stays on outside of it
                self._restart_idle_timer()
                if self.dimmed:
                    self.dimmed = False
                    changed = True
        if changed and notify:
            self._on_change()
