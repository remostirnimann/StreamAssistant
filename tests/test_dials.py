"""Dials and the touch strip: capabilities, layout, rendering, adjusting, and a Stream Deck + behind a bridge."""

from __future__ import annotations

import io
from typing import Any

from homeassistant.core import HomeAssistant, State
from PIL import Image
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service
import voluptuous as vol

from custom_components.stream_assistant.actions import AdjustCall, adjust_call
from custom_components.stream_assistant.bridge_hub import BridgeHub
from custom_components.stream_assistant.capabilities import find_capabilities, grid_capabilities, grid_id
from custom_components.stream_assistant.display import entity_level
from custom_components.stream_assistant.layout import (
    empty_layout,
    merge_into_template,
    remap_layout,
    validate_layout,
)
from custom_components.stream_assistant.protocol.bridge import BridgeDevice
from custom_components.stream_assistant.render import KeyVisual, render_segment

from .common import SetupEntry, bridge_entry, entity_id, wait_for
from .fake_bridge import BRIDGE_ID, FakeBridge, plus

UNIQUE = f"{BRIDGE_ID}-plus-1"


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _layout(keys: dict[str, Any] | None = None, dials: dict[str, Any] | None = None) -> dict[str, Any]:
    layout = empty_layout()
    layout["pages"][0]["keys"] = keys or {}
    layout["pages"][0]["dials"] = dials or {}
    return layout


def _valid(dials: dict[str, Any]) -> dict[str, Any]:
    """A validated layout with these dials, as the editor saves it."""
    return validate_layout(_layout(dials=dials), 8, 4)


# Capabilities, layout, rendering


def test_capabilities_with_dials() -> None:
    plus_caps = find_capabilities("plus")
    assert (plus_caps.dials, plus_caps.segment_width, plus_caps.has_touch) == (4, 200, True)
    assert [plus_caps.segment(x) for x in (0, 199, 200, 799, 5000, -3)] == [0, 0, 1, 3, 3, 0]
    grid = find_capabilities("grid_4x2_d3")
    assert grid == grid_capabilities(4, 2, 3)
    assert (grid.model_id, grid.name, grid.touch_width, grid.touch_height) == ("grid_4x2_d3", "4 × 2 + 3", 600, 100)
    assert grid_id(5, 3) == "grid_5x3" and find_capabilities("grid_5x3").dials == 0
    assert find_capabilities("grid_4x2_d9") is None
    no_strip = find_capabilities("mk2")
    assert no_strip.segment(10) is None and not no_strip.has_touch


def test_dial_layout_validation() -> None:
    dial = {"entity_id": "light.desk", "rotate": "adjust", "step": "2.5"}
    layout = validate_layout(_layout(dials={"1": dial}), 8, 4)
    stored = layout["pages"][0]["dials"]["1"]
    assert stored["step"] == 2.5 and stored["left"] == {"type": "none"} and stored["short"] == {"type": "none"}
    with pytest.raises(vol.Invalid, match="dial 5 does not exist"):
        validate_layout(_layout(dials={"4": dial}), 8, 4)
    with pytest.raises(vol.Invalid, match="links to an unknown page"):
        validate_layout(_layout(dials={"0": {"rotate": "actions", "left": {"type": "page", "page": "x"}}}), 8, 4)
    with pytest.raises(vol.Invalid):
        validate_layout(_layout(dials={"0": {"rotate": "spin"}}), 8, 4)
    # Any number of dials when the count is unknown
    assert "7" in validate_layout(_layout(dials={"7": {}}), None)["pages"][0]["dials"]


