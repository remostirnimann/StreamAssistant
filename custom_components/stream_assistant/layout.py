"""Layout of a deck: pages, folders and what every key shows and does.

Stored per config entry. Shape (all plain JSON):

    {
      "pages": [
        {"id": "main", "name": "Startseite", "parent": null, "keys": {"0": KEY, ...}},
        {"id": "a1b2c3", "name": "Licht OG", "parent": "main", "keys": {...}}
      ]
    }

A page with a parent is a folder: its first key is reserved for "back".

KEY:
    {
      "title": "Wohnzimmer",
      "icon": "mdi:lightbulb-on",       # icon when on (or always), null = automatic
      "icon_off": "mdi:lightbulb-outline",  # icon when off, null = same as "icon"
      "entity_id": "light.wohnzimmer",  # state source for colours / second line, or null
      "second_line": "state",           # state | text | none
      "second_text": "",                # used when second_line == "text"
      "on_color": "#f2b134",
      "off_color": "#2b2b2b",
      "text_color": null,               # null = automatic contrast
      "font_size": null,
      "image": null,                    # path on the HA host
      "short": ACTION,
      "long": ACTION
    }

ACTION:
    {"type": "none"}
    {"type": "default", "entity_id": "..."}          # toggle / activate, depending on domain
    {"type": "action", "action": "light.turn_on", "data": {...}, "target": {...}}
    {"type": "page", "page": "<page id>"}
    {"type": "back"}
"""

from __future__ import annotations

import copy
import secrets
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

ROOT_PAGE_ID = "main"
BACK_KEY = 0

ACTION_NONE = "none"
ACTION_DEFAULT = "default"
ACTION_CALL = "action"
ACTION_PAGE = "page"
ACTION_BACK = "back"

SECOND_LINE_STATE = "state"
SECOND_LINE_TEXT = "text"
SECOND_LINE_NONE = "none"

DEFAULT_ON_COLOR = "#f2b134"
DEFAULT_OFF_COLOR = "#2b2b2b"

HEX_COLOR = vol.Match(r"^#[0-9a-fA-F]{6}$")

ACTION_SCHEMA = vol.Schema(
    vol.Any(
        {vol.Required("type"): vol.In([ACTION_NONE, ACTION_BACK])},
        {vol.Required("type"): ACTION_DEFAULT, vol.Required("entity_id"): cv.entity_id},
        {
            vol.Required("type"): ACTION_CALL,
            vol.Required("action"): cv.service,
            vol.Optional("data", default=dict): dict,
            vol.Optional("target", default=dict): dict,
        },
        {vol.Required("type"): ACTION_PAGE, vol.Required("page"): cv.string},
    )
)

KEY_SCHEMA = vol.Schema(
    {
        vol.Optional("title", default=""): vol.All(cv.string, vol.Length(max=40)),
        vol.Optional("icon", default=None): vol.Any(None, vol.Match(r"^mdi:[a-z0-9-]+$")),
        vol.Optional("icon_off", default=None): vol.Any(None, vol.Match(r"^mdi:[a-z0-9-]+$")),
        vol.Optional("entity_id", default=None): vol.Any(None, cv.entity_id),
        vol.Optional("second_line", default=SECOND_LINE_STATE): vol.In(
            [SECOND_LINE_STATE, SECOND_LINE_TEXT, SECOND_LINE_NONE]
        ),
        vol.Optional("second_text", default=""): vol.All(cv.string, vol.Length(max=40)),
        vol.Optional("on_color", default=DEFAULT_ON_COLOR): HEX_COLOR,
        vol.Optional("off_color", default=DEFAULT_OFF_COLOR): HEX_COLOR,
        vol.Optional("text_color", default=None): vol.Any(None, HEX_COLOR),
        vol.Optional("font_size", default=None): vol.Any(None, vol.All(int, vol.Range(min=6, max=96))),
        vol.Optional("image", default=None): vol.Any(None, cv.string),
        vol.Optional("short", default=lambda: {"type": ACTION_NONE}): ACTION_SCHEMA,
        vol.Optional("long", default=lambda: {"type": ACTION_NONE}): ACTION_SCHEMA,
    }
)

PAGE_SCHEMA = vol.Schema(
    {
        vol.Required("id"): vol.Match(r"^[A-Za-z0-9_-]{1,32}$"),
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=40)),
        vol.Optional("parent", default=None): vol.Any(None, cv.string),
        vol.Optional("keys", default=dict): {vol.Match(r"^\d{1,3}$"): KEY_SCHEMA},
    }
)

