"""One event entity per Stream Deck key."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_BACKGROUND_COLOR,
    ATTR_FONT_SIZE,
    ATTR_IMAGE,
    ATTR_TEXT,
    ATTR_TEXT_COLOR,
    KEY_EVENT_TYPES,
    SERVICE_CLEAR_KEY,
    SERVICE_SET_KEY,
    signal_key,
)
from .device import StreamAssistantConfigEntry, StreamAssistantDevice
from .entity import StreamAssistantEntity

PARALLEL_UPDATES = 0
DEFAULT_BACKGROUND = "#000000"
DEFAULT_TEXT_COLOR = "#ffffff"


def _color(value: Any) -> str:
    """Accept '#rrggbb', a CSS colour name or an [r, g, b] list."""
    if isinstance(value, (list, tuple)):
        r, g, b = vol.Schema(vol.ExactSequence([cv.byte, cv.byte, cv.byte]))(list(value))
        return f"#{r:02x}{g:02x}{b:02x}"
    value = cv.string(value)
    from PIL import ImageColor  # noqa: PLC0415

    try:
        r, g, b = ImageColor.getrgb(value)[:3]
    except ValueError as err:
        raise vol.Invalid(f"Invalid colour: {value}") from err
    return f"#{r:02x}{g:02x}{b:02x}"


SET_KEY_SCHEMA = {
    vol.Optional(ATTR_TEXT, default=""): cv.string,
    vol.Optional(ATTR_BACKGROUND_COLOR, default=DEFAULT_BACKGROUND): _color,
    vol.Optional(ATTR_TEXT_COLOR, default=DEFAULT_TEXT_COLOR): _color,
    vol.Optional(ATTR_FONT_SIZE): vol.All(vol.Coerce(int), vol.Range(min=6, max=96)),
    vol.Optional(ATTR_IMAGE): cv.isfile,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one event entity per key of the attached deck."""
    device = entry.runtime_data
    if device.model is None or device.deck_serial is None:
        return
    async_add_entities(
        StreamDeckKeyEvent(device, key) for key in range(device.model.key_count)
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_SET_KEY, SET_KEY_SCHEMA, "async_set_key")
    platform.async_register_entity_service(SERVICE_CLEAR_KEY, None, "async_clear_key")


class StreamDeckKeyEvent(StreamAssistantEntity, EventEntity):
    """A physical key: fires pressed/released/short_press/long_press."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = KEY_EVENT_TYPES
    _attr_translation_key = "key"

    def __init__(self, device: StreamAssistantDevice, key: int) -> None:
        """Initialize."""
        super().__init__(device)
        assert device.model and device.deck_serial
        self.key = key
        self._attr_unique_id = f"{device.deck_serial}_key_{key}"
        self._attr_device_info = device.deck_device_info
        row, col = divmod(key, device.model.cols)
        # Shown 1-based, like on the deck
        self._attr_translation_placeholders = {"key": str(key + 1)}
        self._attr_extra_state_attributes = {"key": key, "row": row, "column": col}

    async def async_added_to_hass(self) -> None:
        """Subscribe to this key's events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_key(self.device.entry.entry_id, self.key),
                self._on_key_event,
            )
        )

    @callback
    def _on_key_event(self, event_type: str) -> None:
        self._trigger_event(event_type)
        self.async_write_ha_state()

    async def async_set_key(self, **kwargs: Any) -> None:
        """Service: change what this key shows (on the page currently shown)."""
        await self.device.async_set_key(self.key, kwargs)

    async def async_clear_key(self) -> None:
        """Service: blank this key."""
        await self.device.async_clear_key(self.key)
