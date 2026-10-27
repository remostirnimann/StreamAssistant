"""Run the Home Assistant side of a key action, and what turning a dial changes."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .layout import ACTION_CALL, ACTION_DEFAULT

_LOGGER = logging.getLogger(__name__)

# The "obvious" thing a key press does, per domain
DEFAULT_SERVICES: dict[str, str] = {
    "light": "toggle",
    "switch": "toggle",
    "fan": "toggle",
    "input_boolean": "toggle",
    "group": "toggle",
    "siren": "toggle",
    "humidifier": "toggle",
    "climate": "toggle",
    "cover": "toggle",
    "valve": "toggle",
    "media_player": "media_play_pause",
    "scene": "turn_on",
    "script": "turn_on",
    "button": "press",
    "input_button": "press",
    "automation": "trigger",
    "vacuum": "start",
}


def _default_call(hass: HomeAssistant, entity_id: str) -> tuple[str, str]:
    domain = entity_id.split(".", 1)[0]
    if domain == "lock":
        state = hass.states.get(entity_id)
        return domain, "unlock" if state and state.state == "locked" else "lock"
    if domain == "vacuum":
        state = hass.states.get(entity_id)
        return domain, "return_to_base" if state and state.state == "cleaning" else "start"
    if service := DEFAULT_SERVICES.get(domain):
        return domain, service
    return "homeassistant", "toggle"


# Change per dial detent when the dial sets no step: percent, except where noted
DEFAULT_ADJUST_STEPS: dict[str, float] = {
    "light": 5,
    "cover": 5,
    "fan": 5,
    "media_player": 2,
    "climate": 0.5,  # degrees, unless the entity says otherwise
}

ADJUSTABLE_DOMAINS = (*DEFAULT_ADJUST_STEPS, "number", "input_number", "select", "input_select")


@dataclass(frozen=True, slots=True)
class AdjustCall:
    """The service call for some dial detents; value is the new absolute value, if any."""

    domain: str
    service: str
    data: dict[str, Any]
    value: float | None = None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: Any, high: Any) -> float:
    if (low := _number(low)) is not None:
        value = max(low, value)
    if (high := _number(high)) is not None:
        value = min(high, value)
    return value


def adjust_call(state: State, steps: int, step: float | None = None, base: float | None = None) -> AdjustCall | None:
    """What turning a dial by `steps` detents does to an entity.

    `base` is the value the last adjustment set, used while the entity has not
    reported it yet; otherwise the current state is the starting point.
    """
    if not steps or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    domain = state.domain
    attrs = state.attributes
    if domain == "light":
        # Relative: the light works it out, also from off (and turns off at 0)
        return AdjustCall("light", "turn_on", {"brightness_step_pct": (step or 5) * steps})
    if domain == "media_player":
        current = base if base is not None else _number(attrs.get("volume_level"))
        if current is None:
            return AdjustCall("media_player", "volume_up" if steps > 0 else "volume_down", {})
        value = round(_clamp(current + (step or 2) / 100 * steps, 0, 1), 3)
        return AdjustCall("media_player", "volume_set", {"volume_level": value}, value)
    if domain == "cover":
        current = base if base is not None else _number(attrs.get("current_position"))
        if current is None:
            return AdjustCall("cover", "open_cover" if steps > 0 else "close_cover", {})
        value = round(_clamp(current + (step or 5) * steps, 0, 100))
        return AdjustCall("cover", "set_cover_position", {"position": value}, value)
    if domain == "fan":
        current = base if base is not None else (_number(attrs.get("percentage")) or 0 if state.state == "on" else 0)
        value = round(_clamp(current + (step or _number(attrs.get("percentage_step")) or 5) * steps, 0, 100))
        return AdjustCall("fan", "set_percentage", {"percentage": value}, value)
    if domain == "climate":
        current = base if base is not None else _number(attrs.get("temperature"))
        if current is None:
            return None
        increment = step or _number(attrs.get("target_temp_step")) or 0.5
        value = round(_clamp(current + increment * steps, attrs.get("min_temp"), attrs.get("max_temp")), 2)
        return AdjustCall("climate", "set_temperature", {"temperature": value}, value)
    if domain in ("number", "input_number"):
        current = base if base is not None else _number(state.state)
        if current is None:
            return None
        increment = step or _number(attrs.get("step")) or 1
        value = round(_clamp(current + increment * steps, attrs.get("min"), attrs.get("max")), 6)
        return AdjustCall(domain, "set_value", {"value": value}, value)
    if domain in ("select", "input_select"):
        return AdjustCall(domain, "select_next" if steps > 0 else "select_previous", {"cycle": False})
    return None


async def async_run_adjust(
    hass: HomeAssistant, entity_id: str, call: AdjustCall, context: Context | None = None
) -> None:
    """Run the service call of a dial adjustment."""
    try:
        await hass.services.async_call(
            call.domain, call.service, {ATTR_ENTITY_ID: entity_id, **call.data}, context=context
        )
    except (HomeAssistantError, vol.Invalid, ValueError) as err:
        _LOGGER.warning("Stream Deck dial adjustment of %s failed: %s", entity_id, err)


async def async_run_action(hass: HomeAssistant, action: dict[str, Any], context: Context | None = None) -> None:
    """Run a 'default' or 'action' key action. Navigation is handled by the device."""
    try:
        if action["type"] == ACTION_DEFAULT:
            domain, service = _default_call(hass, action["entity_id"])
            await hass.services.async_call(domain, service, {ATTR_ENTITY_ID: action["entity_id"]}, context=context)
        elif action["type"] == ACTION_CALL:
            domain, service = action["action"].split(".", 1)
            await hass.services.async_call(
                domain,
                service,
                dict(action.get("data") or {}),
                target=dict(action.get("target") or {}) or None,
                context=context,
            )
    except (HomeAssistantError, vol.Invalid, ValueError) as err:
        _LOGGER.warning("Stream Deck action %s failed: %s", action, err)
