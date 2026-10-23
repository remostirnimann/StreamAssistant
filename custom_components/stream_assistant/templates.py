"""Templates: layouts that are not bound to a dock.

A template has a model (grid size), so it doubles as a "virtual deck" that
can be planned before the hardware exists. Decks can be linked to a
template; all linked decks then show (and edit) the template's layout.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
import secrets
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .layout import empty_layout
from .preview import RenderCache
from .capabilities import DeckCapabilities, find_capabilities

STORAGE_VERSION = 1
SAVE_DELAY = 2

DATA_TEMPLATES: HassKey[TemplateManager] = HassKey(f"{DOMAIN}_templates")

# Listener argument: the template; it carries "deleted": True when it was deleted
TemplateListener = Callable[[dict[str, Any]], None]


class TemplateManager:
    """Loads, stores and announces changes of all templates."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self.renderer = RenderCache(hass)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.templates")
        self._templates: dict[str, dict[str, Any]] = {}
        self._listeners: dict[str, set[TemplateListener]] = {}
        self._revision_prefix = secrets.token_hex(4)
        self._revisions: dict[str, int] = {}

    async def async_load(self) -> None:
        """Read templates from storage."""
        if stored := await self._store.async_load():
            self._templates = {t["id"]: t for t in stored.get("templates", [])}

    def _schedule_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"templates": list(self._templates.values())}, SAVE_DELAY
        )

    def list(self) -> list[dict[str, Any]]:
        """All templates, sorted by name."""
        return sorted(self._templates.values(), key=lambda t: t["name"].lower())

    def get(self, template_id: str) -> dict[str, Any] | None:
        """Return one template."""
        return self._templates.get(template_id)

    def model(self, template_id: str) -> DeckCapabilities | None:
        """Model (grid size) of a template."""
        template = self.get(template_id)
        return find_capabilities(template["model"]) if template else None

    def revision(self, template_id: str) -> str:
        """Changes on every save, so stale editor saves can be refused."""
        return f"{self._revision_prefix}-{self._revisions.get(template_id, 0)}"

    @callback
    def async_subscribe(self, template_id: str, listener: TemplateListener) -> CALLBACK_TYPE:
        """Call listener whenever the template changes or is deleted."""
        self._listeners.setdefault(template_id, set()).add(listener)

        @callback
        def _unsubscribe() -> None:
            self._listeners.get(template_id, set()).discard(listener)

        return _unsubscribe

    def linked_count(self, template_id: str) -> int:
        """Number of decks currently linked."""
        return len(self._listeners.get(template_id, ()))

    @callback
    def _notify(self, template_id: str, template: dict[str, Any]) -> None:
        for listener in list(self._listeners.get(template_id, ())):
            listener(template)

    async def async_create(self, name: str, model_id: str, layout: dict[str, Any] | None) -> dict[str, Any]:
        """Create a template (empty, or from an existing layout)."""
        template = {
            "id": secrets.token_hex(6),
            "name": name,
            "model": model_id,
            "layout": copy.deepcopy(layout) if layout else empty_layout(),
        }
        self._templates[template["id"]] = template
        self._schedule_save()
        return template

    async def async_set_layout(self, template_id: str, layout: dict[str, Any]) -> None:
        """Replace the layout (already validated for the template's model)."""
        template = self._templates[template_id]
        template["layout"] = layout
        self._revisions[template_id] = self._revisions.get(template_id, 0) + 1
        self._schedule_save()
        self._notify(template_id, template)

    async def async_rename(self, template_id: str, name: str) -> None:
        """Rename a template."""
        self._templates[template_id]["name"] = name
        self._schedule_save()
        self._notify(template_id, self._templates[template_id])

    async def async_delete(self, template_id: str) -> None:
        """Delete a template; linked decks keep a copy of its layout."""
        template = self._templates.pop(template_id)
        self._schedule_save()
        # Linked decks get the template one last time, marked deleted, and keep a copy
        for listener in list(self._listeners.pop(template_id, ())):
            listener({**template, "deleted": True})
        self._revisions.pop(template_id, None)
