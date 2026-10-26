"""What a deck can do, independent of manufacturer and transport.

Layout, rendering, templates and the editor work only with these
capabilities. A transport (Elgato Network Dock, virtual panel, bridge)
maps its hardware to a capability profile.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

IMAGE_JPEG = "jpeg"

# A dial's part of the touch strip of decks without a known strip size (templates, free grids)
SEGMENT_WIDTH = 200
STRIP_HEIGHT = 100


@dataclass(frozen=True, slots=True)
class DeckCapabilities:
    """Grid and key display of a deck, plus dials and the touch strip above them."""

    model_id: str
    name: str
    cols: int
    rows: int
    # Square key images, edge length in pixels
    key_size: int
    image_format: str = IMAGE_JPEG
    # Degrees the image must be rotated before it is sent (panel mounted upside down)
    rotation: int = 0
    # Rotary encoders, left to right; each owns an equal part of the touch strip
    dials: int = 0
    # Touch strip in pixels; 0 when there is none
    touch_width: int = 0
    touch_height: int = 0

    @property
    def key_count(self) -> int:
        """Return the number of keys."""
        return self.cols * self.rows

    @property
    def has_touch(self) -> bool:
        """Return True when there is a touch strip to draw on."""
        return self.touch_width > 0 and self.touch_height > 0

    @property
    def segment_width(self) -> int:
        """Width of one dial's part of the touch strip."""
        return self.touch_width // self.dials if self.dials and self.has_touch else 0

    def segment(self, x: int) -> int | None:
        """The dial whose part of the touch strip contains x."""
        if not self.segment_width:
            return None
        return min(self.dials - 1, max(0, x // self.segment_width))


# Known profiles; also what templates (planned decks) can be created for
CATALOG: tuple[DeckCapabilities, ...] = (
    DeckCapabilities("mk2", "Stream Deck MK.2", 5, 3, 72, rotation=180),
    DeckCapabilities("original_v2", "Stream Deck Original v2", 5, 3, 72, rotation=180),
    DeckCapabilities("xl", "Stream Deck XL", 8, 4, 96, rotation=180),
    DeckCapabilities("plus", "Stream Deck +", 4, 2, 120, dials=4, touch_width=800, touch_height=100),
)


# Free grids (virtual panels, templates for them): any size within these limits
MAX_COLS = 12
MAX_ROWS = 8
MAX_DIALS = 8
# Virtual panels are shown on tablets and phones, render sharp enough for high-DPI screens
GRID_KEY_SIZE = 144
_GRID_ID = re.compile(r"grid_(\d+)x(\d+)(?:_d(\d+))?")


def grid_id(cols: int, rows: int, dials: int = 0) -> str:
    """Model id of a free grid: "grid_5x3", with dials "grid_4x2_d4"."""
    return f"grid_{cols}x{rows}" + (f"_d{dials}" if dials else "")


def grid_capabilities(cols: int, rows: int, dials: int = 0) -> DeckCapabilities:
    """Profile of a free grid, e.g. a virtual panel with 4 columns and 2 rows.

    With dials, a touch strip of SEGMENT_WIDTH × STRIP_HEIGHT per dial is assumed.
    """
    if not (1 <= cols <= MAX_COLS and 1 <= rows <= MAX_ROWS and 0 <= dials <= MAX_DIALS):
        raise ValueError(f"Grid {cols}x{rows} with {dials} dials outside 1-{MAX_COLS} x 1-{MAX_ROWS}, 0-{MAX_DIALS}")
    name = f"{cols} × {rows}" + (f" + {dials}" if dials else "")
    return DeckCapabilities(
        grid_id(cols, rows, dials),
        name,
        cols,
        rows,
        GRID_KEY_SIZE,
        dials=dials,
        touch_width=dials * SEGMENT_WIDTH,
        touch_height=STRIP_HEIGHT if dials else 0,
    )


def find_capabilities(model_id: str | None) -> DeckCapabilities | None:
    """Return a profile by id: a known model or a free grid ("grid_5x3", "grid_4x2_d4")."""
    if model_id and (match := _GRID_ID.fullmatch(model_id)):
        try:
            return grid_capabilities(int(match[1]), int(match[2]), int(match[3] or 0))
        except ValueError:
            return None
    return next((caps for caps in CATALOG if caps.model_id == model_id), None)