def test_dials_follow_templates() -> None:
    layout = _layout({"0": {"title": "k"}}, {"0": {"title": "a"}, "3": {"title": "d"}})
    fewer, dropped = remap_layout(layout, 4, 4, 2, 2)
    assert set(fewer["pages"][0]["dials"]) == {"0"} and dropped == 1
    same, dropped = remap_layout(layout, 4, 4, 2)
    assert set(same["pages"][0]["dials"]) == {"0", "3"} and dropped == 0

    # A deck with 2 dials edits a template with 4: dials 2 and 3 of the template stay
    template = _layout(dials={"0": {"title": "old"}, "2": {"title": "kept"}})
    deck = _layout(dials={"0": {"title": "new"}, "1": {"title": "b"}})
    merged = merge_into_template(deck, 4, 2, template, 4, 2, 2, 4)
    assert {k: v["title"] for k, v in merged["pages"][0]["dials"].items()} == {"0": "new", "1": "b", "2": "kept"}
    # A template without dials takes none from the deck
    assert merge_into_template(deck, 4, 2, _layout(), 5, 3, 2, 0)["pages"][0]["dials"] == {}


def test_segment_rendering() -> None:
    plain = _image(render_segment(200, 100, KeyVisual(title="Licht", subtitle="An", icon="lightbulb")))
    assert plain.size == (200, 100)
    level = KeyVisual(title="Licht", background="#000000", foreground="#ffffff", level=0.5)
    bar = _image(render_segment(200, 100, level))
    # The bar is filled on the left half only
    assert sum(bar.getpixel((30, 89))) > 600 and sum(bar.getpixel((170, 89))) < 600
    empty = _image(render_segment(200, 100, KeyVisual(level=0.0)))
    assert empty.size == (200, 100)


@pytest.mark.parametrize(
    ("domain", "value", "attributes", "expected"),
    [
        ("light", "on", {"brightness": 255}, 1.0),
        ("light", "off", {}, 0.0),
        ("media_player", "playing", {"volume_level": 0.25}, 0.25),
        ("cover", "open", {"current_position": 40}, 0.4),
        ("fan", "on", {"percentage": 50}, 0.5),
        ("fan", "off", {}, 0.0),
        ("climate", "heat", {"temperature": 20, "min_temp": 10, "max_temp": 30}, 0.5),
        ("input_number", "5", {"min": 0, "max": 10}, 0.5),
        ("number", "5", {"min": 10, "max": 10}, None),
        ("sensor", "80", {"unit_of_measurement": "%"}, 0.8),
        ("sensor", "80", {"unit_of_measurement": "W"}, None),
        ("media_player", "playing", {}, None),
        ("light", "unavailable", {}, None),
    ],
)
def test_entity_levels(domain: str, value: str, attributes: dict[str, Any], expected: float | None) -> None:
    assert entity_level(State(f"{domain}.x", value, attributes)) == expected


@pytest.mark.parametrize(
    ("domain", "value", "attributes", "steps", "step", "base", "expected"),
    [
        ("light", "off", {}, 2, None, None, AdjustCall("light", "turn_on", {"brightness_step_pct": 10})),
        ("light", "on", {}, -1, 20, None, AdjustCall("light", "turn_on", {"brightness_step_pct": -20})),
        (
            "media_player",
            "playing",
            {"volume_level": 0.5},
            3,
            None,
            None,
            AdjustCall("media_player", "volume_set", {"volume_level": 0.56}, 0.56),
        ),
        ("media_player", "playing", {}, -1, None, None, AdjustCall("media_player", "volume_down", {})),
        (
            "media_player",
            "playing",
            {"volume_level": 0.5},
            1,
            None,
            0.99,
            AdjustCall("media_player", "volume_set", {"volume_level": 1.0}, 1.0),
        ),
        (
            "cover",
            "open",
            {"current_position": 50},
            -2,
            None,
            None,
            AdjustCall("cover", "set_cover_position", {"position": 40}, 40),
        ),
        ("cover", "closed", {}, 1, None, None, AdjustCall("cover", "open_cover", {})),
        (
            "fan",
            "off",
            {"percentage_step": 25},
            1,
            None,
            None,
            AdjustCall("fan", "set_percentage", {"percentage": 25}, 25),
        ),
        (
            "climate",
            "heat",
            {"temperature": 21, "max_temp": 22},
            4,
            None,
            None,
            AdjustCall("climate", "set_temperature", {"temperature": 22}, 22),
        ),
        ("climate", "heat", {}, 1, None, None, None),
        (
            "input_number",
            "3",
            {"min": 0, "max": 10, "step": 2},
            -2,
            None,
            None,
            AdjustCall("input_number", "set_value", {"value": 0}, 0),
        ),
        ("number", "abc", {}, 1, None, None, None),
        ("select", "a", {}, 1, None, None, AdjustCall("select", "select_next", {"cycle": False})),
        ("input_select", "a", {}, -3, None, None, AdjustCall("input_select", "select_previous", {"cycle": False})),
        ("switch", "on", {}, 1, None, None, None),
        ("light", "unavailable", {}, 1, None, None, None),
        ("light", "on", {}, 0, None, None, None),
    ],
)
def test_adjust_calls(
    domain: str,
    value: str,
    attributes: dict[str, Any],
    steps: int,
    step: float | None,
    base: float | None,
    expected: AdjustCall | None,
) -> None:
    assert adjust_call(State(f"{domain}.x", value, attributes), steps, step, base) == expected


