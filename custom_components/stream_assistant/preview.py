"""Rendering with a small cache, shared by real decks and templates."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from homeassistant.core import HomeAssistant

from .display import page_key_visual
from .capabilities import DeckCapabilities
from .render import KeyVisual, render_key, render_preview

CACHE_SIZE = 256


class RenderCache:
    """Renders key images in the executor and remembers recent results."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self._cache: OrderedDict[tuple[str, int, bool, KeyVisual], bytes] = OrderedDict()

    async def async_render(self, model: DeckCapabilities, visual: KeyVisual, *, upright: bool) -> bytes:
        """JPEG of a key: upright for the editor, else as the deck expects it."""
        # Free grids share ids across key sizes (virtual panel 144 px, bridge deck 72 px)
        cache_key = (model.model_id, model.key_size, upright, visual)
        if (jpeg := self._cache.get(cache_key)) is not None:
            self._cache.move_to_end(cache_key)
            return jpeg
        if upright:
            jpeg = await self.hass.async_add_executor_job(render_preview, model.key_size, visual)
        else:
            jpeg = await self.hass.async_add_executor_job(render_key, model, visual)
        self._cache[cache_key] = jpeg
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return jpeg

    async def async_page_preview(self, model: DeckCapabilities, page: dict[str, Any]) -> list[bytes]:
        """Upright JPEGs of every key of a page, with live entity states."""
        return [
            await self.async_render(model, page_key_visual(self.hass, page, index), upright=True)
            for index in range(model.key_count)
        ]
