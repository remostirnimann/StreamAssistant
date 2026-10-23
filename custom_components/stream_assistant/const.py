"""Constants for Stream Assistant."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stream_assistant"
VERSION = "0.2.3"
PANEL_URL = "stream-assistant"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.NUMBER]

CONF_DOCK_SERIAL = "dock_serial"
CONF_DECK_SERIAL = "deck_serial"
CONF_DECK_PRODUCT_ID = "deck_product_id"

LONG_PRESS_SECONDS = 0.5

EVENT_PRESSED = "pressed"
EVENT_RELEASED = "released"
EVENT_SHORT_PRESS = "short_press"
EVENT_LONG_PRESS = "long_press"
KEY_EVENT_TYPES = [EVENT_PRESSED, EVENT_RELEASED, EVENT_SHORT_PRESS, EVENT_LONG_PRESS]

SERVICE_SET_KEY = "set_key"
SERVICE_CLEAR_KEY = "clear_key"

ATTR_TEXT = "text"
ATTR_BACKGROUND_COLOR = "background_color"
ATTR_TEXT_COLOR = "text_color"
ATTR_FONT_SIZE = "font_size"
ATTR_IMAGE = "image"


def signal_state(entry_id: str) -> str:
    """Dispatcher signal for connection state changes."""
    return f"{DOMAIN}_{entry_id}_state"


def signal_key(entry_id: str, key: int) -> str:
    """Dispatcher signal for events of one key."""
    return f"{DOMAIN}_{entry_id}_key_{key}"
