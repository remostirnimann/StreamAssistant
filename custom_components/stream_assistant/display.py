"""Turn a key's layout entry plus the current entity state into what the key shows."""

from __future__ import annotations

from typing import Any

from homeassistant.const import ATTR_FRIENDLY_NAME, ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State

from .layout import SECOND_LINE_NONE, SECOND_LINE_STATE, SECOND_LINE_TEXT
from .render import KeyVisual

OFFLINE_BG = "#3a3a3a"
OFFLINE_FG = "#9aa3ad"
NAV_BG = "#3a3a3a"
EMPTY_BG = "#000000"

ON_STATES = {
    "on", "open", "opening", "closing", "playing", "unlocked", "unlocking", "home",
    "heat", "cool", "heat_cool", "auto", "dry", "fan_only", "cleaning", "active",
    "armed_away", "armed_home", "armed_night", "armed_vacation", "armed_custom_bypass",
    "triggered", "above_horizon",
}
# Domains without an on/off meaning: always drawn in the "on" colour
NEUTRAL_DOMAINS = {
    "sensor", "weather", "number", "input_number", "input_text", "input_select", "select",
    "scene", "button", "input_button", "counter", "event", "text", "date", "time",
    "datetime", "input_datetime", "image", "camera", "zone", "person",
}
# (icon when on, icon when off) for domains where the state changes the picture
DOMAIN_STATE_ICONS = {
    "light": ("lightbulb-on", "lightbulb-outline"),
    "switch": ("toggle-switch", "toggle-switch-off"),
    "input_boolean": ("toggle-switch", "toggle-switch-off"),
    "fan": ("fan", "fan-off"),
    "cover": ("window-shutter-open", "window-shutter"),
    "lock": ("lock-open-variant", "lock"),
    "media_player": ("play", "pause"),
    "valve": ("valve-open", "valve-closed"),
    "person": ("account", "account-outline"),
}
BINARY_SENSOR_ICONS = {
    "door": ("door-open", "door-closed"),
    "garage_door": ("garage-open", "garage"),
    "window": ("window-open", "window-closed"),
    "motion": ("motion-sensor", "motion-sensor-off"),
    "occupancy": ("motion-sensor", "motion-sensor-off"),
    "plug": ("power-plug", "power-plug-off"),
    "power": ("power", "power-off"),
}
DOMAIN_ICONS = {
    "light": "lightbulb", "switch": "toggle-switch", "fan": "fan", "cover": "blinds",
    "lock": "lock", "scene": "palette", "script": "script-text", "media_player": "play-pause",
    "climate": "thermostat", "sensor": "gauge", "binary_sensor": "checkbox-blank-circle-outline",
    "input_boolean": "toggle-switch", "button": "gesture-tap-button", "automation": "robot",
    "vacuum": "robot-vacuum", "weather": "weather-partly-cloudy", "person": "account",
}

STATE_LABELS = {
    "de": {
        "on": "An", "off": "Aus", "open": "Offen", "closed": "Zu", "opening": "Öffnet",
        "closing": "Schliesst", "locked": "Verriegelt", "unlocked": "Offen", "playing": "Spielt",
        "paused": "Pausiert", "idle": "Bereit", "standby": "Standby", "home": "Zuhause",
        "not_home": "Abwesend", "heat": "Heizen", "cool": "Kühlen", "auto": "Auto",
        "cleaning": "Reinigt", "docked": "Angedockt", "unavailable": "nicht verfügbar",
        "unknown": "unbekannt",
    },
    "en": {
        "on": "On", "off": "Off", "open": "Open", "closed": "Closed", "opening": "Opening",
        "closing": "Closing", "locked": "Locked", "unlocked": "Unlocked", "playing": "Playing",
        "paused": "Paused", "idle": "Idle", "standby": "Standby", "home": "Home",
        "not_home": "Away", "heat": "Heat", "cool": "Cool", "auto": "Auto",
        "cleaning": "Cleaning", "docked": "Docked", "unavailable": "unavailable",
        "unknown": "unknown",
    },
}
UI_LABELS = {
    "de": {"back": "Zurück"},
    "en": {"back": "Back"},
}


BLANK = KeyVisual(background=EMPTY_BG)


def _lang(hass: HomeAssistant) -> str:
    return "de" if (hass.config.language or "").startswith("de") else "en"


