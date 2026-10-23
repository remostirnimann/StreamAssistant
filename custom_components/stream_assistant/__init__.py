"""Stream Assistant: Elgato Stream Deck Network Dock, driven directly by Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import DOMAIN, PLATFORMS
from .device import StreamAssistantConfigEntry, StreamAssistantDevice
from .panel import async_register_panel
from .templates import DATA_TEMPLATES, TemplateManager

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Load templates, register the editor panel and its WebSocket API once."""
    templates = TemplateManager(hass)
    await templates.async_load()
    hass.data[DATA_TEMPLATES] = templates
    websocket.async_register(hass)
    await async_register_panel(hass)
    return True


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
