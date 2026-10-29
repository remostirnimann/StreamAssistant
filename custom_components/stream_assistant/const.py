"""Constants for Stream Assistant."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "stream_assistant"
VERSION = "0.9.0"
PANEL_URL = "stream-assistant"

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.NUMBER, Platform.UPDATE]

CONF_DOCK_SERIAL = "dock_serial"
CONF_DECK_SERIAL = "deck_serial"
CONF_DECK_PRODUCT_ID = "deck_product_id"

# A config entry without a dock: only loads the editor for planning templates
CONF_KIND = "kind"
KIND_PLANNER = "planner"
PLANNER_UNIQUE_ID = "planner"
KIND_DOCK = "dock"
# A Stream Assistant Bridge with any number of decks (docs/bridge-protocol.md)
KIND_BRIDGE = "bridge"
CONF_PORT = "port"
CONF_BRIDGE_ID = "bridge_id"
CONF_TOKEN = "token"
# Devices seen on a bridge, so their entities exist while it is offline
CONF_DEVICES = "devices"
# Entry option of bridges: install the bridge release that fits the integration on its own
CONF_AUTO_UPDATE = "auto_update"
RELEASE_URL = "https://github.com/remostirnimann/StreamAssistant/releases/tag/v{version}"
# How long Home Assistant waits for a bridge to come back with the new version
BRIDGE_UPDATE_TIMEOUT = 900
# A panel that only exists in Home Assistant (dashboard card), with a free grid
KIND_VIRTUAL = "virtual"
CONF_COLS = "cols"
CONF_ROWS = "rows"

LONG_PRESS_SECONDS = 0.5

EVENT_PRESSED = "pressed"
EVENT_RELEASED = "released"
EVENT_SHORT_PRESS = "short_press"
EVENT_LONG_PRESS = "long_press"
KEY_EVENT_TYPES = [EVENT_PRESSED, EVENT_RELEASED, EVENT_SHORT_PRESS, EVENT_LONG_PRESS]
EVENT_ROTATE_LEFT = "rotate_left"
EVENT_ROTATE_RIGHT = "rotate_right"
DIAL_EVENT_TYPES = [EVENT_ROTATE_LEFT, EVENT_ROTATE_RIGHT, *KEY_EVENT_TYPES]
EVENT_TAP = "tap"
EVENT_SWIPE_LEFT = "swipe_left"
EVENT_SWIPE_RIGHT = "swipe_right"
TOUCH_EVENT_TYPES = [EVENT_TAP, EVENT_LONG_PRESS, EVENT_SWIPE_LEFT, EVENT_SWIPE_RIGHT]
# Dial detents collected into one adjustment
DIAL_SETTLE_SECONDS = 0.1
# How long the value of the last adjustment counts while the entity catches up
DIAL_BASE_SECONDS = 2.0

SERVICE_SET_KEY = "set_key"
SERVICE_CLEAR_KEY = "clear_key"

ATTR_TEXT = "text"
ATTR_BACKGROUND_COLOR = "background_color"
ATTR_TEXT_COLOR = "text_color"
ATTR_FONT_SIZE = "font_size"
ATTR_IMAGE = "image"


def signal_state(deck: str) -> str:
    """Dispatcher signal for state changes of one deck (see StreamAssistantDevice.key)."""
    return f"{DOMAIN}_{deck}_state"


def signal_key(deck: str, key: int) -> str:
    """Dispatcher signal for events of one key of a deck."""
    return f"{DOMAIN}_{deck}_key_{key}"


def signal_dial(deck: str, dial: int) -> str:
    """Dispatcher signal for events of one dial of a deck."""
    return f"{DOMAIN}_{deck}_dial_{dial}"


def signal_button(deck: str, button: int) -> str:
    """Dispatcher signal for events of a button outside the grid (page buttons)."""
    return f"{DOMAIN}_{deck}_button_{button}"


def signal_touch(deck: str) -> str:
    """Dispatcher signal for events of the touch strip of a deck."""
    return f"{DOMAIN}_{deck}_touch"


def signal_new_device(entry_id: str) -> str:
    """Dispatcher signal: a bridge entry got a new deck (argument: the device)."""
    return f"{DOMAIN}_{entry_id}_new_device"


def signal_hub_state(entry_id: str) -> str:
    """Dispatcher signal for connection changes of a bridge."""
    return f"{DOMAIN}_{entry_id}_hub_state"
