"""WebSocket API used by the Stream Assistant panel.

Layout commands address either a deck (`entry_id`: the deck's key, the
config entry id for docks and virtual panels, "<entry id>.<device id>" for
bridge decks) or a template (`template_id`, a planned deck without hardware).

All editor commands are admin-only, like the panel: they expose addresses,
serial numbers and the layout (entity ids), or change things.

The panel/* commands serve the dashboard card of virtual panels and are open
to every user: they only show key images and press keys, like a real deck
hanging on the wall.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import cache
import json
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .actions import async_run_action
from .behavior import BEHAVIOR_SCHEMA
from .const import DOMAIN
from .device import StreamAssistantDevice
from .display import page_key_slot
from .entity import entry_devices
from .layout import ACTION_CALL, ACTION_DEFAULT, PAGE_SCHEMA, validate_layout
from .capabilities import CATALOG, DeckCapabilities, find_capabilities
from .render import ASSETS
from .templates import DATA_TEMPLATES, TemplateManager
from .transport import VirtualTransport

TARGET = {vol.Exclusive("entry_id", "target"): str, vol.Exclusive("template_id", "target"): str}


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register all commands."""
    for command in (
        ws_entries,
        ws_models,
        ws_get_layout,
        ws_save_layout,
        ws_preview,
        ws_show_page,
        ws_press,
        ws_icons,
        ws_template_create,
        ws_template_rename,
        ws_template_delete,
        ws_link,
        ws_detach,
        ws_info,
        ws_set_behavior,
        ws_panel_list,
        ws_panel_subscribe,
        ws_panel_press,
    ):
        websocket_api.async_register_command(hass, command)


@dataclass
class Target:
    """What a layout command works on."""

    model: DeckCapabilities | None
    device: StreamAssistantDevice | None = None
    template_id: str | None = None


def _devices(hass: HomeAssistant) -> list[StreamAssistantDevice]:
    """All decks of all loaded entries."""
    return [
        device
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        for device in entry_devices(entry)
    ]


def _device(hass: HomeAssistant, key: str) -> StreamAssistantDevice | None:
    return next((d for d in _devices(hass) if d.key == key), None)


def _templates(hass: HomeAssistant) -> TemplateManager:
    return hass.data[DATA_TEMPLATES]


