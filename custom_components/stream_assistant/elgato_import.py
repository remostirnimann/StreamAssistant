"""Import profiles of the Elgato Stream Deck app into Stream Assistant layouts.

An exported profile (`.streamDeckProfile`) or a backup of all profiles
(`.streamDeckProfilesBackup`) is a ZIP archive with one `manifest.json` per
profile and per page or folder. Three generations exist:

- V1 (Stream Deck app before 6.0): `<id>.sdProfile/manifest.json` holds the
  keys directly under "Actions"; folders are nested `<id>.sdProfile` folders.
- V2 (app 6.x): `<id>.sdProfile/manifest.json` lists the pages
  ({"Pages": {"Pages": [...], "Default": ...}}), every page and folder is
  `<id>.sdProfile/Profiles/<page id>/manifest.json` with "Controllers"
  (type "Keypad" for keys, "Encoder" for the dials of a Stream Deck +).
- V3 (app 7.1+): like V2 below a `Profiles/` folder, plus a `package.json`.

The archive is read in memory, no file is extracted. Manifests are found by
name wherever they are, so small differences between app versions do not
matter. Keys are addressed "column,row".

Only what Stream Assistant can do itself is converted: keys of the Home
Assistant plugin (de.perdoctus.streamdeck.homeassistant, by cgiesche),
folders, page navigation and multi actions with a single Home Assistant step.
Everything else stays empty and is listed in the report. Images are taken
only from converted keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import json
import posixpath
import re
from typing import Any
import zipfile

from .capabilities import CATALOG, DeckCapabilities, grid_capabilities
from .layout import (
    ACTION_CALL,
    ACTION_NONE,
    ACTION_PAGE,
    BACK_KEY,
    ROOT_PAGE_ID,
    SECOND_LINE_NONE,
)

# Limits against broken or hostile archives
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 20000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TITLE = 40
MAX_PAGE_NAME = 40

IMAGE_TYPES = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".gif": "gif", ".bmp": "bmp", ".webp": "webp"}

# Action UUIDs of the Stream Deck app
OPEN_CHILD = "com.elgato.streamdeck.profile.openchild"
BACK_TO_PARENT = "com.elgato.streamdeck.profile.backtoparent"
SWITCH_PROFILE = "com.elgato.streamdeck.profile.rotate"
NEXT_PAGE = ("com.elgato.streamdeck.profiles.nextpage", "com.elgato.streamdeck.page.next")
PREVIOUS_PAGE = ("com.elgato.streamdeck.profiles.previouspage", "com.elgato.streamdeck.page.previous")
GO_TO_PAGE = ("com.elgato.streamdeck.profiles.page", "com.elgato.streamdeck.page.goto")
MULTI_ACTIONS = (
    "com.elgato.streamdeck.multiactions.routine",
    "com.elgato.streamdeck.multiactions.routine2",
    "com.elgato.streamdeck.system.multiaction",
)
DELAY = "com.elgato.streamdeck.multiactions.delay"
# The Home Assistant plugin by Christoph Giesche ("Entity (generic)", "Entity (custom icons)")
HA_PLUGIN = "de.perdoctus.streamdeck.homeassistant"

# Model numbers printed on the decks, as the app stores them
MODEL_NUMBERS: dict[str, str] = {
    "20GAA9901": "original_v2",
    "20GAA9902": "original_v2",
    "20GBA9901": "mk2",
    "20GAT9901": "xl",
    "20GAT9902": "xl",
    "20GBD9901": "plus",
    "20GAI9901": "grid_3x2",
    "20GAI9902": "grid_3x2",
}

# Report reasons. Skipped: nothing of the control was taken over.
SKIP_UNSUPPORTED = "unsupported"
SKIP_MULTI_ACTION = "multi_action"
SKIP_PROFILE_SWITCH = "profile_switch"
SKIP_OUTSIDE = "outside"
SKIP_NO_SPACE = "no_space"
SKIP_HA_UNREADABLE = "ha_unreadable"
# Changed: the control was taken over, but not completely
CHANGE_SERVICE_TEMPLATE = "service_template"
CHANGE_SERVICE_INVALID = "service_invalid"
CHANGE_TITLE_TEMPLATE = "title_template"
CHANGE_TAP_DROPPED = "tap_dropped"
CHANGE_ROTATION_ADJUST = "rotation_adjust"
CHANGE_ROTATION_DROPPED = "rotation_dropped"
CHANGE_MOVED = "moved"
CHANGE_LINK_ADDED = "link_added"
CHANGE_UNKNOWN_ENTITY = "unknown_entity"
CHANGE_INVALID_ENTITY = "invalid_entity"
CHANGE_IMAGE_SKIPPED = "image_skipped"
CHANGE_MULTI_ACTION_STEP = "multi_action_step"

SKIP_REASONS = frozenset(
    {SKIP_UNSUPPORTED, SKIP_MULTI_ACTION, SKIP_PROFILE_SWITCH, SKIP_OUTSIDE, SKIP_NO_SPACE, SKIP_HA_UNREADABLE}
)

# Same rule as homeassistant.core.valid_entity_id / valid_domain
_ENTITY_ID = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")
_SERVICE = re.compile(r"^[\da-z_]+\.[\da-z_]+$")
_TEMPLATE = re.compile(r"\{\{|\{%")
# Domains a dial can adjust directly (actions.ADJUSTABLE_DOMAINS)
ADJUSTABLE_DOMAINS = frozenset(
    {"light", "cover", "fan", "media_player", "climate", "number", "input_number", "select", "input_select"}
)

LABELS: dict[str, dict[str, str]] = {
    "en": {"main": "Home", "page": "Page {n}", "folder": "Folder"},
    "de": {"main": "Startseite", "page": "Seite {n}", "folder": "Ordner"},
}


class ProfileError(Exception):
    """The file is not a readable Stream Deck profile. The message is a reason code."""


@dataclass
class ElgatoPage:
    """A page or folder of a profile: raw actions by position."""

    id: str
    name: str
    folder: str  # path of the page's folder inside the archive
    keys: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    dials: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Custom images of convertible controls by (control, col, row): (extension, data), None = not usable
    images: dict[tuple[str, int, int], tuple[str, bytes] | None] = field(default_factory=dict)


@dataclass
class ElgatoProfile:
    """A profile: its pages in order, the folders they open, and the device it was made for."""

    id: str
    name: str
    model_number: str | None
    size: tuple[int, int] | None
    pages: list[ElgatoPage]
    folders: dict[str, ElgatoPage]

    def suggested_model(self) -> DeckCapabilities:
        """The deck the profile was made for, or the smallest that holds all its keys."""
        if self.model_number and (model_id := MODEL_NUMBERS.get(self.model_number.upper())):
            return _model(model_id)
        all_pages = [*self.pages, *self.folders.values()]
        has_dials = any(page.dials for page in all_pages)
        if self.size:
            cols, rows = self.size
        else:
            cols = max((col + 1 for page in all_pages for col, _ in page.keys), default=1)
            rows = max((row + 1 for page in all_pages for _, row in page.keys), default=1)
        if has_dials and cols <= 4 and rows <= 2:
            return _model("plus")
        for model_id in ("grid_3x2", "mk2", "xl"):
            model = _model(model_id)
            if (model.cols, model.rows) == (cols, rows) or (
                not self.size and cols <= model.cols and rows <= model.rows
            ):
                return model
        return grid_capabilities(min(cols, 16), min(rows, 8), 4 if has_dials else 0)

    def summary(self) -> dict[str, Any]:
        """Counts for the import dialog."""
        controls = [
            action
            for page in (*self.pages, *self.folders.values())
            for action in (*page.keys.values(), *page.dials.values())
        ]
        return {
            "id": self.id,
            "name": self.name,
            "model_number": self.model_number,
            "suggested_model": self.suggested_model().model_id,
            "pages": len(self.pages),
            "folders": len(self.folders),
            "controls": len(controls),
            "ha_controls": sum(1 for action in controls if _is_ha(action) or _ha_step(action)),
        }


@dataclass
class ImportResult:
    """A layout made from a profile, the images it refers to, and what was not taken over."""

    layout: dict[str, Any]
    images: dict[str, bytes]
    report: list[dict[str, Any]]


def _model(model_id: str) -> DeckCapabilities:
    if model_id.startswith("grid_"):
        cols, rows = model_id[5:].split("x")
        return grid_capabilities(int(cols), int(rows))
    return next(caps for caps in CATALOG if caps.model_id == model_id)


# Reading the archive


def _page_id(folder: str) -> str:
    """Id of a page from its folder name: lower case, without ".sdProfile"."""
    name = posixpath.basename(folder.rstrip("/")).lower()
    return name.removesuffix(".sdprofile")


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes | None:
    if info.file_size > limit:
        return None
    with archive.open(info) as handle:
        data = handle.read(limit + 1)
    return data if len(data) <= limit else None


def _json(data: bytes | None) -> Any:
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def _position(text: str) -> tuple[int, int] | None:
    try:
        col, row = (int(part) for part in str(text).split(","))
    except ValueError:
        return None
    return (col, row) if col >= 0 and row >= 0 else None


def _controls(manifest: dict[str, Any]) -> tuple[dict[tuple[int, int], Any], dict[int, Any]]:
    """Keys and dials of a page manifest (V1: "Actions", V2/V3: "Controllers")."""
    keys: dict[tuple[int, int], Any] = {}
    dials: dict[int, Any] = {}
    controllers = manifest.get("Controllers")
    if not isinstance(controllers, list):
        controllers = [{"Type": "Keypad", "Actions": manifest.get("Actions")}]
    for controller in controllers:
        if not isinstance(controller, dict) or not isinstance(controller.get("Actions"), dict):
            continue
        encoder = str(controller.get("Type", "Keypad")).lower() == "encoder"
        for text, action in controller["Actions"].items():
            if not isinstance(action, dict) or (position := _position(text)) is None:
                continue
            if encoder:
                dials[position[0]] = action
            else:
                keys[position] = action
    return keys, dials


def _profile_pages(manifest: dict[str, Any]) -> list[str]:
    """Page ids of a V2/V3 profile manifest, in order."""
    pages = manifest.get("Pages")
    ids: list[Any] = []
    if isinstance(pages, dict):
        ids = list(pages.get("Pages") or [])
        if not ids and pages.get("Default"):
            ids = [pages["Default"]]
    elif isinstance(pages, list):
        ids = pages
    return [str(page).lower() for page in ids if isinstance(page, str) and page]


def parse_archive(data: bytes) -> list[ElgatoProfile]:
    """Read all profiles of an exported profile or a profile backup.

    Raises ProfileError("too_large" | "not_zip" | "no_profile").
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProfileError("too_large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as err:
        raise ProfileError("not_zip") from err
    if len(infos) > MAX_ENTRIES:
        raise ProfileError("too_large")
    with archive:
        return _parse(archive, infos)


def _parse(archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]) -> list[ElgatoProfile]:
    manifests: dict[str, dict[str, Any]] = {}
    package: dict[str, Any] = {}
    for info in infos:
        if info.is_dir():
            continue
        base = posixpath.basename(info.filename).lower()
        if base not in ("manifest.json", "package.json"):
            continue
        content = _json(_read(archive, info, MAX_MANIFEST_BYTES))
        if not isinstance(content, dict):
            continue
        folder = posixpath.dirname(info.filename)
        if base == "package.json":
            if not folder:
                package = content
        else:
            manifests[folder] = content

    # Pages and folders by id; a page id is unique within a profile
    by_id: dict[str, list[str]] = {}
    for folder, manifest in manifests.items():
        if "Controllers" in manifest or "Actions" in manifest:
            by_id.setdefault(_page_id(folder), []).append(folder)

    def find(page_id: str, below: str) -> str | None:
        candidates = by_id.get(page_id.lower().removesuffix(".sdprofile"), [])
        inside = [folder for folder in candidates if folder.startswith(below)]
        return (inside or candidates or [None])[0]

    children = {
        _page_id(str(action.get("Settings", {}).get("ProfileUUID", "")))
        for manifest in manifests.values()
        for action in _all_actions(manifest)
        if action.get("UUID") == OPEN_CHILD and isinstance(action.get("Settings"), dict)
    }
    profiles: list[ElgatoProfile] = []
    image_budget = MAX_TOTAL_IMAGE_BYTES
    for folder, manifest in sorted(manifests.items()):
        if "Pages" in manifest or ("Device" in manifest and "Controllers" not in manifest):
            page_folders = [f for page in _profile_pages(manifest) if (f := find(page, folder + "/")) is not None]
        elif "Actions" in manifest and "Controllers" not in manifest and _page_id(folder) not in children:
            page_folders = [folder]  # V1: the profile is its own first page
        else:
            continue
        device = manifest.get("Device") if isinstance(manifest.get("Device"), dict) else {}
        model_number = device.get("Model") or manifest.get("DeviceModel") or package.get("DeviceModel")
        size = device.get("Size") if isinstance(device.get("Size"), dict) else {}
        try:
            grid = (int(size["Columns"]), int(size["Rows"])) if size else None
        except (KeyError, TypeError, ValueError):
            grid = None
        if grid and not (1 <= grid[0] <= 16 and 1 <= grid[1] <= 8):
            grid = None
        pages = [_load_page(f, manifests[f]) for f in page_folders]
        if not pages:
            continue
        folders: dict[str, ElgatoPage] = {}
        queue = list(pages)
        while queue:
            page = queue.pop(0)
            for action in page.keys.values():
                if action.get("UUID") != OPEN_CHILD or not isinstance(action.get("Settings"), dict):
                    continue
                child = _page_id(str(action["Settings"].get("ProfileUUID", "")))
                if child in folders or not (child_folder := find(child, folder + "/")):
                    continue
                folders[child] = _load_page(child_folder, manifests[child_folder])
                queue.append(folders[child])
        profile = ElgatoProfile(
            id=_page_id(folder) or str(len(profiles)),
            name=str(manifest.get("Name") or package.get("Name") or "Stream Deck")[:60],
            model_number=str(model_number) if model_number else None,
            size=grid,
            pages=pages,
            folders=folders,
        )
        # Images are read now: the archive is closed when parsing is done
        image_budget = _load_images(archive, profile, image_budget)
        profiles.append(profile)
    if not profiles:
        raise ProfileError("no_profile")
    return profiles


