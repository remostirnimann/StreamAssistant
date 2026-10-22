"""Connection state of the dock and its deck."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
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
    """Add the connectivity sensor."""
    async_add_entities([DeckConnectedSensor(entry.runtime_data)])


class DeckConnectedSensor(StreamAssistantEntity, BinarySensorEntity):
    """On while the dock is reachable and a supported deck is attached."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "deck_connected"

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        super().__init__(device)
        self._attr_unique_id = f"{device.dock_serial}_deck_connected"
        self._attr_device_info = device.dock_device_info

    @property
    def available(self) -> bool:
        """Always available, it reports the connection itself."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the deck is connected."""
        return self.device.deck_connected
