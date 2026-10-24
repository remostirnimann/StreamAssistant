"""Connection state of docks, bridges and their decks."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bridge_hub import BridgeHub
from .const import KIND_DOCK, signal_hub_state
from .device import StreamAssistantConfigEntry, StreamAssistantDevice
from .entity import StreamAssistantEntity, async_setup_decks

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Dock: sensors for dock and deck. Bridge: one for the bridge, one per deck."""
    if isinstance(entry.runtime_data, BridgeHub):
        async_add_entities([BridgeConnectedSensor(entry.runtime_data)])

    @callback
    def add(device: StreamAssistantDevice) -> None:
        if device.kind == KIND_DOCK:
            async_add_entities([DockConnectedSensor(device), DeckConnectedSensor(device)])
        elif device.bridge:
            async_add_entities([DeckConnectedSensor(device)])
        # A virtual panel is always "connected", nothing to report

    async_setup_decks(hass, entry, add)


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
        # Dock: unique id kept from the first version, the entity moves to the deck device
        self._attr_unique_id = f"{device.dock_serial or device.deck_serial}_deck_connected"
        # Without a known deck there is no deck device yet, show it on the dock
        if device.model and device.deck_serial:
            self._attr_device_info = device.deck_device_info
        else:
            self._attr_device_info = device.dock_device_info

    @property
    def is_on(self) -> bool:
        """Return True when the deck is connected."""
        return self.device.deck_connected


class BridgeConnectedSensor(BinarySensorEntity):
    """On while the bridge is connected."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "bridge_connected"

    def __init__(self, hub: BridgeHub) -> None:
        """Initialize."""
        self.hub = hub
        self._attr_unique_id = f"bridge-{hub.bridge_id}_connected"
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        """Follow the bridge connection."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_hub_state(self.hub.entry.entry_id), self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        """Return True while connected."""
        return self.hub.connected
