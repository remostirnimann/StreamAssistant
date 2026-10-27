"""Update entity per bridge: shows the bridge's version and installs the matching release."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .bridge_hub import BridgeHub
from .const import RELEASE_URL, signal_hub_state
from .device import StreamAssistantConfigEntry
from .protocol.bridge import BridgeError

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StreamAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One update entity per bridge."""
    if isinstance(entry.runtime_data, BridgeHub):
        async_add_entities([BridgeUpdate(entry.runtime_data)])


class BridgeUpdate(UpdateEntity):
    """The bridge's software: the version it runs, and the one that fits this integration.

    The bridge and the integration are released together, so the latest version is the
    integration's own. Bridges that can update themselves get an Install button; Home
    Assistant then waits until the bridge is back with the new version.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_title = "Stream Assistant Bridge"

    def __init__(self, hub: BridgeHub) -> None:
        """Initialize."""
        self.hub = hub
        self._attr_unique_id = f"bridge-{hub.bridge_id}_update"
        self._attr_device_info = hub.device_info

    async def async_added_to_hass(self) -> None:
        """Follow connection and update progress."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, signal_hub_state(self.hub.entry.entry_id), self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Known while connected, and while an update restarts the bridge."""
        return self.hub.connected or self.hub.update_in_progress

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Install only on bridges that can update themselves."""
        if self.hub.can_update:
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
        return UpdateEntityFeature(0)

    @property
    def installed_version(self) -> str | None:
        """The version the bridge runs."""
        return self.hub.bridge_version

    @property
    def latest_version(self) -> str | None:
        """The version that fits this integration (no offer for development builds)."""
        return self.hub.latest_version or self.hub.bridge_version

    @property
    def release_url(self) -> str | None:
        """Release notes of the latest version."""
        return RELEASE_URL.format(version=self.hub.latest_version) if self.hub.latest_version else None

    @property
    def in_progress(self) -> bool:
        """True from Install until the bridge is back with the new version."""
        return self.hub.update_in_progress

    @property
    def auto_update(self) -> bool:
        """The bridge updates itself when the integration was updated (entry option)."""
        return self.hub.auto_update

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Ask the bridge to install the version and wait until it is back."""
        target = version or self.hub.latest_version
        if not target:
            raise HomeAssistantError("No version to install")
        try:
            await self.hub.async_update_bridge(target)
        except BridgeError as err:
            raise HomeAssistantError(f"The bridge could not be updated: {err}") from err
