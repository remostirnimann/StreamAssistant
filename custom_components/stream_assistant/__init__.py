"""Stream Assistant: Elgato Stream Deck Network Dock, driven directly by Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .device import StreamAssistantConfigEntry, StreamAssistantDevice


async def async_setup_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Set up a dock from a config entry."""
    device = StreamAssistantDevice(hass, entry)
    entry.runtime_data = device
    await device.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
