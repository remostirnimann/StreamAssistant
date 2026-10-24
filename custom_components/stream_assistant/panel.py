"""Sidebar panel hosting the key editor, and the dashboard card of virtual panels."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import PANEL_URL, VERSION

STATIC_URL = "/stream_assistant_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve the scripts, add the sidebar entry (admins only) and load the card everywhere."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    # Loaded on every dashboard, so the card needs no manual resource entry
    add_extra_js_url(hass, f"{STATIC_URL}/card.js?v={VERSION}")
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="stream-assistant-panel",
        frontend_url_path=PANEL_URL,
        module_url=f"{STATIC_URL}/panel.js?v={VERSION}",
        sidebar_title="Stream Assistant",
        sidebar_icon="mdi:view-grid-outline",
        require_admin=True,
        config={},
    )
