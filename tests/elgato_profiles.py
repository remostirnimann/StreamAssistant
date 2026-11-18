"""Small Stream Deck app profiles, built in the tests (no exported files are checked in).

They follow the archive layouts of the Stream Deck app: V1 (before 6.0),
V2 (6.x) and V3 (7.1+, with package.json and a Profiles/ prefix).
"""

from __future__ import annotations

import io
import json
from typing import Any
import zipfile

from PIL import Image

HA_ENTITY = "de.perdoctus.streamdeck.homeassistant.entity"


def png(color: str = "red") -> bytes:
    """A tiny PNG image."""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "PNG")
    return buffer.getvalue()


def action(uuid: str, title: str = "", settings: dict | None = None, image: str | None = None, **extra: Any) -> dict:
    """An action as the app stores it on a key or dial."""
    state: dict[str, Any] = {"Title": title}
    if image:
        state["Image"] = image
    return {
        "ActionID": "00000000-0000-0000-0000-000000000000",
        "LinkedTitle": True,
        "Name": uuid.rsplit(".", 1)[-1],
        "Plugin": {"Name": "x", "UUID": uuid.rsplit(".", 1)[0], "Version": "1.0"},
        "Settings": settings or {},
        "State": 0,
        "States": [state],
        "UUID": uuid,
        **extra,
    }


def call(service: str = "", entity: str = "", data: str = "") -> dict[str, str]:
    return {"serviceId": service, "entityId": entity, "serviceData": data}


def ha(
    entity: str,
    short: dict | None = None,
    long: dict | None = None,
    rotation: dict | None = None,
    tap: dict | None = None,
    title: str = "",
    custom_title: str = "",
    image: str | None = None,
) -> dict:
    """A key of the Home Assistant plugin with settings of its current version (8)."""
    settings = {
        "version": 8,
        "display": {
            "entityId": entity,
            "useCustomTitle": bool(custom_title),
            "buttonTitle": custom_title or "{{friendly_name}}",
        },
        "button": {
            "serviceShortPress": short or call(),
            "serviceLongPress": long or call(),
            "serviceRotation": rotation or call(),
            "serviceTap": tap or call(),
        },
        "controllerType": "Keypad",
    }
    result = action(HA_ENTITY, title, settings, image)
    result["Plugin"] = {"Name": "Home Assistant", "UUID": "de.perdoctus.streamdeck.homeassistant", "Version": "3"}
    return result


def folder_key(child: str, title: str = "") -> dict:
    return action("com.elgato.streamdeck.profile.openchild", title, {"ProfileUUID": child})


def back_key() -> dict:
    return action("com.elgato.streamdeck.profile.backtoparent")


def multi(*steps: dict, title: str = "") -> dict:
    return action("com.elgato.streamdeck.multiactions.routine", title, {}, Actions=[{"Actions": list(steps)}])


def delay() -> dict:
    return action("com.elgato.streamdeck.multiactions.delay", settings={"duration": 500})


def hotkey(title: str = "Copy", image: str | None = None) -> dict:
    return action("com.elgato.streamdeck.system.hotkey", title, {"Hotkeys": []}, image)


def page(keys: dict[str, dict] | None = None, dials: dict[str, dict] | None = None, name: str = "") -> dict:
    """A V2/V3 page manifest."""
    controllers = [{"Type": "Keypad", "Actions": keys or {}}]
    if dials is not None:
        controllers.append({"Type": "Encoder", "Actions": dials})
    return {"Controllers": controllers, "Icon": "", "Name": name}


def profile_v2(
    name: str,
    pages: dict[str, dict],
    order: list[str],
    files: dict[str, bytes] | None = None,
    model: str = "20GBA9901",
    profile_id: str = "AAAA1111-2222-3333-4444-555566667777",
    prefix: str = "",
    size: tuple[int, int] | None = None,
) -> dict[str, bytes]:
    """Archive entries of a V2 profile (prefix "Profiles/" for V3). files: paths below a page folder."""
    root = f"{prefix}{profile_id}.sdProfile"
    device: dict[str, Any] = {"Model": model, "UUID": ""}
    if size:
        device["Size"] = {"Columns": size[0], "Rows": size[1]}
    entries = {
        f"{root}/manifest.json": json.dumps(
            {
                "Name": name,
                "Device": device,
                "Pages": {"Current": order[0], "Default": order[0], "Pages": order},
                "Version": "2.0",
            }
        ).encode()
    }
    for page_id, manifest in pages.items():
        entries[f"{root}/Profiles/{page_id.upper()}/manifest.json"] = json.dumps(manifest).encode()
    for path, data in (files or {}).items():
        page_id, rest = path.split("/", 1)
        entries[f"{root}/Profiles/{page_id.upper()}/{rest}"] = data
    return entries


def zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
    return buffer.getvalue()


