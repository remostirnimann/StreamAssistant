"""Import of Elgato Stream Deck app profiles as templates (editor, admins only).

1. The editor uploads the file to ElgatoUploadView. It is read in memory,
   parsed and kept for IMPORT_TTL seconds under a random token; the answer
   lists the profiles found in it.
2. stream_assistant/import/create turns the chosen profiles into templates
   for the chosen models and answers with a report per template.

The upload goes over HTTP because a backup of all profiles can be larger than
a WebSocket message may be.
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
import logging
from pathlib import Path
import secrets
import time
from typing import Any

from aiohttp import web
from homeassistant.components import websocket_api
from homeassistant.components.http import KEY_HASS, KEY_HASS_USER, HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey
import voluptuous as vol

from .capabilities import find_capabilities
from .const import DOMAIN
from .elgato_import import (
    CHANGE_UNKNOWN_ENTITY,
    MAX_ARCHIVE_BYTES,
    ElgatoProfile,
    ProfileError,
    convert_profile,
    parse_archive,
)
from .layout import ACTION_SLOTS, validate_layout
from .templates import DATA_TEMPLATES

_LOGGER = logging.getLogger(__name__)

UPLOAD_URL = "/api/stream_assistant/import/elgato"
IMPORT_TTL = 15 * 60
MAX_PENDING = 3
# Images of imported keys: Home Assistant allows reading below www by default
IMAGE_FOLDER = ("www", "stream_assistant", "import")

DATA_IMPORTS: HassKey[dict[str, PendingImport]] = HassKey(f"{DOMAIN}_imports")


@dataclass
class PendingImport:
    """Profiles of an uploaded file, until they are imported or expire."""

    expires: float
    profiles: dict[str, ElgatoProfile]


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register the upload view and the WebSocket command."""
    hass.data[DATA_IMPORTS] = {}
    hass.http.register_view(ElgatoUploadView())
    websocket_api.async_register_command(hass, ws_import_create)


def _pending(hass: HomeAssistant) -> dict[str, PendingImport]:
    imports = hass.data[DATA_IMPORTS]
    now = time.monotonic()
    for token in [token for token, pending in imports.items() if pending.expires < now]:
        del imports[token]
    return imports


class ElgatoUploadView(HomeAssistantView):
    """Receives an exported profile or a profile backup and lists the profiles in it."""

    url = UPLOAD_URL
    name = "api:stream_assistant:import:elgato"

    async def post(self, request: web.Request) -> web.Response:
        """Read the "file" field of a multipart upload."""
        hass = request.app[KEY_HASS]
        if not request[KEY_HASS_USER].is_admin:
            return self.json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        try:
            data = await _read_upload(request)
        except ProfileError as err:
            return self.json({"error": str(err)}, HTTPStatus.BAD_REQUEST)
        try:
            profiles = await hass.async_add_executor_job(parse_archive, data)
        except ProfileError as err:
            return self.json({"error": str(err)}, HTTPStatus.BAD_REQUEST)
        imports = _pending(hass)
        while len(imports) >= MAX_PENDING:
            del imports[next(iter(imports))]
        token = secrets.token_hex(8)
        imports[token] = PendingImport(time.monotonic() + IMPORT_TTL, {p.id: p for p in profiles})
        return self.json({"token": token, "profiles": [profile.summary() for profile in profiles]})


async def _read_upload(request: web.Request) -> bytes:
    """The uploaded file, streamed, refused when larger than the parser accepts."""
    try:
        reader = await request.multipart()
        while (part := await reader.next()) is not None:
            if getattr(part, "name", None) != "file":
                continue
            data = bytearray()
            while chunk := await part.read_chunk(256 * 1024):  # type: ignore[union-attr]
                data += chunk
                if len(data) > MAX_ARCHIVE_BYTES:
                    raise ProfileError("too_large")
            return bytes(data)
    except (ValueError, AssertionError, KeyError) as err:
        raise ProfileError("no_file") from err
    raise ProfileError("no_file")


def _write_images(folder: Path, images: dict[str, bytes]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in images.items():
        (folder / name).write_bytes(data)


def _note_unknown_entities(
    hass: HomeAssistant, layout: dict[str, Any], cols: int, report: list[dict[str, Any]]
) -> None:
    """Entities the profile uses that this Home Assistant does not have (yet): kept, but reported."""
    for page in layout["pages"]:
        for kind, controls in (("key", page["keys"]), ("dial", page["dials"])):
            for index, control in controls.items():
                entities = {control.get("entity_id")}
                for slot in ACTION_SLOTS:
                    target = (control.get(slot) or {}).get("target") or {}
                    entities.add(target.get("entity_id"))
                missing = sorted(e for e in entities if isinstance(e, str) and e and hass.states.get(e) is None)
                if not missing:
                    continue
                col, row = (int(index) % cols, int(index) // cols) if kind == "key" else (int(index), 0)
                report.append(
                    {
                        "page": page["name"],
                        "control": kind,
                        "col": col,
                        "row": row,
                        "title": control.get("title", ""),
                        "action": "",
                        "reason": CHANGE_UNKNOWN_ENTITY,
                        "skipped": False,
                        "detail": ", ".join(missing),
                    }
                )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "stream_assistant/import/create",
        vol.Required("token"): str,
        vol.Required("profiles"): vol.All(
            [
                {
                    vol.Required("id"): str,
                    vol.Required("name"): vol.All(str, vol.Length(min=1, max=60)),
                    vol.Required("model"): str,
                }
            ],
            vol.Length(min=1),
        ),
    }
)
@websocket_api.async_response
async def ws_import_create(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Create a template from each chosen profile of an upload."""
    pending = _pending(hass).get(msg["token"])
    if pending is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "The upload has expired, please upload again")
        return
    jobs = []
    for choice in msg["profiles"]:
        profile = pending.profiles.get(choice["id"])
        model = find_capabilities(choice["model"])
        if profile is None or model is None:
            connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Unknown profile or model")
            return
        jobs.append((choice["name"], profile, model))
    manager = hass.data[DATA_TEMPLATES]
    created = []
    for name, profile, model in jobs:
        folder = Path(hass.config.path(*IMAGE_FOLDER, secrets.token_hex(4)))
        result = convert_profile(profile, model, str(folder), hass.config.language)
        try:
            layout = validate_layout(result.layout, model.key_count, model.dials)
        except vol.Invalid as err:
            # The converter only produces valid layouts; this guards against what it missed
            _LOGGER.error("Imported profile %s gave an invalid layout: %s", profile.name, err)
            connection.send_error(msg["id"], websocket_api.ERR_UNKNOWN_ERROR, f"Import failed: {err}")
            return
        if result.images:
            await hass.async_add_executor_job(_write_images, folder, result.images)
        report = list(result.report)
        _note_unknown_entities(hass, layout, model.cols, report)
        template = await manager.async_create(name, model.model_id, layout)
        created.append(
            {
                "template_id": template["id"],
                "name": name,
                "model": model.model_id,
                "pages": len(layout["pages"]),
                "controls": sum(len(page["keys"]) + len(page["dials"]) for page in layout["pages"]),
                "images": len(result.images),
                "image_folder": str(folder) if result.images else None,
                "report": report,
            }
        )
    connection.send_result(msg["id"], {"templates": created})
