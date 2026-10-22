"""Base entity for Stream Assistant."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import signal_state
from .device import StreamAssistantDevice


class StreamAssistantEntity(Entity):
    """Entity that follows the connection state of its dock."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: StreamAssistantDevice) -> None:
        """Initialize."""
        self.device = device

    async def async_added_to_hass(self) -> None:
        """Subscribe to connection state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_state(self.device.entry.entry_id), self._on_state
            )
        )

    @callback
    def _on_state(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Entities of the deck are only available while it is connected."""
        return self.device.deck_connected
