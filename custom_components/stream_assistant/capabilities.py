"""What a deck can do, independent of manufacturer and transport.

Layout, rendering, templates and the editor work only with these
capabilities. A transport (Elgato Network Dock, virtual panel; bridge
later) maps its hardware to a capability profile.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

IMAGE_JPEG = "jpeg"


@dataclass(frozen=True, slots=True)
class DeckCapabilities:
    """Grid and key display of a deck."""

    model_id: str
    name: str
    cols: int
    rows: int
    # Square key images, edge length in pixels
    key_size: int
    image_format: str = IMAGE_JPEG
    # Degrees the image must be rotated before it is sent (panel mounted upside down)
    rotation: int = 0

    @property
    def key_count(self) -> int:
        """Return the number of keys."""
        return self.cols * self.rows


# Known profiles; also what templates (planned decks) can be created for
CATALOG: tuple[DeckCapabilities, ...] = (
    DeckCapabilities("mk2", "Stream Deck MK.2", 5, 3, 72, rotation=180),
    DeckCapabilities("original_v2", "Stream Deck Original v2", 5, 3, 72, rotation=180),
    DeckCapabilities("xl", "Stream Deck XL", 8, 4, 96, rotation=180),
)


# Free grids (virtual panels, templates for them): any size within these limits
MAX_COLS = 12
MAX_ROWS = 8
# Virtual panels are shown on tablets and phones, render sharp enough for high-DPI screens
GRID_KEY_SIZE = 144
_GRID_ID = re.compile(r"grid_(\d+)x(\d+)")


def grid_capabilities(cols: int, rows: int) -> DeckCapabilities:
    """Profile of a free grid, e.g. a virtual panel with 4 columns and 2 rows."""
    if not (1 <= cols <= MAX_COLS and 1 <= rows <= MAX_ROWS):
        raise ValueError(f"Grid {cols}x{rows} outside 1-{MAX_COLS} x 1-{MAX_ROWS}")
    return DeckCapabilities(f"grid_{cols}x{rows}", f"{cols} × {rows}", cols, rows, GRID_KEY_SIZE)


def find_capabilities(model_id: str | None) -> DeckCapabilities | None:
    """Return a profile by id: a known model or a free grid ("grid_5x3")."""
    if model_id and (match := _GRID_ID.fullmatch(model_id)):
        try:
            return grid_capabilities(int(match[1]), int(match[2]))
        except ValueError:
            return None
    return next((caps for caps in CATALOG if caps.model_id == model_id), None)