# Page ids as the app writes them (UUIDs); the parser matches them case-insensitively
P1 = "11111111-aaaa-bbbb-cccc-000000000001"
P2 = "11111111-aaaa-bbbb-cccc-000000000002"
P3 = "11111111-aaaa-bbbb-cccc-000000000003"
F1 = "22222222-aaaa-bbbb-cccc-000000000001"
F2 = "22222222-aaaa-bbbb-cccc-000000000002"


def mk2_profile() -> bytes:
    """An MK.2 profile with three pages, a folder in a folder and a mix of actions."""
    pages = {
        P1: page(
            {
                "0,0": ha(
                    "light.kitchen",
                    short=call("light.toggle", "light.kitchen"),
                    title="Kitchen",
                    image="Images/LIGHT.png",
                ),
                "1,0": hotkey(image="Images/HOTKEY.png"),
                "2,0": folder_key(F1, "Cellar"),
                "3,0": multi(delay(), ha("scene.movie", short=call("scene.turn_on", "scene.movie")), title="Movie"),
                "4,0": multi(hotkey(), ha("light.a", short=call("light.toggle", "light.a"))),
                "0,1": action("com.elgato.streamdeck.profile.rotate", "Other"),
                "1,1": ha("light.desk", short=call("light.turn_on", "light.desk", '{"brightness": {{ticks}} }')),
                "2,1": ha("switch.fan", short=call("switch.toggle"), long=call("switch.turn_off", "", '{"x": 1}')),
                "4,2": action("com.elgato.streamdeck.profiles.nextpage"),
            }
        ),
        P2: page(
            {
                "0,0": ha("switch.pump", short=call("switch.toggle", "switch.pump"), title="Pump"),
                "1,0": action("com.elgato.streamdeck.profiles.previouspage", "Back"),
            },
            name="Garden",
        ),
        P3: page({"0,0": hotkey()}),
        F1: page(
            {
                "0,0": back_key(),
                "1,0": ha("cover.door", short=call("cover.toggle", "cover.door"), long=call("cover.stop_cover")),
                "2,0": folder_key(F2),
                "3,0": action("com.elgato.streamdeck.profiles.nextpage"),
            }
        ),
        F2: page({"0,0": back_key(), "1,0": ha("lock.front", short=call("lock.lock", "lock.front"))}, name="Locks"),
    }
    files = {f"{P1}/Images/LIGHT.png": png(), f"{P1}/Images/HOTKEY.png": png("blue")}
    return zip_bytes(profile_v2("Living room", pages, [P1, P2, P3], files))


def plus_profile() -> bytes:
    """A Stream Deck + profile in the V3 layout, with dials."""
    pages = {
        P1: page(
            {"0,0": ha("light.kitchen", short=call("light.toggle", "light.kitchen"))},
            {
                "0,0": ha(
                    "light.kitchen",
                    short=call("light.toggle", "light.kitchen"),
                    rotation=call("light.turn_on", "light.kitchen", '{"brightness_step_pct": {{ ticks }} }'),
                    tap=call("light.turn_off", "light.kitchen"),
                ),
                "1,0": ha(
                    "sensor.power",
                    tap=call("homeassistant.update_entity", "sensor.power"),
                    rotation=call("script.turn_on", "script.x"),
                ),
                "2,0": hotkey(),
            },
        )
    }
    entries = profile_v2("Desk", pages, [P1], model="20GBD9901", prefix="Profiles/")
    entries["package.json"] = json.dumps({"AppVersion": "7.1.0", "DeviceModel": "20GBD9901", "Name": "Desk"}).encode()
    return zip_bytes(entries)


def v1_profile() -> bytes:
    """A profile of the app before 6.0: keys directly in the manifest, settings of plugin version 1."""
    root = "33333333-0000-0000-0000-000000000001.sdProfile"
    child = "33333333-0000-0000-0000-000000000002"
    settings = {
        "domain": "light",
        "entityId": "light.hall",
        "service": {"id": "toggle", "data": ""},
        "serviceLongPress": {"id": "turn_off", "data": '{"transition": 2}'},
        "useCustomTitle": True,
        "buttonTitle": "Hall",
    }
    hall = action(HA_ENTITY, "", settings)
    hall["Plugin"] = None
    manifest = {
        "Actions": {"0,0": hall, "1,0": folder_key(child.upper(), "More")},
        "DeviceModel": "20GAI9901",
        "Name": "Old",
        "Version": "1.0",
    }
    v2_settings = {
        "version": 2,
        "display": {"entityId": "fan.attic"},
        "button": {
            "service": {"domain": "fan", "name": "toggle", "data": ""},
            "serviceLongPress": {"domain": "", "name": "", "data": ""},
        },
    }
    child_manifest = {"Actions": {"0,0": back_key(), "1,0": action(HA_ENTITY, "Attic", v2_settings)}}
    return zip_bytes(
        {
            f"{root}/manifest.json": json.dumps(manifest).encode(),
            f"{root}/0,0/CustomImages/state0.png": png(),
            f"{root}/Profiles/{child}.sdProfile/manifest.json": json.dumps(child_manifest).encode(),
        }
    )
