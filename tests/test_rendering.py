"""Capabilities, key rendering and what a key shows for an entity state."""

from __future__ import annotations

import io

from PIL import Image
import pytest

from custom_components.stream_assistant.capabilities import (
    CATALOG,
    MAX_COLS,
    MAX_ROWS,
    find_capabilities,
    grid_capabilities,
)
from custom_components.stream_assistant.display import (
    BLANK,
    OFFLINE_BG,
    back_visual,
    default_icon,
    format_state,
    is_active,
    key_visual,
    page_key_slot,
    page_key_visual,
)
from custom_components.stream_assistant.layout import KEY_SCHEMA
from custom_components.stream_assistant.preview import RenderCache
from custom_components.stream_assistant.render import KeyVisual, icon_exists, render_key, render_preview
from homeassistant.core import HomeAssistant, State


def test_catalog_and_grids() -> None:
    assert find_capabilities("mk2") is CATALOG[0]
    assert find_capabilities("xl").key_count == 32
    grid = find_capabilities("grid_4x2")
    assert grid is not None and (grid.cols, grid.rows, grid.key_size, grid.rotation) == (4, 2, 144, 0)
    assert grid.name == "4 × 2"
    assert find_capabilities(f"grid_{MAX_COLS + 1}x1") is None
    assert find_capabilities("grid_0x1") is None
    assert find_capabilities("nope") is None
    assert find_capabilities(None) is None
    with pytest.raises(ValueError, match="outside"):
        grid_capabilities(1, MAX_ROWS + 1)


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_render_sizes_and_rotation() -> None:
    mk2 = find_capabilities("mk2")
    visual = KeyVisual("Büro", "An", "lightbulb", "#ffffff", font_size=14)
    deck = _image(render_key(mk2, visual))
    upright = _image(render_preview(mk2.key_size, visual))
    assert deck.size == upright.size == (72, 72)
    # The MK.2 shows images upside down: what it gets is the preview turned by 180°
    assert deck.convert("L").rotate(180).getbbox() is not None
    grid = _image(render_key(grid_capabilities(2, 2), KeyVisual(title="Sehr langer Titel für eine Taste")))
    assert grid.size == (144, 144)


def test_render_image_and_unknown_icon(tmp_path) -> None:
    picture = tmp_path / "p.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(picture)
    out = _image(render_preview(72, KeyVisual(image=str(picture), icon="does-not-exist")))
    assert out.getpixel((36, 36))[0] > 200
    assert icon_exists("lightbulb")
    assert not icon_exists("does-not-exist")


async def test_render_cache(hass: HomeAssistant) -> None:
    cache = RenderCache(hass)
    caps = grid_capabilities(2, 1)
    first = await cache.async_render(caps, KeyVisual("a"), upright=True)
    assert await cache.async_render(caps, KeyVisual("a"), upright=True) is first
    images = await cache.async_page_preview(caps, {"id": "main", "parent": None, "keys": {}})
    assert len(images) == 2


def _key(**values) -> dict:
    return KEY_SCHEMA(values)


async def test_key_visual_follows_entity(hass: HomeAssistant) -> None:
    hass.states.async_set("light.buero", "on", {"friendly_name": "Büro", "brightness": 128})
    visual = key_visual(hass, _key(entity_id="light.buero"))
    assert visual.title == "Büro"
    assert visual.subtitle == "On · 50 %"
    assert visual.icon == "lightbulb-on"
    assert visual.background == "#f2b134"

    hass.states.async_set("light.buero", "off", {"friendly_name": "Büro"})
    visual = key_visual(hass, _key(entity_id="light.buero", icon="mdi:star", icon_off="mdi:star-outline"))
    assert visual.icon == "star-outline"
    assert visual.background == "#2b2b2b"


async def test_key_visual_offline_text_and_blank(hass: HomeAssistant) -> None:
    assert key_visual(hass, None) is BLANK
    offline = key_visual(hass, _key(entity_id="light.missing"))
    assert offline.background == OFFLINE_BG
    assert offline.title == "light.missing"
    hass.states.async_set("scene.film", "unknown", {"friendly_name": "Film"})
    assert key_visual(hass, _key(entity_id="scene.film")).background != OFFLINE_BG

    text = key_visual(hass, _key(title="Hi", second_line="text", second_text="there", text_color="#000000"))
    assert (text.title, text.subtitle, text.foreground) == ("Hi", "there", "#000000")
    hass.states.async_set("sensor.t", "21.5", {"unit_of_measurement": "°C"})
    assert key_visual(hass, _key(entity_id="sensor.t", second_line="none")).subtitle == ""


async def test_format_state(hass: HomeAssistant) -> None:
    def fmt(entity_id: str, state: str, **attrs) -> str:
        return format_state(hass, State(entity_id, state, attrs))

    assert fmt("cover.rollo", "open", current_position=40) == "Open · 40 %"
    assert fmt("climate.wz", "heat", current_temperature=21) == "21°"
    assert fmt("media_player.tv", "playing", media_title="News") == "News"
    assert fmt("sensor.power", "12.0", unit_of_measurement="W") == "12 W"
    assert fmt("sensor.mode", "eco", unit_of_measurement="x") == "eco x"
    assert fmt("switch.a", "on") == "On"
    hass.config.language = "de"
    assert fmt("sensor.t", "21.5", unit_of_measurement="°C") == "21,5 °C"
    assert fmt("lock.door", "locked") == "Verriegelt"
    assert back_visual(hass).title == "Zurück"


def test_icons_and_activity() -> None:
    assert default_icon(State("binary_sensor.door", "on", {"device_class": "door"}), True) == "door-open"
    assert default_icon(State("binary_sensor.x", "off"), False) == "checkbox-blank-circle-outline"
    assert default_icon(State("light.a", "on", {"icon": "mdi:lamp"}), True) == "lamp"
    assert default_icon(State("climate.a", "heat"), True) == "thermostat"
    assert default_icon(State("weird.a", "x"), True) is None
    assert is_active(State("sensor.a", "3"))
    assert not is_active(State("switch.a", "off"))


async def test_page_key_slots(hass: HomeAssistant) -> None:
    folder = {"id": "f", "parent": "main", "keys": {"0": _key(title="hidden"), "1": _key(title="one")}}
    assert page_key_slot(folder, 0) == (None, True)
    assert page_key_slot(folder, 1)[0]["title"] == "one"
    assert page_key_visual(hass, folder, 0).icon == "arrow-left"
    assert page_key_visual(hass, folder, 1).title == "one"
