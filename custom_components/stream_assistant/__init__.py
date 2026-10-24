"""Stream Assistant: Stream Decks driven directly by Home Assistant (Network Dock, bridge, virtual panels)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .bridge_hub import BridgeHub
from .const import CONF_DEVICES, CONF_KIND, DOMAIN, KIND_BRIDGE, KIND_PLANNER, PLATFORMS
from .device import StreamAssistantConfigEntry, StreamAssistantDevice, async_remove_layout, deck_key
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


def _kind(entry: StreamAssistantConfigEntry) -> str | None:
    return entry.data.get(CONF_KIND)


async def async_setup_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Set up a dock, bridge or virtual panel."""
    if _kind(entry) == KIND_PLANNER:
        # Nothing to connect to: the entry only makes HA load the editor (async_setup)
        entry.runtime_data = None
        return True
    runtime: StreamAssistantDevice | BridgeHub
    if _kind(entry) == KIND_BRIDGE:
        runtime = BridgeHub(hass, entry)
    else:
        runtime = StreamAssistantDevice(hass, entry)
    entry.runtime_data = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> bool:
    """Unload a config entry."""
    if _kind(entry) == KIND_PLANNER:
        return True
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> None:
    """Delete what the entry stored (layouts, behaviour); runs after unloading."""
    if _kind(entry) == KIND_PLANNER:
        return
    if _kind(entry) == KIND_BRIDGE:
        for device_id in entry.data.get(CONF_DEVICES, {}):
            await async_remove_layout(hass, deck_key(entry.entry_id, device_id))
        return
    await async_remove_layout(hass, entry.entry_id)
