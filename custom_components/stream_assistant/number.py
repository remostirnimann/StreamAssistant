"""Brightness of the Stream Deck panel."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .device import StreamAssistantConfigEntry, StreamAssistantDevice
from .entity import StreamAssistantEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the brightness entity."""
    device = entry.runtime_data
    if device.model is None or device.deck_serial is None:
        return
    async_add_entities([StreamDeckBrightness(device)])


class StreamDeckBrightness(StreamAssistantEntity, RestoreNumber):
    """Panel brightness in percent, restored after restarts."""

    _attr_translation_key = "brightness"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        super().__init__(device)
        self._attr_unique_id = f"{device.deck_serial}_brightness"
        self._attr_device_info = device.deck_device_info

    async def async_added_to_hass(self) -> None:
        """Restore the last brightness and apply it."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            await self.device.async_set_brightness(int(last.native_value))

    @property
    def native_value(self) -> float:
        """Return the brightness."""
        return self.device.brightness

    async def async_set_native_value(self, value: float) -> None:
        """Set the brightness."""
        await self.device.async_set_brightness(int(value))
        self.async_write_ha_state()
