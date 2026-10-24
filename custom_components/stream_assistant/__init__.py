"""Stream Assistant: Elgato Stream Deck Network Dock, driven directly by Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import CONF_KIND, DOMAIN, KIND_PLANNER, PLATFORMS
from .device import StreamAssistantConfigEntry, StreamAssistantDevice, async_remove_layout
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


def _is_planner(entry: StreamAssistantConfigEntry) -> bool:
    return entry.data.get(CONF_KIND) == KIND_PLANNER


async def async_setup_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Set up a dock from a config entry."""
    if _is_planner(entry):
        # Nothing to connect to: the entry only makes HA load the editor (async_setup)
        entry.runtime_data = None  # type: ignore[assignment]
        return True
    device = StreamAssistantDevice(hass, entry)
    entry.runtime_data = device
    await device.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Unload a config entry."""
    if _is_planner(entry):
        return True
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> None:
    """Delete what the entry stored (layout, behaviour); runs after unloading."""
    if not _is_planner(entry):
        await async_remove_layout(hass, entry.entry_id)
