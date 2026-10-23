"""Render a sheet of sample keys to a PNG, to check the key renderer without a deck.

Usage: .venv\\Scripts\\python.exe scripts\\render_sheet.py <out.png> [key_size]
"""

from __future__ import annotations

import io
from pathlib import Path
import sys
import types

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "stream_assistant"
_pkg = types.ModuleType("sa")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules["sa"] = _pkg

from PIL import Image  # noqa: E402

from sa.render import KeyVisual, render_preview  # noqa: E402

SAMPLES = [
    KeyVisual("Wohnzimmer", "An · 80 %", "lightbulb", "#f2b134"),
    KeyVisual("Esstisch", "Aus", "lightbulb", "#2b2b2b"),
    KeyVisual("Store Ost", "Offen · 100 %", "blinds", "#2f6fb0"),
    KeyVisual("Kino", "", "movie-open", "#6a4a9c"),
    KeyVisual("Gute Nacht", "", "weather-night", "#2c4a6e"),
    KeyVisual("Wohnen", "21,5 °C", "thermometer", "#2b2b2b"),
    KeyVisual("Musik", "Pausiert", "play-pause", "#1e6b52"),
    KeyVisual("Haustür", "Verriegelt", "lock", "#2b2b2b"),
    KeyVisual("Licht OG", "", "folder", "#3a3a3a"),
    KeyVisual("Zurück", "", "arrow-left", "#3a3a3a"),
    KeyVisual("Ein sehr langer Titel", "noch längerer Status", "lightbulb", "#2b2b2b"),
    KeyVisual("Nur Text", "", None, "#0277bd"),
    KeyVisual("", "", "power", "#b3261e"),
    KeyVisual("Küche", "nicht verfügbar", "lightbulb", "#3a3a3a", "#9aa3ad"),
    KeyVisual(),
]


def main(out: str, size: int) -> None:
    gap = 8
    sheet = Image.new("RGB", (5 * size + 6 * gap, 3 * size + 4 * gap), (23, 24, 26))
    for i, visual in enumerate(SAMPLES):
        tile = Image.open(io.BytesIO(render_preview(size, visual)))
        sheet.paste(tile, (gap + (i % 5) * (size + gap), gap + (i // 5) * (size + gap)))
    sheet = sheet.resize((sheet.width * 3, sheet.height * 3), Image.Resampling.NEAREST)
    sheet.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 72)
