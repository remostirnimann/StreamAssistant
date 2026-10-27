"""Layout model: validation, migration and moving keys between grids."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.stream_assistant.layout import (
    ROOT_PAGE_ID,
    default_key,
    empty_layout,
    merge_into_template,
    migrate_v1,
    new_page_id,
    remap_layout,
    validate_layout,
)


def _layout(*pages: dict) -> dict:
    return {"pages": list(pages)}


def _page(page_id: str = ROOT_PAGE_ID, parent: str | None = None, **keys: dict) -> dict:
    return {
        "id": page_id,
        "name": page_id.title(),
        "parent": parent,
        "keys": {k.lstrip("k"): v for k, v in keys.items()},
    }


def test_empty_layout_and_defaults() -> None:
    layout = empty_layout()
    assert validate_layout(layout, 15) == layout
    key = default_key()
    assert key["short"] == {"type": "none"}
    assert key["second_line"] == "state"
    assert len(new_page_id()) == 8


def test_validate_fills_defaults_and_keeps_input_untouched() -> None:
    raw = _layout(_page(k0={"title": "Licht", "entity_id": "light.buero"}))
    layout = validate_layout(raw, 15)
    key = layout["pages"][0]["keys"]["0"]
    assert key["on_color"] == "#f2b134"
    assert key["long"] == {"type": "none"}
    assert "on_color" not in raw["pages"][0]["keys"]["0"]


def test_root_page_never_has_a_parent() -> None:
    layout = validate_layout(_layout(_page(parent="elsewhere"), _page("elsewhere", ROOT_PAGE_ID)), 15)
    assert layout["pages"][0]["parent"] is None


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        (_layout(_page(), _page()), "unique"),
        (_layout(_page("other")), "root page"),
        (_layout(_page(), _page("folder", "nowhere")), "unknown parent"),
        (_layout(_page(), _page("loop", "loop")), "unknown parent"),
        (_layout(_page(k15={"title": "x"})), "key 16 does not exist"),
        (_layout(_page(k1={"short": {"type": "page", "page": "missing"}})), "unknown page"),
    ],
)
def test_validate_rejects(layout: dict, message: str) -> None:
    with pytest.raises(vol.Invalid, match=message):
        validate_layout(layout, 15)


def test_validate_without_grid_accepts_any_key() -> None:
    assert "40" in validate_layout(_layout(_page(k40={})), None)["pages"][0]["keys"]


def test_validate_rejects_bad_values() -> None:
    with pytest.raises(vol.Invalid):
        validate_layout(_layout(_page(k0={"on_color": "red"})), 15)
    with pytest.raises(vol.Invalid):
        validate_layout(_layout(_page(k0={"short": {"type": "action", "action": "not a service"}})), 15)


def test_migrate_v1() -> None:
    layout = migrate_v1({"keys": {"3": {"text": "Hi", "background_color": "#112233", "font_size": 20}}})
    key = layout["pages"][0]["keys"]["3"]
    assert key["title"] == "Hi"
    assert key["on_color"] == key["off_color"] == "#112233"
    assert key["second_line"] == "none"
    assert key["font_size"] == 20
    assert migrate_v1({}) == empty_layout()


def test_remap_same_width_drops_rows_below() -> None:
    layout = _layout(_page(k0={"title": "a"}, k14={"title": "b"}))
    result, dropped = remap_layout(layout, 5, 5, 2)
    assert list(result["pages"][0]["keys"]) == ["0"]
    assert dropped == 1
    # The input stays unchanged
    assert "14" in layout["pages"][0]["keys"]


def test_remap_keeps_row_and_column() -> None:
    # 5x3: key 6 is row 1, column 1; key 4 is row 0, column 4 (outside a 3 wide grid)
    layout = _layout(_page(k6={"title": "a"}, k4={"title": "b"}))
    result, dropped = remap_layout(layout, 5, 3, 3)
    assert result["pages"][0]["keys"] == {"4": {"title": "a"}}
    assert dropped == 1


def test_merge_into_template_keeps_keys_outside_the_deck() -> None:
    template = _layout(_page(k0={"title": "old"}, k7={"title": "outside"}), _page("gone", ROOT_PAGE_ID))
    deck = _layout(_page(k0={"title": "new"}), _page("fresh", ROOT_PAGE_ID, k1={"title": "x"}))
    # Deck 2x2 edits an 8x4 template: key 7 (row 0, column 7) is outside the deck
    merged = merge_into_template(deck, 2, 2, template, 8, 4)
    pages = {p["id"]: p for p in merged["pages"]}
    assert pages[ROOT_PAGE_ID]["keys"] == {"0": {"title": "new"}, "7": {"title": "outside"}}
    assert pages["fresh"]["keys"] == {"1": {"title": "x"}}
    assert "gone" not in pages
