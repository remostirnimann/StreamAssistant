"""Base entity for Stream Assistant, and how platforms find the decks of an entry."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import signal_new_device, signal_state
from .device import StreamAssistantConfigEntry, StreamAssistantDevice


def entry_devices(entry: StreamAssistantConfigEntry) -> list[StreamAssistantDevice]:
    """Decks of a loaded entry: one for a dock or virtual panel, any number for a bridge."""
    data = entry.runtime_data
    if data is None:
        return []
    if isinstance(data, StreamAssistantDevice):
        return [data]
    return list(data.devices.values())


@callback
def async_setup_decks(
    hass: HomeAssistant,
    entry: StreamAssistantConfigEntry,
    add: Callable[[StreamAssistantDevice], None],
) -> None:
    """Call add for every deck of the entry now, and for decks a bridge reports later."""
    for device in entry_devices(entry):
        add(device)
    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_device(entry.entry_id), add))


class StreamAssistantEntity(Entity):
    """Entity that follows the connection state of its deck."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        self.device = device

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_state(self.device.key), self._on_state)
        )

    @callback
    def _on_state(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Entities of the deck are only available while it is connected."""
        return self.device.deck_connected
