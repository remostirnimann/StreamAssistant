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
    """Add one connectivity sensor for the dock and one for the deck."""
    device = entry.runtime_data
    async_add_entities([DockConnectedSensor(device), DeckConnectedSensor(device)])


class _ConnectivitySensor(StreamAssistantEntity, BinarySensorEntity):
    """Connectivity sensor, always available since it reports the connection itself."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Always available."""
        return True


class DockConnectedSensor(_ConnectivitySensor):
    """On while the dock is reachable over the network."""

    _attr_translation_key = "dock_connected"

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        super().__init__(device)
        self._attr_unique_id = f"{device.dock_serial}_dock_connected"
        self._attr_device_info = device.dock_device_info

    @property
    def is_on(self) -> bool:
        """Return True when the dock is reachable."""
        return self.device.dock_connected


class DeckConnectedSensor(_ConnectivitySensor):
    """On while a supported deck is attached to the dock and connected."""

    _attr_translation_key = "deck_connected"

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        super().__init__(device)
        # Unique id kept from the first version, the entity moves to the deck device
        self._attr_unique_id = f"{device.dock_serial}_deck_connected"
        # Without a known deck there is no deck device yet, show it on the dock
        if device.model and device.deck_serial:
            self._attr_device_info = device.deck_device_info
        else:
            self._attr_device_info = device.dock_device_info

    @property
    def is_on(self) -> bool:
        """Return True when the deck is connected."""
        return self.device.deck_connected
