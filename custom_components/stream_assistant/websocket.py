"""WebSocket API used by the Stream Assistant panel."""

from __future__ import annotations

import base64
from functools import cache
import json
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .device import StreamAssistantDevice
from .layout import PAGE_SCHEMA, validate_layout
from .render import ASSETS


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all commands."""
    websocket_api.async_register_command(hass, ws_entries)
    websocket_api.async_register_command(hass, ws_get_layout)
    websocket_api.async_register_command(hass, ws_save_layout)
    websocket_api.async_register_command(hass, ws_preview)
    websocket_api.async_register_command(hass, ws_show_page)
    websocket_api.async_register_command(hass, ws_press)
    websocket_api.async_register_command(hass, ws_icons)


def _device(hass: HomeAssistant, entry_id: str) -> StreamAssistantDevice | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data


def _model_info(device: StreamAssistantDevice) -> dict[str, Any] | None:
    if not device.model:
        return None
    m = device.model
    return {"name": m.name, "cols": m.cols, "rows": m.rows, "key_count": m.key_count, "key_size": m.key_size}


def _summary(device: StreamAssistantDevice) -> dict[str, Any]:
    return {
        "entry_id": device.entry.entry_id,
        "title": device.entry.title,
        "model": _model_info(device),
        "dock_connected": device.dock_connected,
        "deck_connected": device.deck_connected,
        "current_page": device.current_page,
        "host": device.client.host,
    }


@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/entries"})
@callback
def ws_entries(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List all configured docks."""
    devices = [
        _device(hass, entry.entry_id) for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], [_summary(d) for d in devices if d is not None])


@websocket_api.websocket_command(
    {vol.Required("type"): "stream_assistant/layout/get", vol.Required("entry_id"): str}
)
@callback
def ws_get_layout(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the layout of one dock."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    connection.send_result(
        msg["id"], {**_summary(device), "layout": device.layout, "revision": device.layout_revision}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/layout/save",
        vol.Required("entry_id"): str,
        vol.Required("layout"): dict,
        # Revision the editor started from; a mismatch means someone else saved meanwhile
        vol.Optional("revision"): str,
    }
)
@websocket_api.async_response
async def ws_save_layout(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Validate, store and show a new layout."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    if "revision" in msg and msg["revision"] != device.layout_revision:
        connection.send_error(msg["id"], "conflict", "The layout was changed elsewhere")
        return
    try:
        layout = validate_layout(msg["layout"], device.model.key_count if device.model else None)
    except vol.Invalid as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    await device.async_set_layout(layout)
    connection.send_result(msg["id"], {"layout": layout, "revision": device.layout_revision})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/preview",
        vol.Required("entry_id"): str,
        vol.Required("page"): dict,
    }
)
@websocket_api.async_response
async def ws_preview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Render every key of a (possibly unsaved) page with live entity states."""
    if (device := _device(hass, msg["entry_id"])) is None or device.model is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or no deck attached")
        return
    try:
        page = PAGE_SCHEMA(msg["page"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    images = await device.async_render_page_preview(page)
    connection.send_result(
        msg["id"], {"images": [base64.b64encode(img).decode("ascii") for img in images]}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/show_page",
        vol.Required("entry_id"): str,
        vol.Required("page_id"): str,
    }
)
@websocket_api.async_response
async def ws_show_page(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Switch the deck to a page."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    await device.async_show_page(msg["page_id"])
    connection.send_result(msg["id"], {"current_page": device.current_page})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/press",
        vol.Required("entry_id"): str,
        vol.Required("key"): vol.All(int, vol.Range(min=0)),
        vol.Optional("long", default=False): bool,
        # The editor's draft of the page, so unsaved changes can be tested
        vol.Optional("page"): dict,
    }
)
@websocket_api.async_response
async def ws_press(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Simulate a key press: fires the key events and runs the key's action."""
    if (device := _device(hass, msg["entry_id"])) is None or device.model is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or no deck attached")
        return
    if msg["key"] >= device.model.key_count:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Key does not exist")
        return
    page = None
    if "page" in msg:
        try:
            page = PAGE_SCHEMA(msg["page"])
        except vol.Invalid as err:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
            return
    await device.async_simulate_press(msg["key"], msg["long"], page)
    connection.send_result(msg["id"])


@cache
def _icon_names() -> list[str]:
    return sorted(json.loads((ASSETS / "mdi.json").read_text(encoding="utf-8")))


@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/icons"})
@websocket_api.async_response
async def ws_icons(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Names of all icons the renderer knows (without 'mdi:')."""
    names = await hass.async_add_executor_job(_icon_names)
    connection.send_result(msg["id"], names)