def _target(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> Target | None:
    """Resolve entry_id / template_id, sending an error when it does not exist."""
    if "entry_id" in msg:
        if (device := _device(hass, msg["entry_id"])) is not None:
            return Target(model=device.model, device=device)
    elif "template_id" in msg:
        if _templates(hass).get(msg["template_id"]) is not None:
            return Target(model=_templates(hass).model(msg["template_id"]), template_id=msg["template_id"])
    connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock or template not found")
    return None


def _model_info(model: DeckCapabilities | None) -> dict[str, Any] | None:
    if not model:
        return None
    return {
        "id": model.model_id,
        "name": model.name,
        "cols": model.cols,
        "rows": model.rows,
        "key_count": model.key_count,
        "key_size": model.key_size,
    }


def _entry_summary(device: StreamAssistantDevice) -> dict[str, Any]:
    return {
        "entry_id": device.key,
        "title": device.title,
        "kind": device.kind,
        "virtual": device.virtual,
        "model": _model_info(device.model),
        "dock_connected": device.dock_connected,
        "deck_connected": device.deck_connected,
        "current_page": device.current_page,
        "host": device.transport.hub_info().get("host"),
        "template_id": device.template_id,
        "template_dropped": device.template_dropped,
    }


def _template_summary(hass: HomeAssistant, template: dict[str, Any]) -> dict[str, Any]:
    linked = [d.title for d in _devices(hass) if d.template_id == template["id"]]
    return {
        "template_id": template["id"],
        "title": template["name"],
        "model": _model_info(find_capabilities(template["model"])),
        "linked": linked,
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/entries"})
@callback
def ws_entries(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List docks and templates."""
    connection.send_result(
        msg["id"],
        {
            "entries": [_entry_summary(d) for d in _devices(hass)],
            "templates": [_template_summary(hass, t) for t in _templates(hass).list()],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/models"})
@callback
def ws_models(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Models a template can be planned for."""
    connection.send_result(msg["id"], [_model_info(m) for m in CATALOG])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/layout/get", **TARGET})
@callback
def ws_get_layout(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the layout of a dock or template."""
    if (target := _target(hass, connection, msg)) is None:
        return
    if target.device:
        device = target.device
        result = {**_entry_summary(device), "layout": device.layout, "revision": device.layout_revision}
    else:
        manager = _templates(hass)
        template = manager.get(target.template_id)
        result = {
            **_template_summary(hass, template),
            "layout": template["layout"],
            "revision": manager.revision(target.template_id),
        }
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/layout/save",
        **TARGET,
        vol.Required("layout"): dict,
        # Revision the editor started from; a mismatch means someone else saved meanwhile
        vol.Optional("revision"): str,
    }
)
@websocket_api.async_response
async def ws_save_layout(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Validate, store and show a new layout."""
    if (target := _target(hass, connection, msg)) is None:
        return
    manager = _templates(hass)
    current = target.device.layout_revision if target.device else manager.revision(target.template_id)
    if "revision" in msg and msg["revision"] != current:
        connection.send_error(msg["id"], "conflict", "The layout was changed elsewhere")
        return
    try:
        layout = validate_layout(msg["layout"], target.model.key_count if target.model else None)
    except vol.Invalid as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    if target.device:
        await target.device.async_set_layout(layout)
        revision = target.device.layout_revision
        layout = target.device.layout
    else:
        await manager.async_set_layout(target.template_id, layout)
        revision = manager.revision(target.template_id)
    connection.send_result(msg["id"], {"layout": layout, "revision": revision})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "stream_assistant/preview", **TARGET, vol.Required("page"): dict}
)
@websocket_api.async_response
async def ws_preview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Render every key of a (possibly unsaved) page with live entity states."""
    if (target := _target(hass, connection, msg)) is None:
        return
    if target.model is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "No deck attached")
        return
    try:
        page = PAGE_SCHEMA(msg["page"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    renderer = _templates(hass).renderer
    images = await renderer.async_page_preview(target.model, page)
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
        **TARGET,
        vol.Required("key"): vol.All(int, vol.Range(min=0)),
        vol.Optional("long", default=False): bool,
        # The editor's draft of the page, so unsaved changes can be tested
        vol.Optional("page"): dict,
    }
)
@websocket_api.async_response
async def ws_press(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Simulate a key press.

    On a dock: fires the key events and runs the action, like a real press.
    On a template: there are no key entities, so only the Home Assistant action runs.
    """
    if (target := _target(hass, connection, msg)) is None:
        return
    if target.model is None or msg["key"] >= target.model.key_count:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Key does not exist")
        return
    page = None
    if "page" in msg:
        try:
            page = PAGE_SCHEMA(msg["page"])
        except vol.Invalid as err:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
            return
    if target.device:
        await target.device.async_simulate_press(msg["key"], msg["long"], page)
    elif page is not None:
        key, _ = page_key_slot(page, msg["key"])
        action = key["long" if msg["long"] else "short"] if key else None
        if action and action["type"] in (ACTION_DEFAULT, ACTION_CALL):
            await async_run_action(hass, action)
    connection.send_result(msg["id"])


@cache
def _icon_names() -> list[str]:
    return sorted(json.loads((ASSETS / "mdi.json").read_text(encoding="utf-8")))


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/icons"})
@websocket_api.async_response
async def ws_icons(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Names of all icons the renderer knows (without 'mdi:')."""
    names = await hass.async_add_executor_job(_icon_names)
    connection.send_result(msg["id"], names)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/template/create",
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Optional("model"): str,
        # Start from a dock's layout (and link that dock to the new template)
        vol.Optional("from_entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_template_create(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create a template: empty for a model, or from a dock's layout."""
    manager = _templates(hass)
    layout = None
    device = None
    if "from_entry_id" in msg:
        device = _device(hass, msg["from_entry_id"])
        if device is None or device.model is None:
            connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or no deck attached")
            return
        model = device.model
        layout = device.layout
    else:
        model = find_capabilities(msg.get("model", ""))
        if model is None:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Unknown model")
            return
    template = await manager.async_create(msg["name"], model.model_id, layout)
    if device is not None:
        await device.async_link_template(template["id"])
    connection.send_result(msg["id"], _template_summary(hass, template))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/template/rename",
        vol.Required("template_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
    }
)
@websocket_api.async_response
async def ws_template_rename(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Rename a template."""
    manager = _templates(hass)
    if manager.get(msg["template_id"]) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Template not found")
        return
    await manager.async_rename(msg["template_id"], msg["name"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "stream_assistant/template/delete", vol.Required("template_id"): str}
)
@websocket_api.async_response
async def ws_template_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete a template; linked decks keep a copy of its layout."""
    manager = _templates(hass)
    if manager.get(msg["template_id"]) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Template not found")
        return
    await manager.async_delete(msg["template_id"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/link",
        vol.Required("entry_id"): str,
        vol.Required("template_id"): str,
    }
)
@websocket_api.async_response
async def ws_link(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Link a dock to a template. Reports keys that do not fit the deck."""
    device = _device(hass, msg["entry_id"])
    manager = _templates(hass)
    template_model = manager.model(msg["template_id"])
    if device is None or template_model is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock or template not found")
        return
    await device.async_link_template(msg["template_id"])
    connection.send_result(msg["id"], {"dropped": device.template_dropped})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/info", vol.Required("entry_id"): str})
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Facts about a dock and its deck, plus its automation settings."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    connection.send_result(msg["id"], device.info())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/behavior/set",
        vol.Required("entry_id"): str,
        vol.Required("behavior"): dict,
    }
)
@websocket_api.async_response
async def ws_set_behavior(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Store a dock's automation settings (night brightness, dim when idle)."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    try:
        settings = BEHAVIOR_SCHEMA(msg["behavior"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, str(err))
        return
    await device.async_set_behavior(settings)
    connection.send_result(msg["id"], device.info())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "stream_assistant/detach", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_detach(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Give a dock its own copy of the template layout and stop following it."""
    if (device := _device(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dock not found or not loaded")
        return
    await device.async_detach_template()
    connection.send_result(msg["id"])


# Dashboard card of virtual panels (all users)


def _panel(hass: HomeAssistant, entry_id: str) -> tuple[StreamAssistantDevice, VirtualTransport] | None:
    device = _device(hass, entry_id)
    if device is None or not isinstance(device.transport, VirtualTransport):
        return None
    return device, device.transport


def _b64(image: bytes) -> str:
    return base64.b64encode(image).decode("ascii")


@websocket_api.websocket_command({vol.Required("type"): "stream_assistant/panel/list"})
@callback
def ws_panel_list(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Virtual panels, for the card editor."""
    connection.send_result(
        msg["id"],
        [
            {"entry_id": d.key, "title": d.title, "cols": d.model.cols, "rows": d.model.rows}
            for d in _devices(hass)
            if d.virtual and d.model
        ],
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "stream_assistant/panel/subscribe", vol.Required("entry_id"): str}
)
@callback
def ws_panel_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Send the full panel once, then every changed key image and brightness.

    {"stopped": true} means the panel was reloaded or removed: subscribe again.
    """
    if (found := _panel(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Virtual panel not found or not loaded")
        return
    device, transport = found
    assert device.model

    @callback
    def forward(kind: str, index: int | None) -> None:
        if kind == "image" and index is not None:
            payload: dict[str, Any] = {"key": index, "image": _b64(transport.images[index])}
        elif kind == "brightness":
            payload = {"brightness": transport.brightness}
        else:
            payload = {"stopped": True}
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    connection.subscriptions[msg["id"]] = transport.subscribe(forward)
    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(
            msg["id"],
            {
                "title": device.title,
                "cols": device.model.cols,
                "rows": device.model.rows,
                "brightness": transport.brightness,
                "images": {str(i): _b64(img) for i, img in transport.images.items()},
            },
        )
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/panel/press",
        vol.Required("entry_id"): str,
        vol.Required("key"): vol.All(int, vol.Range(min=0)),
        vol.Required("pressed"): bool,
    }
)
@callback
def ws_panel_press(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """A key of the card went down or up; long presses come from holding it."""
    if (found := _panel(hass, msg["entry_id"])) is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Virtual panel not found or not loaded")
        return
    found[1].press(msg["key"], msg["pressed"])
    connection.send_result(msg["id"])
