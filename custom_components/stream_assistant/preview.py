"""Rendering with a small cache, shared by real decks and templates."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from homeassistant.core import HomeAssistant

from .capabilities import DeckCapabilities
from .display import page_dial_visual, page_key_visual
from .render import KeyVisual, render_key, render_preview, render_segment

CACHE_SIZE = 256
# Editor previews of keys without a display (pedals)
PREVIEW_KEY_SIZE = 96


class RenderCache:
    """Renders key images in the executor and remembers recent results."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass
        self._cache: OrderedDict[tuple[str, int, int | bool, KeyVisual], bytes] = OrderedDict()

    async def async_render(self, model: DeckCapabilities, visual: KeyVisual, *, upright: bool) -> bytes:
        """JPEG of a key: upright for the editor, else as the deck expects it."""
        # Free grids share ids across key sizes (virtual panel 144 px, bridge deck 72 px)
        cache_key = (model.model_id, model.key_size, upright, visual)
        if (jpeg := self._cache.get(cache_key)) is not None:
            self._cache.move_to_end(cache_key)
            return jpeg
        if upright:
            jpeg = await self.hass.async_add_executor_job(render_preview, model.key_size or PREVIEW_KEY_SIZE, visual)
        else:
            jpeg = await self.hass.async_add_executor_job(render_key, model, visual)
        self._cache[cache_key] = jpeg
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return jpeg

    async def async_render_segment(self, model: DeckCapabilities, visual: KeyVisual) -> bytes:
        """Upright JPEG of a dial's part of the touch strip (the bridge turns it if needed)."""
        return await self.async_render_area(model.segment_width, model.touch_height, visual)

    async def async_render_area(self, width: int, height: int, visual: KeyVisual) -> bytes:
        """Upright JPEG of a wide area (strip segment, screen): icon and text side by side."""
        cache_key = ("area", width, height, visual)
        if (jpeg := self._cache.get(cache_key)) is not None:
            self._cache.move_to_end(cache_key)
            return jpeg
        jpeg = await self.hass.async_add_executor_job(render_segment, width, height, visual)
        self._cache[cache_key] = jpeg
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return jpeg

    async def async_dial_preview(self, model: DeckCapabilities, page: dict[str, Any]) -> list[bytes]:
        """Touch strip segments of every dial of a page; empty without a touch strip."""
        if not model.segment_width:
            return []
        return [
            await self.async_render_segment(model, page_dial_visual(self.hass, page, index))
            for index in range(model.dials)
        ]

    async def async_page_preview(self, model: DeckCapabilities, page: dict[str, Any]) -> list[bytes]:
        """Upright JPEGs of every key of a page, with live entity states."""
        return [
            await self.async_render(model, page_key_visual(self.hass, page, index), upright=True)
            for index in range(model.key_count)
        ]
