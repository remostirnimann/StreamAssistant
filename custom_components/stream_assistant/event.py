"""Event entities: one per key and dial, one for the touch strip."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform, entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from .const import (
    ATTR_BACKGROUND_COLOR,
    ATTR_FONT_SIZE,
    ATTR_IMAGE,
    ATTR_TEXT,
    ATTR_TEXT_COLOR,
    DIAL_EVENT_TYPES,
    KEY_EVENT_TYPES,
    SERVICE_CLEAR_KEY,
    SERVICE_SET_KEY,
    TOUCH_EVENT_TYPES,
    signal_dial,
    signal_key,
    signal_touch,
)
from .device import StreamAssistantConfigEntry, StreamAssistantDevice
from .entity import StreamAssistantEntity, async_setup_decks

PARALLEL_UPDATES = 0
DEFAULT_BACKGROUND = "#000000"
DEFAULT_TEXT_COLOR = "#ffffff"


def _color(value: Any) -> str:
    """Accept '#rrggbb', a CSS colour name or an [r, g, b] list."""
    if isinstance(value, (list, tuple)):
        r, g, b = vol.Schema(vol.ExactSequence([cv.byte, cv.byte, cv.byte]))(list(value))
        return f"#{r:02x}{g:02x}{b:02x}"
    value = cv.string(value)
    from PIL import ImageColor

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
    """Create the event entities of every deck."""

    @callback
    def add(device: StreamAssistantDevice) -> None:
        if device.model is None or device.deck_serial is None:
            return
        _remove_surplus_keys(hass, entry, device)
        entities: list[EventEntity] = [StreamDeckKeyEvent(device, key) for key in range(device.model.key_count)]
        entities.extend(StreamDeckDialEvent(device, dial) for dial in range(device.model.dials))
        if device.model.has_touch:
            entities.append(StreamDeckTouchEvent(device))
        async_add_entities(entities)

    async_setup_decks(hass, entry, add)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_SET_KEY, SET_KEY_SCHEMA, "async_set_key")
    platform.async_register_entity_service(SERVICE_CLEAR_KEY, None, "async_clear_key")


def _remove_surplus_keys(hass: HomeAssistant, entry: StreamAssistantConfigEntry, device: StreamAssistantDevice) -> None:
    """Drop key and dial entities the deck no longer has (a smaller grid, other controls)."""
    assert device.model
    registry = er.async_get(hass)
    limits = {f"{device.deck_serial}_key_": device.model.key_count, f"{device.deck_serial}_dial_": device.model.dials}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain != "event":
            continue
        if entity.unique_id == f"{device.deck_serial}_touch" and not device.model.has_touch:
            registry.async_remove(entity.entity_id)
            continue
        for prefix, count in limits.items():
            index = entity.unique_id.removeprefix(prefix)
            if entity.unique_id.startswith(prefix) and index.isdigit() and int(index) >= count:
                registry.async_remove(entity.entity_id)


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
                signal_key(self.device.key, self.key),
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


class StreamDeckDialEvent(StreamAssistantEntity, EventEntity):
    """A dial: fires rotate_left/rotate_right (with steps) and the press events."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = DIAL_EVENT_TYPES
    _attr_translation_key = "dial"

    def __init__(self, device: StreamAssistantDevice, dial: int) -> None:
        """Initialize."""
        super().__init__(device)
        assert device.deck_serial
        self.dial = dial
        self._attr_unique_id = f"{device.deck_serial}_dial_{dial}"
        self._attr_device_info = device.deck_device_info
        self._attr_translation_placeholders = {"dial": str(dial + 1)}
        self._attr_extra_state_attributes = {"dial": dial}

    async def async_added_to_hass(self) -> None:
        """Subscribe to this dial's events."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_dial(self.device.key, self.dial), self._on_dial_event)
        )

    @callback
    def _on_dial_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        self._trigger_event(event_type, data)
        self.async_write_ha_state()


class StreamDeckTouchEvent(StreamAssistantEntity, EventEntity):
    """The touch strip: fires tap, long_press, swipe_left and swipe_right with the position."""

    _attr_event_types = TOUCH_EVENT_TYPES
    _attr_translation_key = "touch_strip"

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        super().__init__(device)
        assert device.deck_serial
        self._attr_unique_id = f"{device.deck_serial}_touch"
        self._attr_device_info = device.deck_device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to the strip's events."""
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(self.hass, signal_touch(self.device.key), self._on_touch_event))

    @callback
    def _on_touch_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