def _icon_name(value: str | None) -> str | None:
    if value and value.startswith("mdi:"):
        return value[4:]
    return None


def default_icon(state: State, active: bool) -> str | None:
    """Icon matching the entity and its state when the key sets none."""
    if custom := _icon_name(state.attributes.get("icon")):
        return custom
    pair = None
    if state.domain == "binary_sensor":
        pair = BINARY_SENSOR_ICONS.get(state.attributes.get("device_class", ""))
        if pair is None:
            pair = ("checkbox-marked-circle", "checkbox-blank-circle-outline")
    else:
        pair = DOMAIN_STATE_ICONS.get(state.domain)
    if pair:
        return pair[0] if active else pair[1]
    return DOMAIN_ICONS.get(state.domain)


def is_active(state: State) -> bool:
    """Return True when the entity should be drawn in its 'on' colour."""
    if state.domain in NEUTRAL_DOMAINS:
        return True
    return state.state in ON_STATES


def format_state(hass: HomeAssistant, state: State) -> str:
    """Short, human readable state for the second line."""
    labels = STATE_LABELS[_lang(hass)]
    value = state.state
    text = labels.get(value, value)
    attrs = state.attributes

    if state.domain == "light" and value == "on" and attrs.get("brightness") is not None:
        return f"{text} · {round(attrs['brightness'] / 255 * 100)} %"
    if state.domain == "cover" and attrs.get("current_position") is not None and value not in ("closed",):
        return f"{text} · {attrs['current_position']} %"
    if state.domain == "climate" and attrs.get("current_temperature") is not None:
        return f"{attrs['current_temperature']}°"
    if state.domain == "media_player" and value == "playing" and attrs.get("media_title"):
        return str(attrs["media_title"])
    if unit := attrs.get(ATTR_UNIT_OF_MEASUREMENT):
        try:
            number = float(value)
        except ValueError:
            return f"{value} {unit}"
        shown = f"{number:.1f}" if not number.is_integer() else f"{int(number)}"
        if _lang(hass) == "de":
            shown = shown.replace(".", ",")
        return f"{shown} {unit}"
    return text


def back_visual(hass: HomeAssistant) -> KeyVisual:
    """The reserved first key of a folder."""
    return KeyVisual(
        title=UI_LABELS[_lang(hass)]["back"], icon="arrow-left", background=NAV_BG
    )


def key_visual(hass: HomeAssistant, key: dict[str, Any] | None) -> KeyVisual:
    """Compute the visual of a configured key (None = unassigned)."""
    if not key:
        return BLANK

    state = hass.states.get(key["entity_id"]) if key.get("entity_id") else None
    title = key.get("title") or ""
    icon_on = _icon_name(key.get("icon"))
    icon_off = _icon_name(key.get("icon_off")) or icon_on
    icon = icon_on

    if key.get("entity_id"):
        # A scene that never ran is "unknown" but perfectly usable
        if (
            state is None
            or state.state == STATE_UNAVAILABLE
            or (state.state == STATE_UNKNOWN and state.domain not in NEUTRAL_DOMAINS)
        ):
            return KeyVisual(
                title=title or (state.name if state else key["entity_id"]),
                subtitle=STATE_LABELS[_lang(hass)]["unavailable"],
                icon=icon_off or (DOMAIN_ICONS.get(key["entity_id"].split(".")[0])),
                background=OFFLINE_BG,
                foreground=OFFLINE_FG,
                font_size=key.get("font_size"),
            )
        title = title or str(state.attributes.get(ATTR_FRIENDLY_NAME, state.entity_id))
        active = is_active(state)
        icon = (icon_on if active else icon_off) or default_icon(state, active)
    else:
        active = True

    second = key.get("second_line", SECOND_LINE_STATE)
    if second == SECOND_LINE_TEXT:
        subtitle = key.get("second_text") or ""
    elif second == SECOND_LINE_STATE and state is not None:
        subtitle = format_state(hass, state)
    else:
        subtitle = ""
    if second == SECOND_LINE_NONE:
        subtitle = ""

    return KeyVisual(
        title=title,
        subtitle=subtitle,
        icon=icon,
        background=key["on_color"] if active else key["off_color"],
        foreground=key.get("text_color"),
        font_size=key.get("font_size"),
        image=key.get("image"),
    )
