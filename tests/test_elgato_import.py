"""Import of Elgato Stream Deck app profiles: parser, conversion, upload and template creation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import FormData
from homeassistant.core import HomeAssistant
import pytest

from custom_components.stream_assistant import elgato_import, profile_import
from custom_components.stream_assistant.capabilities import find_capabilities
from custom_components.stream_assistant.elgato_import import ProfileError, convert_profile, parse_archive
from custom_components.stream_assistant.layout import validate_layout

from . import elgato_profiles as ep
from .common import SetupEntry, virtual_entry


def _convert(data: bytes, model: str, index: int = 0, language: str = "en"):
    profile = parse_archive(data)[index]
    caps = find_capabilities(model)
    result = convert_profile(profile, caps, "/config/www/x", language)
    # Whatever the converter makes must be a valid layout for the deck
    validate_layout(result.layout, caps.key_count, caps.dials)
    return result


def _pages(result) -> dict[str, dict[str, Any]]:
    return {page["id"]: page for page in result.layout["pages"]}


def _reasons(result) -> list[tuple[str, str, int, int]]:
    return sorted((r["reason"], r["page"], r["col"], r["row"]) for r in result.report)


def test_mk2_profile_pages_folders_and_keys() -> None:
    profile = parse_archive(ep.mk2_profile())[0]
    assert profile.summary() == {
        "id": "aaaa1111-2222-3333-4444-555566667777",
        "name": "Living room",
        "model_number": "20GBA9901",
        "suggested_model": "mk2",
        "pages": 3,
        "folders": 2,
        "controls": 18,
        "ha_controls": 7,
    }
    result = _convert(ep.mk2_profile(), "mk2")
    pages = _pages(result)
    assert [(p["id"], p["name"], p["parent"]) for p in result.layout["pages"]] == [
        ("main", "Home", None),
        ("page2", "Garden", "main"),
        ("page3", "Page 3", "main"),
        ("folder1", "Cellar", "main"),
        ("folder2", "Locks", "folder1"),
    ]
    main = pages["main"]["keys"]
    assert main["0"] == {
        "title": "Kitchen",
        "entity_id": "light.kitchen",
        "short": {"type": "action", "action": "light.toggle", "data": {}, "target": {"entity_id": "light.kitchen"}},
        "long": {"type": "none"},
        "image": "/config/www/x/001.png",
    }
    # Images only of converted keys: the hotkey's image is not taken
    assert list(result.images) == ["001.png"] and result.images["001.png"].startswith(b"\x89PNG")
    assert "1" not in main
    assert main["2"]["short"] == {"type": "page", "page": "folder1"} and main["2"]["title"] == "Cellar"
    # A multi action with one Home Assistant step (and delays) is taken over
    assert main["3"]["short"]["action"] == "scene.turn_on" and main["3"]["title"] == "Movie"
    assert "4" not in main and "5" not in main
    # A templated service call keeps the entity, but not the action
    assert main["6"]["short"] == {"type": "none"} and main["6"]["entity_id"] == "light.desk"
    # The plugin's entity is the target when the call names none; a call's own data is kept
    assert main["7"]["short"]["target"] == {"entity_id": "switch.fan"}
    assert main["7"]["long"] == {
        "type": "action",
        "action": "switch.turn_off",
        "data": {"x": 1},
        "target": {"entity_id": "switch.fan"},
    }
    assert main["14"]["short"] == {"type": "page", "page": "page2"} and main["14"]["second_line"] == "none"
    # Page 2 is a folder of the root page now: its first key moved to a free position
    garden = pages["page2"]["keys"]
    assert garden["2"]["entity_id"] == "switch.pump"
    assert garden["1"]["short"] == {"type": "page", "page": "main"}
    # Nothing led to page 3: a link was added on the page before it
    assert garden["14"] == {
        "title": "Page 3",
        "icon": "mdi:arrow-right",
        "second_line": "none",
        "short": {"type": "page", "page": "page3"},
    }
    cellar = pages["folder1"]["keys"]
    assert "0" not in cellar
    assert cellar["1"]["long"] == {
        "type": "action",
        "action": "cover.stop_cover",
        "data": {},
        "target": {"entity_id": "cover.door"},
    }
    assert cellar["2"]["short"] == {"type": "page", "page": "folder2"} and cellar["2"]["title"] == "Locks"
    assert _reasons(result) == [
        ("link_added", "Garden", 4, 2),
        ("moved", "Garden", 0, 0),
        ("multi_action", "Home", 4, 0),
        ("multi_action_step", "Home", 3, 0),
        ("profile_switch", "Home", 0, 1),
        ("service_template", "Home", 1, 1),
        ("unsupported", "Cellar", 3, 0),
        ("unsupported", "Home", 1, 0),
        ("unsupported", "Page 3", 0, 0),
    ]
    skipped = {r["reason"] for r in result.report if r["skipped"]}
    assert skipped == {"multi_action", "profile_switch", "unsupported"}


def test_smaller_and_larger_decks() -> None:
    small = _convert(ep.mk2_profile(), "grid_3x2", language="de")
    pages = _pages(small)
    assert pages["main"]["name"] == "Startseite" and pages["page3"]["name"] == "Seite 3"
    assert {"0", "2"} <= set(pages["main"]["keys"])
    outside = [(r["page"], r["col"], r["row"]) for r in small.report if r["reason"] == "outside"]
    assert ("Startseite", 3, 0) in outside and ("Startseite", 4, 2) in outside
    # The key to page 2 did not fit: a link on the root page instead
    links = {r["detail"] for r in small.report if r["reason"] == "link_added"}
    assert links == {"Garden", "Seite 3"}
    assert pages["main"]["keys"]["3"]["short"] == {"type": "page", "page": "page2"}

    xl = _convert(ep.mk2_profile(), "xl")
    main = _pages(xl)["main"]["keys"]
    # Same column and row on the wider grid
    assert main["9"]["entity_id"] == "light.desk" and main["20"]["short"]["page"] == "page2"


def test_no_room_for_links_or_moved_keys() -> None:
    full = {f"{c},{r}": ep.ha("light.a", short=ep.call("light.toggle", "light.a")) for c in range(3) for r in range(2)}
    data = ep.zip_bytes(
        ep.profile_v2("Full", {ep.P1: ep.page(full), ep.P2: ep.page(full)}, [ep.P1, ep.P2], model="20GAI9901")
    )
    result = _convert(data, "grid_3x2")
    reasons = [r["reason"] for r in result.report]
    # Page 2's first key has no place to go, and no page has room for a link to page 2
    assert reasons.count("no_space") == 2
    assert len(_pages(result)["page2"]["keys"]) == 5


def test_plus_profile_with_dials() -> None:
    profile = parse_archive(ep.plus_profile())[0]
    assert profile.name == "Desk" and profile.suggested_model().model_id == "plus"
    result = _convert(ep.plus_profile(), "plus")
    dials = _pages(result)["main"]["dials"]
    assert dials["0"]["rotate"] == "adjust" and dials["0"]["entity_id"] == "light.kitchen"
    assert dials["0"]["short"]["action"] == "light.toggle"
    # Only a tap: it becomes the dial's press
    assert dials["1"]["short"]["action"] == "homeassistant.update_entity" and "rotate" not in dials["1"]
    assert "2" not in dials
    assert _reasons(result) == [
        ("rotation_adjust", "Home", 0, 0),
        ("rotation_dropped", "Home", 1, 0),
        ("tap_dropped", "Home", 0, 0),
        ("unsupported", "Home", 2, 0),
    ]
    # Without dials, they are reported
    no_dials = _convert(ep.plus_profile(), "mk2")
    assert [r["reason"] for r in no_dials.report].count("outside") == 2


def test_v1_profile() -> None:
    profile = parse_archive(ep.v1_profile())[0]
    assert (profile.name, profile.suggested_model().model_id, len(profile.folders)) == ("Old", "grid_3x2", 1)
    result = _convert(ep.v1_profile(), "grid_3x2")
    pages = _pages(result)
    hall = pages["main"]["keys"]["0"]
    assert hall["title"] == "Hall" and hall["image"] == "/config/www/x/001.png"
    assert hall["short"]["action"] == "light.toggle"
    assert hall["long"]["data"] == {"transition": 2}
    attic = pages["folder1"]["keys"]["1"]
    assert pages["folder1"]["name"] == "More" and attic["title"] == "Attic"
    assert attic["short"] == {
        "type": "action",
        "action": "fan.toggle",
        "data": {},
        "target": {"entity_id": "fan.attic"},
    }


def test_backup_with_several_profiles_and_odd_content() -> None:
    entries = ep.profile_v2("One", {ep.P1: ep.page({"0,0": ep.hotkey()})}, [ep.P1], model="X", size=(4, 2))
    entries |= ep.profile_v2(
        "Two",
        {ep.P2: ep.page({"7,3": ep.hotkey(), "x": ep.hotkey(), "1,0": "junk"})},
        [ep.P2, "missing"],
        model="",
        profile_id="BBBB",
    )
    entries["broken/manifest.json"] = b"{not json"
    entries["list/manifest.json"] = b"[]"
    entries["package.json"] = b'{"Name": "Backup"}'
    profiles = parse_archive(ep.zip_bytes(entries))
    assert [(p.name, p.suggested_model().model_id) for p in profiles] == [("One", "grid_4x2"), ("Two", "xl")]


@pytest.mark.parametrize(
    ("settings", "reason"),
    [
        (None, "ha_unreadable"),
        ({"version": 8, "display": {"entityId": "Not An Entity"}, "button": {}}, "invalid_entity"),
    ],
)
def test_unreadable_plugin_settings(settings: Any, reason: str) -> None:
    key = ep.ha("light.a")
    key["Settings"] = settings
    data = ep.zip_bytes(ep.profile_v2("X", {ep.P1: ep.page({"0,0": key})}, [ep.P1]))
    assert reason in [r["reason"] for r in _convert(data, "mk2").report]


def test_bad_calls_and_titles() -> None:
    keys = {
        "0,0": ep.ha("light.a", short=ep.call("streamdeck.open_url", "", '{"url": "x"}')),
        "1,0": ep.ha("light.a", short=ep.call("light.toggle", "", "[1]"), long=ep.call("light.on", "", "{bad")),
        "2,0": ep.ha("light.a", short=ep.call("light.toggle", "Bad Entity"), custom_title="{{ state }} W"),
        "3,0": ep.ha("light.a", custom_title="Lamp\nleft"),
        "4,0": ep.ha("", short=ep.call("script.turn_on", "", '{"entity_id": "script.a"}')),
        "0,1": ep.action("com.elgato.streamdeck.profiles.page", settings={"page": 9}),
        "1,1": ep.action("com.elgato.streamdeck.profiles.page", settings={"page": "x"}),
        "2,1": ep.folder_key("unknown"),
    }
    keys["3,0"]["States"][0]["ShowTitle"] = False
    data = ep.zip_bytes(ep.profile_v2("X", {ep.P1: ep.page(keys)}, [ep.P1]))
    result = _convert(data, "mk2")
    main = _pages(result)["main"]["keys"]
    assert main["0"]["short"] == {"type": "none"}
    assert main["2"]["short"]["target"] == {} and main["2"]["title"] == ""
    assert main["3"]["title"] == "Lamp left"
    assert main["4"]["short"]["target"] == {} and "entity_id" not in main["4"]
    assert _reasons(result) == [
        ("invalid_entity", "Home", 2, 0),
        ("service_invalid", "Home", 0, 0),
        ("service_invalid", "Home", 1, 0),
        ("service_invalid", "Home", 1, 0),
        ("title_template", "Home", 2, 0),
        ("unsupported", "Home", 0, 1),
        ("unsupported", "Home", 1, 1),
        ("unsupported", "Home", 2, 1),
    ]


def test_images_that_cannot_be_used(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = {
        "0,0": ep.ha("light.a", image="Images/A.svg"),
        "1,0": ep.ha("light.b", image="Images/B.png"),
        "2,0": ep.ha("light.c", image="Images/C.png"),
    }
    files = {f"{ep.P1}/Images/A.svg": b"<svg/>", f"{ep.P1}/Images/B.png": ep.png(), f"{ep.P1}/Images/C.png": ep.png()}
    data = ep.zip_bytes(ep.profile_v2("X", {ep.P1: ep.page(keys)}, [ep.P1], files))
    monkeypatch.setattr(elgato_import, "MAX_TOTAL_IMAGE_BYTES", len(ep.png()) + 1)
    result = _convert(data, "mk2")
    assert list(result.images) == ["001.png"]
    assert [(r["reason"], r["col"]) for r in result.report] == [("image_skipped", 0), ("image_skipped", 2)]


def test_archive_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProfileError, match="not_zip"):
        parse_archive(b"no zip")
    with pytest.raises(ProfileError, match="no_profile"):
        parse_archive(ep.zip_bytes({"readme.txt": b"x"}))
    monkeypatch.setattr(elgato_import, "MAX_ENTRIES", 1)
    with pytest.raises(ProfileError, match="too_large"):
        parse_archive(ep.mk2_profile())
    monkeypatch.setattr(elgato_import, "MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(ProfileError, match="too_large"):
        parse_archive(ep.mk2_profile())


# Upload and template creation in Home Assistant


async def _upload(client, data: bytes, field: str = "file"):
    form = FormData()
    form.add_field(field, data, filename="x.streamDeckProfile")
    return await client.post(profile_import.UPLOAD_URL, data=form)


async def test_upload_and_create_templates(
    hass: HomeAssistant, hass_client, hass_ws_client, setup_entry: SetupEntry, tmp_path: Path
) -> None:
    await setup_entry(virtual_entry(4, 2))
    hass.states.async_set("light.kitchen", "on")
    # Images go below www, which Home Assistant allows by default (core_config)
    hass.config.config_dir = str(tmp_path)
    hass.config.allowlist_external_dirs = {hass.config.path("www")}
    client = await hass_client()
    response = await _upload(client, ep.mk2_profile())
    assert response.status == 200
    upload = await response.json()
    assert [p["name"] for p in upload["profiles"]] == ["Living room"]

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {
            "type": "stream_assistant/import/create",
            "token": upload["token"],
            "profiles": [{"id": upload["profiles"][0]["id"], "name": "Living room", "model": "mk2"}],
        }
    )
    result = (await ws.receive_json())["result"]["templates"][0]
    assert (result["model"], result["pages"], result["images"]) == ("mk2", 5, 1)
    unknown = [r for r in result["report"] if r["reason"] == "unknown_entity"]
    assert {r["detail"] for r in unknown} >= {"light.desk", "cover.door", "scene.movie"}
    assert not any("light.kitchen" in r["detail"] for r in unknown)
    image = Path(result["image_folder"]) / "001.png"
    assert image.is_file() and hass.config.is_allowed_path(str(image))

    await ws.send_json_auto_id({"type": "stream_assistant/layout/get", "template_id": result["template_id"]})
    layout = (await ws.receive_json())["result"]["layout"]
    assert layout["pages"][0]["keys"]["0"]["image"] == str(image)

    # A different model, from the same upload
    await ws.send_json_auto_id(
        {
            "type": "stream_assistant/import/create",
            "token": upload["token"],
            "profiles": [{"id": upload["profiles"][0]["id"], "name": "Small", "model": "nope"}],
        }
    )
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"
    await ws.send_json_auto_id(
        {
            "type": "stream_assistant/import/create",
            "token": "gone",
            "profiles": [{"id": "a", "name": "b", "model": "mk2"}],
        }
    )
    assert (await ws.receive_json())["error"]["code"] == "not_found"


async def test_upload_errors_and_expiry(
    hass: HomeAssistant, hass_client, hass_read_only_access_token: str, setup_entry: SetupEntry, monkeypatch
) -> None:
    await setup_entry(virtual_entry(4, 2))
    client = await hass_client()
    assert (await (await _upload(client, b"nope")).json()) == {"error": "not_zip"}
    assert (await (await _upload(client, ep.mk2_profile(), field="other")).json()) == {"error": "no_file"}
    assert (await client.post(profile_import.UPLOAD_URL, data=b"raw")).status == 400
    monkeypatch.setattr(profile_import, "MAX_ARCHIVE_BYTES", 100)
    assert (await (await _upload(client, ep.mk2_profile())).json()) == {"error": "too_large"}
    monkeypatch.undo()

    user = await hass_client(hass_read_only_access_token)
    assert (await _upload(user, ep.mk2_profile())).status == 401

    # Old uploads are dropped: by count and by age
    tokens = [(await (await _upload(client, ep.v1_profile())).json())["token"] for _ in range(4)]
    imports = hass.data[profile_import.DATA_IMPORTS]
    assert list(imports) == tokens[1:]
    imports[tokens[1]].expires = 0
    await _upload(client, ep.v1_profile())
    assert tokens[1] not in imports


async def test_invalid_layout_is_refused(
    hass: HomeAssistant, hass_client, hass_ws_client, setup_entry: SetupEntry, monkeypatch
) -> None:
    await setup_entry(virtual_entry(4, 2))
    upload = await (await _upload(await hass_client(), ep.v1_profile())).json()

    def broken(*args, **kwargs):
        return elgato_import.ImportResult(layout={"pages": []}, images={}, report=[])

    monkeypatch.setattr(profile_import, "convert_profile", broken)
    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id(
        {
            "type": "stream_assistant/import/create",
            "token": upload["token"],
            "profiles": [{"id": upload["profiles"][0]["id"], "name": "x", "model": "mk2"}],
        }
    )
    assert (await ws.receive_json())["error"]["code"] == "unknown_error"