LAYOUT_SCHEMA = vol.Schema({vol.Required("pages"): [PAGE_SCHEMA]})


def new_page_id() -> str:
    """Return a random page id."""
    return secrets.token_hex(4)


def empty_layout() -> dict[str, Any]:
    """Layout with just the root page."""
    return {"pages": [{"id": ROOT_PAGE_ID, "name": "Startseite", "parent": None, "keys": {}}]}


def validate_layout(data: Any, key_count: int | None) -> dict[str, Any]:
    """Validate a full layout. Raises vol.Invalid with a readable message."""
    layout = LAYOUT_SCHEMA(copy.deepcopy(data))
    ids = [page["id"] for page in layout["pages"]]
    if len(ids) != len(set(ids)):
        raise vol.Invalid("Page ids must be unique")
    if ROOT_PAGE_ID not in ids:
        raise vol.Invalid("The root page is missing")
    for page in layout["pages"]:
        if page["id"] == ROOT_PAGE_ID:
            page["parent"] = None
        elif page["parent"] not in ids or page["parent"] == page["id"]:
            raise vol.Invalid(f"Page {page['name']}: unknown parent")
        for index, key in page["keys"].items():
            if key_count is not None and int(index) >= key_count:
                raise vol.Invalid(f"Page {page['name']}: key {int(index) + 1} does not exist")
            for slot in ("short", "long"):
                action = key[slot]
                if action["type"] == ACTION_PAGE and action["page"] not in ids:
                    raise vol.Invalid(f"Page {page['name']}: key {int(index) + 1} links to an unknown page")
    return layout


def migrate_v1(old: dict[str, Any]) -> dict[str, Any]:
    """Version 1 stored only {"keys": {index: appearance}} from the set_key action."""
    layout = empty_layout()
    keys = layout["pages"][0]["keys"]
    for index, appearance in old.get("keys", {}).items():
        keys[str(index)] = KEY_SCHEMA(
            {
                "title": appearance.get("text", ""),
                "on_color": appearance.get("background_color", DEFAULT_ON_COLOR),
                "off_color": appearance.get("background_color", DEFAULT_OFF_COLOR),
                "text_color": appearance.get("text_color"),
                "font_size": appearance.get("font_size"),
                "image": appearance.get("image"),
                "second_line": SECOND_LINE_NONE,
            }
        )
    return layout


def remap_layout(
    layout: dict[str, Any], from_cols: int, to_cols: int, to_rows: int
) -> tuple[dict[str, Any], int]:
    """Move keys to another grid size, keeping row and column.

    Returns the new layout and how many keys did not fit.
    """
    result = copy.deepcopy(layout)
    if from_cols == to_cols:
        dropped = 0
        for page in result["pages"]:
            for index in [i for i in page["keys"] if int(i) >= to_cols * to_rows]:
                del page["keys"][index]
                dropped += 1
        return result, dropped
    dropped = 0
    for page in result["pages"]:
        moved: dict[str, Any] = {}
        for index, key in page["keys"].items():
            row, col = divmod(int(index), from_cols)
            if row < to_rows and col < to_cols:
                moved[str(row * to_cols + col)] = key
            else:
                dropped += 1
        page["keys"] = moved
    return result, dropped


def merge_into_template(
    deck_layout: dict[str, Any],
    deck_cols: int,
    deck_rows: int,
    template_layout: dict[str, Any],
    template_cols: int,
    template_rows: int,
) -> dict[str, Any]:
    """Write a smaller (or differently shaped) deck's edit back into its template.

    Only the part of the template the deck can show is replaced; keys
    outside the deck's grid are kept, so editing on a small deck never
    deletes keys of a bigger template.
    """
    mapped, _ = remap_layout(deck_layout, deck_cols, template_cols, template_rows)
    old_pages = {page["id"]: page for page in template_layout["pages"]}
    pages = []
    for page in mapped["pages"]:
        keys = {}
        if (old := old_pages.get(page["id"])) is not None:
            for index, key in old["keys"].items():
                row, col = divmod(int(index), template_cols)
                if row >= deck_rows or col >= deck_cols:
                    keys[index] = copy.deepcopy(key)
        keys.update(page["keys"])
        pages.append({**page, "keys": keys})
    return {"pages": pages}


def default_key() -> dict[str, Any]:
    """A blank key with all defaults filled in."""
    return KEY_SCHEMA({})
