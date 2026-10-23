"""What a deck can do, independent of manufacturer and transport.

Layout, rendering, templates and the editor work only with these
capabilities. A transport (Elgato Network Dock today; bridge and virtual
decks later) maps its hardware to a capability profile.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def find_capabilities(model_id: str | None) -> DeckCapabilities | None:
    """Return a profile by id."""
    return next((caps for caps in CATALOG if caps.model_id == model_id), None)
