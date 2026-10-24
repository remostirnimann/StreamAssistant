"""WebSocket API of the editor and the dashboard card, templates and the panel."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.stream_assistant.const import DOMAIN
from custom_components.stream_assistant.layout import empty_layout
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .common import SetupEntry, entity_id, virtual_entry, wait_for


@pytest.fixture
async def ws(hass: HomeAssistant, hass_ws_client, setup_entry: SetupEntry):
    """Admin WebSocket client with a 4x2 virtual panel set up."""
    entry = await setup_entry(virtual_entry(4, 2))
    client = await hass_ws_client(hass)
    client.entry_id = entry.entry_id
    return client


async def call(client, **message: Any) -> dict[str, Any]:
    await client.send_json_auto_id(message)
    return await client.receive_json()


def _layout(**keys: dict) -> dict:
    layout = empty_layout()
    layout["pages"][0]["keys"] = {k.lstrip("k"): v for k, v in keys.items()}
    return layout


async def test_entries_models_icons(ws) -> None:
    result = (await call(ws, type="stream_assistant/entries"))["result"]
    assert [e["entry_id"] for e in result["entries"]] == [ws.entry_id]
    assert result["entries"][0]["kind"] == "virtual" and result["templates"] == []
    models = (await call(ws, type="stream_assistant/models"))["result"]
    assert {m["id"] for m in models} == {"mk2", "original_v2", "xl"}
    icons = (await call(ws, type="stream_assistant/icons"))["result"]
    assert "lightbulb" in icons and len(icons) > 5000


async def test_layout_save_get_and_conflicts(hass: HomeAssistant, ws) -> None:
    current = (await call(ws, type="stream_assistant/layout/get", entry_id=ws.entry_id))["result"]
    assert current["model"]["key_count"] == 8
    saved = await call(
        ws, type="stream_assistant/layout/save", entry_id=ws.entry_id, layout=_layout(k1={"title": "a"}), revision=current["revision"]
    )
    assert saved["success"] and saved["result"]["layout"]["pages"][0]["keys"]["1"]["title"] == "a"
    stale = await call(ws, type="stream_assistant/layout/save", entry_id=ws.entry_id, layout=_layout(), revision=current["revision"])
    assert stale["error"]["code"] == "conflict"
    invalid = await call(ws, type="stream_assistant/layout/save", entry_id=ws.entry_id, layout=_layout(k9={}))
    assert invalid["error"]["code"] == "invalid_format"
    missing = await call(ws, type="stream_assistant/layout/get", entry_id="nope")
    assert missing["error"]["code"] == "not_found"


async def test_preview_show_page_press(hass: HomeAssistant, ws) -> None:
    toggles = async_mock_service(hass, "light", "toggle")
    page = _layout(k0={"title": "x", "short": {"type": "default", "entity_id": "light.a"}})["pages"][0]
    preview = (await call(ws, type="stream_assistant/preview", entry_id=ws.entry_id, page=page))["result"]
    assert len(preview["images"]) == 8
    bad = await call(ws, type="stream_assistant/preview", entry_id=ws.entry_id, page={"id": "!"})
    assert bad["error"]["code"] == "invalid_format"

    pressed = await call(ws, type="stream_assistant/press", entry_id=ws.entry_id, key=0, page=page)
    assert pressed["success"]
    await hass.async_block_till_done()
    assert len(toggles) == 1
    long = await call(ws, type="stream_assistant/press", entry_id=ws.entry_id, key=0, long=True)
    assert long["success"]
    out_of_range = await call(ws, type="stream_assistant/press", entry_id=ws.entry_id, key=8)
    assert out_of_range["error"]["code"] == "invalid_format"
    bad_page = await call(ws, type="stream_assistant/press", entry_id=ws.entry_id, key=0, page={"id": "!"})
    assert bad_page["error"]["code"] == "invalid_format"

    shown = await call(ws, type="stream_assistant/show_page", entry_id=ws.entry_id, page_id="main")
    assert shown["result"] == {"current_page": "main"}
    assert (await call(ws, type="stream_assistant/show_page", entry_id="nope", page_id="main"))["error"]["code"] == "not_found"


async def test_info_and_behavior(ws) -> None:
    info = (await call(ws, type="stream_assistant/info", entry_id=ws.entry_id))["result"]
    assert info["virtual"] and not info["behavior"]["night"]["enabled"]
    updated = await call(
        ws, type="stream_assistant/behavior/set", entry_id=ws.entry_id, behavior={"night": {"enabled": True, "mode": "sun"}}
    )
    assert updated["result"]["behavior"]["night"]["enabled"]
    invalid = await call(ws, type="stream_assistant/behavior/set", entry_id=ws.entry_id, behavior={"idle": {"timeout": 1}})
    assert invalid["error"]["code"] == "invalid_format"
    for command in ("info", "behavior/set", "detach"):
        extra = {"behavior": {}} if command == "behavior/set" else {}
        result = await call(ws, type=f"stream_assistant/{command}", entry_id="nope", **extra)
        assert result["error"]["code"] == "not_found"


async def test_templates(hass: HomeAssistant, ws) -> None:
    created = (await call(ws, type="stream_assistant/template/create", name="Büro", model="grid_5x3"))["result"]
    template_id = created["template_id"]
    assert created["model"]["key_count"] == 15
    assert (await call(ws, type="stream_assistant/template/create", name="x", model="nope"))["error"]["code"] == "invalid_format"

    # Template layout with a key outside the 4x2 panel (row 2)
    saved = await call(
        ws,
        type="stream_assistant/layout/save",
        template_id=template_id,
        layout=_layout(k0={"title": "inside"}, k12={"title": "outside"}),
    )
    assert saved["success"]
    preview = await call(ws, type="stream_assistant/preview", template_id=template_id, page=saved["result"]["layout"]["pages"][0])
    assert len(preview["result"]["images"]) == 15
    assert (await call(ws, type="stream_assistant/press", template_id=template_id, key=0))["success"]

    linked = await call(ws, type="stream_assistant/link", entry_id=ws.entry_id, template_id=template_id)
    assert linked["result"] == {"dropped": 1}
    deck = (await call(ws, type="stream_assistant/layout/get", entry_id=ws.entry_id))["result"]
    assert deck["template_id"] == template_id and set(deck["layout"]["pages"][0]["keys"]) == {"0"}

    # Editing on the small panel writes into the template and keeps the hidden key
    await call(ws, type="stream_assistant/layout/save", entry_id=ws.entry_id, layout=_layout(k1={"title": "new"}))
    template = (await call(ws, type="stream_assistant/layout/get", template_id=template_id))["result"]
    assert set(template["layout"]["pages"][0]["keys"]) == {"1", "12"}
    assert template["linked"] == ["Wall panel"]

    assert (await call(ws, type="stream_assistant/template/rename", template_id=template_id, name="Neu"))["success"]
    assert (await call(ws, type="stream_assistant/template/rename", template_id="nope", name="x"))["error"]["code"] == "not_found"

    # Detach keeps a copy
    assert (await call(ws, type="stream_assistant/detach", entry_id=ws.entry_id))["success"]
    deck = (await call(ws, type="stream_assistant/layout/get", entry_id=ws.entry_id))["result"]
    assert deck["template_id"] is None and set(deck["layout"]["pages"][0]["keys"]) == {"1"}

    # Save as template from the deck links it again; deleting the template leaves a copy
    copied = (await call(ws, type="stream_assistant/template/create", name="Kopie", from_entry_id=ws.entry_id))["result"]
    assert copied["linked"] == ["Wall panel"]
    assert (await call(ws, type="stream_assistant/template/delete", template_id=copied["template_id"]))["success"]
    deck = (await call(ws, type="stream_assistant/layout/get", entry_id=ws.entry_id))["result"]
    assert deck["template_id"] is None and set(deck["layout"]["pages"][0]["keys"]) == {"1"}
    assert (await call(ws, type="stream_assistant/template/delete", template_id="nope"))["error"]["code"] == "not_found"
    assert (await call(ws, type="stream_assistant/link", entry_id=ws.entry_id, template_id="nope"))["error"]["code"] == "not_found"
    bad = await call(ws, type="stream_assistant/template/create", name="x", from_entry_id="nope")
    assert bad["error"]["code"] == "not_found"


async def test_editor_is_admin_only_card_is_not(
    hass: HomeAssistant, hass_ws_client, setup_entry: SetupEntry, hass_read_only_access_token: str
) -> None:
    entry = await setup_entry(virtual_entry(2, 1))
    await wait_for(lambda: len(entry.runtime_data.transport.images) == 2)
    user = await hass_ws_client(hass, hass_read_only_access_token)
    assert (await call(user, type="stream_assistant/entries"))["error"]["code"] == "unauthorized"

    panels = (await call(user, type="stream_assistant/panel/list"))["result"]
    assert panels == [{"entry_id": entry.entry_id, "title": "Wall panel", "cols": 2, "rows": 1}]

    await user.send_json_auto_id({"type": "stream_assistant/panel/subscribe", "entry_id": entry.entry_id})
    assert (await user.receive_json())["success"]
    first = (await user.receive_json())["event"]
    assert (first["cols"], first["rows"], first["brightness"]) == (2, 1, 100)
    assert set(first["images"]) == {"0", "1"}

    pressed = await call(user, type="stream_assistant/panel/press", entry_id=entry.entry_id, key=0, pressed=True)
    assert pressed["success"]
    await call(user, type="stream_assistant/panel/press", entry_id=entry.entry_id, key=0, pressed=False)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "event", "virtual-test_key_0")).attributes["event_type"] == "short_press"

    missing = await call(user, type="stream_assistant/panel/subscribe", entry_id="nope")
    assert missing["error"]["code"] == "not_found"
    assert (await call(user, type="stream_assistant/panel/press", entry_id="nope", key=0, pressed=True))["error"]["code"] == "not_found"

    # Reloading the panel tells open cards to subscribe again
    await user.send_json_auto_id({"type": "stream_assistant/panel/subscribe", "entry_id": entry.entry_id})
    await user.receive_json()
    await user.receive_json()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    events = []
    while True:
        message = await user.receive_json()
        events.append(message.get("event", {}))
        if events[-1].get("stopped"):
            break
    assert events[-1] == {"stopped": True}


async def test_panel_and_card_are_registered(hass: HomeAssistant, setup_entry: SetupEntry) -> None:
    await setup_entry(virtual_entry())
    assert "stream-assistant" in hass.data[frontend.DATA_PANELS]
    assert any("card.js" in url for url in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls)
    assert await async_setup_component(hass, DOMAIN, {})