def _all_actions(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    keys, dials = _controls(manifest)
    return [*keys.values(), *dials.values()]


def _load_page(folder: str, manifest: dict[str, Any]) -> ElgatoPage:
    keys, dials = _controls(manifest)
    return ElgatoPage(id=_page_id(folder), name=str(manifest.get("Name") or ""), folder=folder, keys=keys, dials=dials)


def _state(action: dict[str, Any]) -> dict[str, Any]:
    states = action.get("States")
    if not isinstance(states, list) or not states:
        return {}
    try:
        index = int(action.get("State") or 0)
    except (TypeError, ValueError):
        index = 0
    state = states[index] if 0 <= index < len(states) else states[0]
    return state if isinstance(state, dict) else {}


def _load_images(archive: zipfile.ZipFile, profile: ElgatoProfile, budget: int) -> int:
    """Read the custom images of the controls that can be converted; returns the budget left.

    Images of other controls (other plugins, hotkeys, ...) are never read.
    """
    names = {info.filename.lower(): info for info in archive.infolist() if not info.is_dir()}
    for page in (*profile.pages, *profile.folders.values()):
        controls = [("key", col, row, action) for (col, row), action in page.keys.items()]
        controls += [("dial", col, 0, action) for col, action in page.dials.items()]
        for kind, col, row, action in controls:
            if not _is_convertible(action):
                continue
            image = _state(action).get("Image")
            candidates = []
            if isinstance(image, str) and image:
                candidates += [posixpath.join(page.folder, image), posixpath.join(page.folder, f"{col},{row}", image)]
            candidates.append(posixpath.join(page.folder, f"{col},{row}", "CustomImages", "state0.png"))
            for candidate in candidates:
                info = names.get(posixpath.normpath(candidate).lower())
                if info is None:
                    continue
                extension = posixpath.splitext(info.filename)[1].lower()
                data = _read(archive, info, MAX_IMAGE_BYTES) if extension in IMAGE_TYPES else None
                if data is None or len(data) > budget:
                    page.images[(kind, col, row)] = None
                else:
                    budget -= len(data)
                    page.images[(kind, col, row)] = (IMAGE_TYPES[extension], data)
                break
    return budget


# Understanding actions


def _plugin_uuid(action: dict[str, Any]) -> str:
    plugin = action.get("Plugin")
    uuid = plugin.get("UUID") if isinstance(plugin, dict) else None
    return str(uuid or action.get("UUID") or "")


def _is_ha(action: dict[str, Any]) -> bool:
    return str(action.get("UUID", "")).startswith(HA_PLUGIN + ".") or _plugin_uuid(action) == HA_PLUGIN


def _sub_actions(action: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps of a multi action, wherever the app version keeps them."""
    found: list[dict[str, Any]] = []
    settings = action.get("Settings") if isinstance(action.get("Settings"), dict) else {}
    for source in (action.get("Actions"), settings.get("Actions"), settings.get("Routine")):
        stack = list(source) if isinstance(source, list) else []
        while stack:
            item = stack.pop(0)
            if not isinstance(item, dict):
                continue
            if "UUID" in item:
                found.append(item)
            elif isinstance(item.get("Actions"), list):
                stack[0:0] = item["Actions"]
            elif isinstance(item.get("Actions"), dict):
                stack[0:0] = list(item["Actions"].values())
    return found


def _ha_step(action: dict[str, Any]) -> dict[str, Any] | None:
    """The single Home Assistant step of a multi action whose other steps are only delays."""
    if action.get("UUID") not in MULTI_ACTIONS:
        return None
    steps = [step for step in _sub_actions(action) if step.get("UUID") != DELAY]
    return steps[0] if len(steps) == 1 and _is_ha(steps[0]) else None


def _is_convertible(action: dict[str, Any]) -> bool:
    uuid = action.get("UUID")
    return (
        _is_ha(action) or _ha_step(action) is not None or uuid in (OPEN_CHILD, *NEXT_PAGE, *PREVIOUS_PAGE, *GO_TO_PAGE)
    )


@dataclass
class _Service:
    service: str
    entity_id: str
    data: str


def _service(raw: Any) -> _Service | None:
    if not isinstance(raw, dict) or not raw.get("serviceId"):
        return None
    return _Service(str(raw["serviceId"]), str(raw.get("entityId") or ""), str(raw.get("serviceData") or ""))


@dataclass
class _HaSettings:
    entity_id: str
    title: str
    title_template: bool
    short: _Service | None
    long: _Service | None
    rotation: _Service | None
    tap: _Service | None


def _ha_settings(settings: Any) -> _HaSettings | None:
    """Settings of the Home Assistant plugin, any version (it migrates v1 to v8 the same way)."""
    if not isinstance(settings, dict):
        return None
    version = settings.get("version") or 1
    if version == 1:
        entity = str(settings.get("entityId") or "")
        domain = str(settings.get("domain") or entity.split(".", 1)[0])
        calls = []
        for name in ("service", "serviceLongPress"):
            raw = settings.get(name)
            calls.append(
                _Service(f"{domain}.{raw['id']}", entity, str(raw.get("data") or ""))
                if isinstance(raw, dict) and raw.get("id")
                else None
            )
        custom = bool(settings.get("useCustomTitle"))
        return _HaSettings(entity, str(settings.get("buttonTitle") or ""), custom, calls[0], calls[1], None, None)
    display = settings.get("display") if isinstance(settings.get("display"), dict) else {}
    button = settings.get("button") if isinstance(settings.get("button"), dict) else {}
    entity = str(display.get("entityId") or "")
    if version == 2:
        calls = []
        for name in ("service", "serviceLongPress"):
            raw = button.get(name)
            calls.append(
                _Service(f"{raw.get('domain')}.{raw['name']}", entity, str(raw.get("data") or ""))
                if isinstance(raw, dict) and raw.get("name")
                else None
            )
        short, long, rotation, tap = calls[0], calls[1], None, None
    else:
        short = _service(button.get("serviceShortPress"))
        long = _service(button.get("serviceLongPress"))
        rotation = _service(button.get("serviceRotation"))
        tap = _service(button.get("serviceTap"))
    return _HaSettings(
        entity,
        str(display.get("buttonTitle") or ""),
        bool(display.get("useCustomTitle")),
        short,
        long,
        rotation,
        tap,
    )


# Converting


@dataclass
class _Context:
    report: list[dict[str, Any]]
    images: dict[str, bytes]
    image_dir: str
    page_ids: list[str]  # layout page id of every Elgato page, in order
    folder_ids: dict[str, str]  # Elgato folder id -> layout page id
    page_names: dict[str, str]


@dataclass
class _Where:
    page: str
    control: str  # "key" | "dial"
    col: int
    row: int
    title: str
    action: str


def _title(action: dict[str, Any]) -> str:
    state = _state(action)
    if state.get("ShowTitle") is False:
        return ""
    title = str(state.get("Title") or "")
    return " ".join(title.split())[:MAX_TITLE]


def _action_name(action: dict[str, Any]) -> str:
    return str(action.get("Name") or action.get("UUID") or "?")[:80]


def _note(ctx: _Context, where: _Where, reason: str, detail: str = "") -> None:
    ctx.report.append(
        {
            "page": where.page,
            "control": where.control,
            "col": where.col,
            "row": where.row,
            "title": where.title,
            "action": where.action,
            "reason": reason,
            "skipped": reason in SKIP_REASONS,
            "detail": detail[:200],
        }
    )


def _call(ctx: _Context, where: _Where, call: _Service | None, fallback_entity: str) -> dict[str, Any]:
    """A plugin service call as a layout action ({"type": "none"} when it cannot be taken over)."""
    if call is None:
        return {"type": ACTION_NONE}
    if call.service == "streamdeck.open_url" or not _SERVICE.match(call.service):
        _note(ctx, where, CHANGE_SERVICE_INVALID, call.service)
        return {"type": ACTION_NONE}
    if _TEMPLATE.search(call.data):
        _note(ctx, where, CHANGE_SERVICE_TEMPLATE, f"{call.service}: {call.data}")
        return {"type": ACTION_NONE}
    data: Any = {}
    if call.data.strip():
        try:
            data = json.loads(call.data)
        except ValueError:
            data = None
    if not isinstance(data, dict):
        _note(ctx, where, CHANGE_SERVICE_INVALID, f"{call.service}: {call.data}")
        return {"type": ACTION_NONE}
    entity = call.entity_id or fallback_entity
    target: dict[str, Any] = {}
    if entity and "entity_id" not in data:
        if _ENTITY_ID.match(entity):
            target = {"entity_id": entity}
        else:
            _note(ctx, where, CHANGE_INVALID_ENTITY, entity)
    return {"type": ACTION_CALL, "action": call.service, "data": data, "target": target}


def _same_call(a: _Service | None, b: _Service | None) -> bool:
    return a is None or b is None or (a.service, a.entity_id, a.data) == (b.service, b.entity_id, b.data)


def _convert_ha(
    ctx: _Context, where: _Where, action: dict[str, Any], dial: bool, from_multi: bool = False
) -> dict[str, Any] | None:
    settings = _ha_settings(action.get("Settings"))
    if settings is None:
        _note(ctx, where, SKIP_HA_UNREADABLE)
        return None
    control: dict[str, Any] = {"title": where.title}
    entity = settings.entity_id
    if entity and not _ENTITY_ID.match(entity):
        _note(ctx, where, CHANGE_INVALID_ENTITY, entity)
        entity = ""
    if settings.title_template and settings.title and not where.title:
        if _TEMPLATE.search(settings.title):
            if settings.title.strip() not in ("{{friendly_name}}", "{{ friendly_name }}"):
                _note(ctx, where, CHANGE_TITLE_TEMPLATE, settings.title)
        else:
            control["title"] = " ".join(settings.title.split())[:MAX_TITLE]
    control["short"] = _call(ctx, where, settings.short, entity)
    control["long"] = _call(ctx, where, settings.long, entity)
    if dial:
        if settings.tap is not None:
            if control["short"]["type"] == ACTION_NONE and settings.short is None:
                control["short"] = _call(ctx, where, settings.tap, entity)
            elif not _same_call(settings.short, settings.tap):
                _note(ctx, where, CHANGE_TAP_DROPPED, settings.tap.service)
        if settings.rotation is not None:
            rotated = settings.rotation.entity_id or entity
            if _ENTITY_ID.match(rotated) and rotated.split(".", 1)[0] in ADJUSTABLE_DOMAINS:
                control["rotate"] = "adjust"
                entity = rotated
                _note(ctx, where, CHANGE_ROTATION_ADJUST, settings.rotation.service)
            else:
                _note(ctx, where, CHANGE_ROTATION_DROPPED, settings.rotation.service)
    if entity:
        control["entity_id"] = entity
    if from_multi:
        _note(ctx, where, CHANGE_MULTI_ACTION_STEP)
    return control


def _convert(
    ctx: _Context, where: _Where, action: dict[str, Any], page: ElgatoPage, page_index: int | None, dial: bool
) -> dict[str, Any] | None:
    """One control; None when it stays empty."""
    uuid = action.get("UUID")
    control: dict[str, Any] | None
    if _is_ha(action):
        control = _convert_ha(ctx, where, action, dial)
    elif (step := _ha_step(action)) is not None:
        control = _convert_ha(ctx, where, step, dial, from_multi=True)
    elif uuid == BACK_TO_PARENT:
        return None  # every folder has its back key at the first position
    elif uuid == OPEN_CHILD:
        child = _page_id(str((action.get("Settings") or {}).get("ProfileUUID", "")))
        if child not in ctx.folder_ids:
            _note(ctx, where, SKIP_UNSUPPORTED)
            return None
        target = ctx.folder_ids[child]
        control = {"title": where.title or ctx.page_names[target], "short": {"type": ACTION_PAGE, "page": target}}
    elif uuid in (*NEXT_PAGE, *PREVIOUS_PAGE, *GO_TO_PAGE):
        if uuid in GO_TO_PAGE:
            settings = action.get("Settings") if isinstance(action.get("Settings"), dict) else {}
            raw = settings.get("page", settings.get("PageIndex", settings.get("pageIndex")))
            try:
                index = int(raw)
            except (TypeError, ValueError):
                index = -1
        elif page_index is None:
            index = -1  # next / previous inside a folder: no page order there
        else:
            index = page_index + (1 if uuid in NEXT_PAGE else -1)
        if not 0 <= index < len(ctx.page_ids):
            _note(ctx, where, SKIP_UNSUPPORTED)
            return None
        target = ctx.page_ids[index]
        control = {"title": where.title or ctx.page_names[target], "short": {"type": ACTION_PAGE, "page": target}}
    elif uuid in MULTI_ACTIONS:
        _note(ctx, where, SKIP_MULTI_ACTION)
        return None
    elif uuid == SWITCH_PROFILE:
        _note(ctx, where, SKIP_PROFILE_SWITCH)
        return None
    else:
        _note(ctx, where, SKIP_UNSUPPORTED, _plugin_uuid(action))
        return None
    if control is None:
        return None
    if control["short"]["type"] == ACTION_PAGE:
        control["second_line"] = SECOND_LINE_NONE
    image_key = (where.control, where.col, where.row)
    if image_key in page.images:
        if (image := page.images[image_key]) is None:
            _note(ctx, where, CHANGE_IMAGE_SKIPPED)
        else:
            extension, data = image
            name = f"{len(ctx.images) + 1:03d}.{extension}"
            ctx.images[name] = data
            control["image"] = posixpath.join(ctx.image_dir, name)
    return control


def convert_profile(
    profile: ElgatoProfile, model: DeckCapabilities, image_dir: str, language: str = "en"
) -> ImportResult:
    """Turn a profile into a layout for a deck of the given model.

    The first page becomes the root page; further pages become folders of
    it, so their first key is the back key (a key there moves to a free
    position). Folders hang below the page whose key opens them. A page that
    no key leads to gets a link on the page before it. Image paths point into
    image_dir; the caller writes the returned images there.
    """
    labels = LABELS["de" if language.lower().startswith("de") else "en"]
    page_ids = [ROOT_PAGE_ID] + [f"page{n}" for n in range(2, len(profile.pages) + 1)]
    folder_ids = {folder_id: f"folder{n}" for n, folder_id in enumerate(profile.folders, start=1)}
    names: dict[str, str] = {}
    for n, (page, page_id) in enumerate(zip(profile.pages, page_ids, strict=True), start=1):
        names[page_id] = _page_name(page.name, labels["main"] if n == 1 else labels["page"].format(n=n))
    # A folder is named after the key that opens it, else after its own name
    parents: dict[str, str] = {}
    openers: dict[str, str] = {}
    for page, page_id in [
        *zip(profile.pages, page_ids, strict=True),
        *((f, folder_ids[f.id]) for f in profile.folders.values()),
    ]:
        for action in page.keys.values():
            if action.get("UUID") == OPEN_CHILD and isinstance(action.get("Settings"), dict):
                child = _page_id(str(action["Settings"].get("ProfileUUID", "")))
                if child in folder_ids and child not in parents:
                    parents[child] = page_id
                    openers[child] = _title(action)
    for folder_id, layout_id in folder_ids.items():
        names[layout_id] = _page_name(openers.get(folder_id) or profile.folders[folder_id].name, labels["folder"])

    ctx = _Context(
        report=[], images={}, image_dir=image_dir, page_ids=page_ids, folder_ids=folder_ids, page_names=names
    )
    pages: list[dict[str, Any]] = []
    sources = [(page, page_ids[n], n, None if n == 0 else ROOT_PAGE_ID) for n, page in enumerate(profile.pages)]
    sources += [
        (folder, folder_ids[folder.id], None, parents.get(folder.id, ROOT_PAGE_ID))
        for folder in profile.folders.values()
    ]
    for page, page_id, page_index, parent in sources:
        layout_page: dict[str, Any] = {"id": page_id, "name": names[page_id], "parent": parent, "keys": {}, "dials": {}}
        moved: list[tuple[_Where, dict[str, Any]]] = []
        for (col, row), action in sorted(page.keys.items(), key=lambda item: (item[0][1], item[0][0])):
            where = _Where(names[page_id], "key", col, row, _title(action), _action_name(action))
            if parent and (col, row) == (0, 0) and action.get("UUID") == BACK_TO_PARENT:
                continue
            control = _convert(ctx, where, action, page, page_index, dial=False)
            if control is None:
                continue
            if col >= model.cols or row >= model.rows:
                _note(ctx, where, SKIP_OUTSIDE)
                continue
            index = row * model.cols + col
            if parent and index == BACK_KEY:
                moved.append((where, control))
                continue
            layout_page["keys"][str(index)] = control
        for where, control in moved:
            if (free := _free_key(layout_page, model, bool(parent))) is None:
                _note(ctx, where, SKIP_NO_SPACE)
                continue
            layout_page["keys"][str(free)] = control
            _note(ctx, where, CHANGE_MOVED, str(free + 1))
        for col, action in sorted(page.dials.items()):
            where = _Where(names[page_id], "dial", col, 0, _title(action), _action_name(action))
            control = _convert(ctx, where, action, page, page_index, dial=True)
            if control is None:
                continue
            if col >= model.dials:
                _note(ctx, where, SKIP_OUTSIDE)
                continue
            layout_page["dials"][str(col)] = control
        pages.append(layout_page)

    _link_unreachable(ctx, pages, model)
    return ImportResult(layout={"pages": pages}, images=ctx.images, report=ctx.report)


def _page_name(name: str, fallback: str) -> str:
    name = " ".join(name.split())[:MAX_PAGE_NAME]
    return name or fallback


def _free_key(page: dict[str, Any], model: DeckCapabilities, folder: bool, last: bool = False) -> int | None:
    indexes = range(model.key_count - 1, -1, -1) if last else range(model.key_count)
    return next(
        (i for i in indexes if str(i) not in page["keys"] and not (folder and i == BACK_KEY)),
        None,
    )


def _link_unreachable(ctx: _Context, pages: list[dict[str, Any]], model: DeckCapabilities) -> None:
    """Pages and folders that no key opens get a key: pages on the page before, folders on their parent.

    A folder is unreachable when the key that opened it did not fit the deck.
    If there is no free key, the root page is tried.
    """
    linked = {
        control[slot]["page"]
        for page in pages
        for control in (*page["keys"].values(), *page["dials"].values())
        for slot in ("short", "long")
        if control.get(slot, {}).get("type") == ACTION_PAGE
    }
    by_id = {page["id"]: page for page in pages}
    hosts = {page_id: ctx.page_ids[n - 1] for n, page_id in enumerate(ctx.page_ids) if n}
    hosts.update({page["id"]: page["parent"] for page in pages if page["id"] not in hosts and page["parent"]})
    for page_id, before in hosts.items():
        if page_id in linked:
            continue
        for host_id in dict.fromkeys((before, ROOT_PAGE_ID)):
            host = by_id[host_id]
            free = _free_key(host, model, host["parent"] is not None, last=True)
            if free is not None:
                host["keys"][str(free)] = {
                    "title": ctx.page_names[page_id],
                    "icon": "mdi:arrow-right",
                    "second_line": SECOND_LINE_NONE,
                    "short": {"type": ACTION_PAGE, "page": page_id},
                }
                linked.add(page_id)
                where = _Where(host["name"], "key", free % model.cols, free // model.cols, ctx.page_names[page_id], "")
                _note(ctx, where, CHANGE_LINK_ADDED, ctx.page_names[page_id])
                break
        else:
            where = _Where(ctx.page_names[page_id], "key", 0, 0, ctx.page_names[page_id], "")
            _note(ctx, where, SKIP_NO_SPACE)