def test_bridge_device_with_dials_round_trip() -> None:
    device = BridgeDevice.from_json(plus())
    assert (device.dials, device.dial_press, device.touch_width, device.touch_height) == (4, True, 800, 100)
    assert BridgeDevice.from_json(device.to_json()) == device


# A Stream Deck + behind a bridge


async def _plus_device(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge):
    fake_bridge.devices = {"plus-1": plus()}
    entry = await setup_entry(bridge_entry(fake_bridge))
    hub: BridgeHub = entry.runtime_data
    await wait_for(lambda: "plus-1" in hub.devices and hub.devices["plus-1"].deck_connected)
    await hass.async_block_till_done()
    return hub.devices["plus-1"]


async def test_plus_paints_the_strip_and_has_entities(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    device = await _plus_device(hass, setup_entry, fake_bridge)
    assert device.model.model_id == "grid_4x2_d4" and device.model.key_size == 120
    await wait_for(lambda: len(fake_bridge.touch_images) == 4)
    assert ("plus-1", 600, 0, 200, 100) in fake_bridge.touch_images
    assert hass.states.get(entity_id(hass, "event", f"{UNIQUE}_dial_3")) is not None
    assert hass.states.get(entity_id(hass, "event", f"{UNIQUE}_touch")) is not None
    assert device.info()["deck"]["dial_count"] == 4

    # The dial's entity changes: only its segment is painted again
    hass.states.async_set("light.desk", "on", {"brightness": 128})
    await device.async_set_layout(_valid({"1": {"entity_id": "light.desk", "rotate": "adjust"}}))
    await wait_for(lambda: device._wanted.get(("dial", 1)) is not None and device._wanted[("dial", 1)].level)
    before = fake_bridge.touch_images[("plus-1", 200, 0, 200, 100)]
    hass.states.async_set("light.desk", "on", {"brightness": 255})
    await wait_for(lambda: fake_bridge.touch_images[("plus-1", 200, 0, 200, 100)] != before)


async def test_turning_adjusts_and_runs_actions(
    hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    device = await _plus_device(hass, setup_entry, fake_bridge)
    hass.states.async_set("light.desk", "on", {"brightness": 128})
    hass.states.async_set("media_player.radio", "playing", {"volume_level": 0.5})
    light = async_mock_service(hass, "light", "turn_on")
    volume = async_mock_service(hass, "media_player", "volume_set")
    scripts = async_mock_service(hass, "script", "turn_on")
    await device.async_set_layout(
        _valid(
            {
                "0": {"entity_id": "light.desk", "rotate": "adjust", "step": 10},
                "1": {"entity_id": "media_player.radio", "rotate": "adjust"},
                "2": {
                    "rotate": "actions",
                    "left": {"type": "action", "action": "script.turn_on", "data": {"entity_id": "script.down"}},
                    "right": {"type": "action", "action": "script.turn_on", "data": {"entity_id": "script.up"}},
                },
            }
        )
    )

    # Fast turning becomes one call
    await fake_bridge.turn("plus-1", 0, 2)
    await fake_bridge.turn("plus-1", 0, 1)
    await wait_for(lambda: len(light) == 1)
    assert light[0].data == {"entity_id": "light.desk", "brightness_step_pct": 30}
    dial0 = hass.states.get(entity_id(hass, "event", f"{UNIQUE}_dial_0"))
    assert dial0.attributes["event_type"] == "rotate_right" and dial0.attributes["steps"] == 1

    # Volume goes on from the value just set, before the player reports it
    await fake_bridge.turn("plus-1", 1, 5)
    await wait_for(lambda: len(volume) == 1)
    await fake_bridge.turn("plus-1", 1, 5)
    await wait_for(lambda: len(volume) == 2)
    assert [c.data["volume_level"] for c in volume] == [0.6, 0.7]

    # One action per detent, at most five
    await fake_bridge.turn("plus-1", 2, -7)
    await wait_for(lambda: len(scripts) == 5)
    assert {c.data["entity_id"] for c in scripts} == {"script.down"}

    # Nothing configured, or an entity that cannot be adjusted: nothing happens
    hass.states.async_set("switch.fan", "on")
    await device.async_set_layout(_valid({"0": {"entity_id": "switch.fan", "rotate": "adjust"}}))
    await fake_bridge.turn("plus-1", 0, 1)
    await fake_bridge.turn("plus-1", 3, 1)
    await hass.async_block_till_done()
    assert len(light) == 1


async def test_pushing_and_touching(hass: HomeAssistant, setup_entry: SetupEntry, fake_bridge: FakeBridge) -> None:
    device = await _plus_device(hass, setup_entry, fake_bridge)
    calls = async_mock_service(hass, "script", "turn_on")

    def run(name: str) -> dict[str, Any]:
        return {"type": "action", "action": "script.turn_on", "data": {"entity_id": f"script.{name}"}}

    await device.async_set_layout(_valid({"1": {"short": run("short"), "long": run("long")}}))
    ran = lambda: [c.data["entity_id"] for c in calls]  # noqa: E731

    await fake_bridge.push_dial("plus-1", 1, True)
    await fake_bridge.push_dial("plus-1", 1, False)
    await wait_for(lambda: ran() == ["script.short"])
    dial1 = entity_id(hass, "event", f"{UNIQUE}_dial_1")
    assert hass.states.get(dial1).attributes["event_type"] == "short_press"

    # Tap and hold on the dial's part of the strip
    await fake_bridge.touch("plus-1", "tap", 250)
    await fake_bridge.touch("plus-1", "long", 399)
    await wait_for(lambda: ran() == ["script.short", "script.short", "script.long"])
    touch = entity_id(hass, "event", f"{UNIQUE}_touch")
    assert hass.states.get(touch).attributes["event_type"] == "long_press"
    assert hass.states.get(touch).attributes["dial"] == 1

    # Swipes are events only; a tap on an empty segment does nothing
    await fake_bridge.touch("plus-1", "swipe", 700, x2=100, y2=50)
    await wait_for(lambda: hass.states.get(touch).attributes["event_type"] == "swipe_left")
    assert hass.states.get(touch).attributes["x2"] == 100
    await fake_bridge.touch("plus-1", "swipe", 100, x2=700, y2=50)
    await wait_for(lambda: hass.states.get(touch).attributes["event_type"] == "swipe_right")
    await fake_bridge.touch("plus-1", "tap", 10)
    await hass.async_block_till_done()
    assert len(calls) == 3

    # A dimmed deck wakes up first: that turn, push or touch does nothing else
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(device.behavior, "async_activity", lambda: True)
        await fake_bridge.turn("plus-1", 1, 1)
        await fake_bridge.touch("plus-1", "tap", 250)
        await fake_bridge.push_dial("plus-1", 1, True)
        # Messages arrive in order: once the push is swallowed, the rest was handled
        await wait_for(lambda: ("dial", 1) in device._swallowed)
    await fake_bridge.push_dial("plus-1", 1, False)  # the release of the swallowed push
    await wait_for(lambda: ("dial", 1) not in device._swallowed)
    await hass.async_block_till_done()
    assert len(calls) == 3


async def test_editor_with_dials(
    hass: HomeAssistant, hass_ws_client, setup_entry: SetupEntry, fake_bridge: FakeBridge
) -> None:
    device = await _plus_device(hass, setup_entry, fake_bridge)
    client = await hass_ws_client(hass)

    async def call(**message: Any) -> dict[str, Any]:
        await client.send_json_auto_id(message)
        return await client.receive_json()

    calls = async_mock_service(hass, "script", "turn_on")
    hass.states.async_set("cover.blind", "open", {"current_position": 50})
    positions = async_mock_service(hass, "cover", "set_cover_position")
    action = {"type": "action", "action": "script.turn_on", "data": {"entity_id": "script.x"}}
    page = {
        "id": "main",
        "name": "Start",
        "dials": {
            "0": {"title": "Push", "short": action, "rotate": "actions", "right": action},
            "1": {"entity_id": "cover.blind", "rotate": "adjust"},
        },
    }

    entries = (await call(type="stream_assistant/entries"))["result"]["entries"]
    model = next(e for e in entries if e["entry_id"] == device.key)["model"]
    assert (model["dials"], model["touch_width"], model["touch_height"]) == (4, 800, 100)

    preview = (await call(type="stream_assistant/preview", entry_id=device.key, page=page))["result"]
    assert len(preview["images"]) == 8 and len(preview["dials"]) == 4

    assert (await call(type="stream_assistant/press", entry_id=device.key, dial=0, page=page))["success"]
    assert (await call(type="stream_assistant/press", entry_id=device.key, dial=0, rotate="right", page=page))[
        "success"
    ]
    assert (await call(type="stream_assistant/press", entry_id=device.key, dial=0, long=True, page=page))["success"]
    assert (await call(type="stream_assistant/press", entry_id=device.key, dial=1, rotate="left", page=page))["success"]
    await wait_for(lambda: len(calls) == 2 and len(positions) == 1)
    assert positions[0].data["position"] == 45
    missing = await call(type="stream_assistant/press", entry_id=device.key, dial=4)
    assert missing["error"]["code"] == "invalid_format"
    neither = await call(type="stream_assistant/press", entry_id=device.key)
    assert not neither["success"]

    saved = await call(
        type="stream_assistant/layout/save", entry_id=device.key, layout={"pages": [{**page, "dials": page["dials"]}]}
    )
    assert saved["success"] and saved["result"]["layout"]["pages"][0]["dials"]["0"]["title"] == "Push"
    too_many = await call(
        type="stream_assistant/layout/save", entry_id=device.key, layout={"pages": [{**page, "dials": {"5": {}}}]}
    )
    assert too_many["error"]["code"] == "invalid_format"

    # A template for the deck keeps its dials; testing on it runs only actions
    created = (await call(type="stream_assistant/template/create", name="Plus", from_entry_id=device.key))["result"]
    template_id = created["template_id"]
    assert created["model"]["dials"] == 4
    for message in (
        {"dial": 0},
        {"dial": 0, "rotate": "right"},
        {"dial": 1, "rotate": "right"},
    ):
        assert (await call(type="stream_assistant/press", template_id=template_id, page=page, **message))["success"]
    await wait_for(lambda: len(calls) == 4)
    assert len(positions) == 1

    # Linked: the deck shows the template with its dials
    assert (await call(type="stream_assistant/link", entry_id=device.key, template_id=template_id))["success"]
    await wait_for(lambda: device.layout["pages"][0]["dials"].get("0", {}).get("title") == "Push")
