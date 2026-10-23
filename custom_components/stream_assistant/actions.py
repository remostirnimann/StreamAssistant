"""Run the Home Assistant side of a key action."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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


async def async_run_action(
    hass: HomeAssistant, action: dict[str, Any], context: Context | None = None
) -> None:
    """Run a 'default' or 'action' key action. Navigation is handled by the device."""
    try:
        if action["type"] == ACTION_DEFAULT:
            domain, service = _default_call(hass, action["entity_id"])
            await hass.services.async_call(
                domain, service, {ATTR_ENTITY_ID: action["entity_id"]}, context=context
            )
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
