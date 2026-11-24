"""Draw the Stream Assistant icons: SVG sources and the PNG and ICO files made from them.

- The integration's icon, a deck with four keys (one with a house) and a dial with its level
  ring, in `icon` for light surfaces and `dark_icon` for dark ones: `docs/images/icon.svg`,
  `docs/images/dark_icon.svg` and the brand images in `custom_components/stream_assistant/brand/`
  (256 and 512 px, see https://developers.home-assistant.io/docs/core/integration/brand_images).
- The bridge's icon, the same keys with a badge of two arrows: `docs/images/bridge_icon.svg`,
  `bridge/assets/bridge.ico` (program, installer; 16 and 24 px use a simpler drawing) and
  `bridge/assets/bridge.png` (window), and the add-on's `icon.png` and `logo.png` in
  `addon/stream_assistant_bridge/`.

Every icon is one list of shapes that both the SVG and the Pillow output draw. Needs Pillow:

    .venv/Scripts/python.exe scripts/make_brand.py
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BRAND = ROOT / "custom_components" / "stream_assistant" / "brand"
BRIDGE = ROOT / "bridge" / "assets"
ADDON = ROOT / "addon" / "stream_assistant_bridge"
DOCS = ROOT / "docs" / "images"

SIZE = 120  # drawing units; the images scale this square
SUPERSAMPLE = 4
ICO_SIMPLE = (16, 24)
ICO_FULL = (32, 48, 64, 128, 256)

CYAN = "#2EC4B6"
AMBER = "#F5A623"


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    r: float
    fill: str
    stroke: str | None = None
    width: float = 0


@dataclass(frozen=True)
class Polygon:
    points: tuple[tuple[float, float], ...]
    fill: str


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float
    fill: str
    stroke: str | None = None
    width: float = 0


@dataclass(frozen=True)
class Line:
    """A line with round ends."""

    x1: float
    y1: float
    x2: float
    y2: float
    colour: str
    width: float


@dataclass(frozen=True)
class Arc:
    """A circular arc with round ends; Pillow angles (degrees clockwise from three o'clock)."""

    cx: float
    cy: float
    r: float
    start: float
    end: float
    colour: str
    width: float


Shape = Rect | Polygon | Circle | Line | Arc


def house_key(x: float, y: float, size: float, body: str) -> list[Shape]:
    """A cyan key with a house on it, cut out in the body colour."""
    mid = x + size / 2
    return [
        Rect(x, y, size, size, size * 0.22, CYAN),
        Polygon(
            ((mid, y + size * 0.15), (mid - size * 0.43, y + size * 0.54), (mid + size * 0.43, y + size * 0.54)), body
        ),
        Rect(mid - size * 0.29, y + size * 0.54, size * 0.58, size * 0.32, 0, body),
    ]


def integration_icon(body: str, key: str, border: str | None = None) -> list[Shape]:
    """Deck with four keys and a dial; the level ring fills two thirds of its 270°."""
    shapes: list[Shape] = [
        Rect(1.5, 1.5, 117, 117, 22.5, body, border, 3) if border else Rect(0, 0, SIZE, SIZE, 24, body)
    ]
    shapes += [Rect(10, 29, 28, 28, 6, key), *house_key(44, 29, 28, body)]
    shapes += [Rect(10, 63, 28, 28, 6, key), Rect(44, 63, 28, 28, 6, key)]
    shapes += [
        Arc(95, 60, 17, 135, 405, key, 6),
        Arc(95, 60, 17, 135, 315, CYAN, 6),
        Circle(95, 60, 10, AMBER),
        Line(95, 60, 100, 55, body, 3),
    ]
    return shapes


BRIDGE_BODY = "#1F2A44"
BRIDGE_KEY = "#3A4A6B"


def bridge_icon(badge: str = AMBER) -> list[Shape]:
    """The integration's keys with a badge of two arrows: the connection."""
    b = BRIDGE_BODY
    return [
        Rect(0, 0, SIZE, SIZE, 24, b),
        Rect(12, 12, 32, 32, 7, BRIDGE_KEY),
        *house_key(50, 12, 32, b),
        Rect(12, 50, 32, 32, 7, BRIDGE_KEY),
        Rect(50, 50, 32, 32, 7, BRIDGE_KEY),
        Circle(90, 90, 25, badge, b, 5),
        Line(78, 83, 96, 83, b, 5),
        Polygon(((104, 83), (95, 76), (95, 90)), b),
        Line(102, 97, 84, 97, b, 5),
        Polygon(((76, 97), (85, 90), (85, 104)), b),
    ]


def bridge_icon_simple(badge: str = AMBER) -> list[Shape]:
    """The bridge's icon for 16 and 24 px: three lighter keys and the badge."""
    b = BRIDGE_BODY
    light = "#5B6F99"
    return [
        Rect(0, 0, SIZE, SIZE, 26, b),
        Rect(14, 14, 40, 40, 9, light),
        Rect(66, 14, 40, 40, 9, light),
        Rect(14, 66, 40, 40, 9, light),
        Circle(86, 86, 30, badge, b, 8),
    ]


def _n(value: float) -> str:
    return f"{value:g}"


def svg(shapes: list[Shape]) -> str:
    """The shapes as SVG."""
    parts = []
    for s in shapes:
        match s:
            case Rect():
                stroke = f' stroke="{s.stroke}" stroke-width="{_n(s.width)}"' if s.stroke else ""
                parts.append(
                    f'<rect x="{_n(s.x)}" y="{_n(s.y)}" width="{_n(s.w)}" height="{_n(s.h)}" '
                    f'rx="{_n(s.r)}" fill="{s.fill}"{stroke}/>'
                )
            case Polygon():
                points = " ".join(f"{_n(x)},{_n(y)}" for x, y in s.points)
                parts.append(f'<polygon points="{points}" fill="{s.fill}"/>')
            case Circle():
                stroke = f' stroke="{s.stroke}" stroke-width="{_n(s.width)}"' if s.stroke else ""
                parts.append(f'<circle cx="{_n(s.cx)}" cy="{_n(s.cy)}" r="{_n(s.r)}" fill="{s.fill}"{stroke}/>')
            case Line():
                parts.append(
                    f'<line x1="{_n(s.x1)}" y1="{_n(s.y1)}" x2="{_n(s.x2)}" y2="{_n(s.y2)}" '
                    f'stroke="{s.colour}" stroke-width="{_n(s.width)}" stroke-linecap="round"/>'
                )
            case Arc():

                def point(angle: float, a: Arc = s) -> str:
                    rad = math.radians(angle)
                    return f"{_n(round(a.cx + a.r * math.cos(rad), 3))} {_n(round(a.cy + a.r * math.sin(rad), 3))}"

                large = 1 if s.end - s.start > 180 else 0
                parts.append(
                    f'<path d="M{point(s.start)} A{_n(s.r)} {_n(s.r)} 0 {large} 1 {point(s.end)}" fill="none" '
                    f'stroke="{s.colour}" stroke-width="{_n(s.width)}" stroke-linecap="round"/>'
                )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}">{"".join(parts)}</svg>\n'


def png(shapes: list[Shape], pixels: int) -> Image.Image:
    """The shapes as a square image with transparent corners."""
    k = pixels * SUPERSAMPLE / SIZE
    image = Image.new("RGBA", (pixels * SUPERSAMPLE,) * 2, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(x: float, y: float, w: float, h: float) -> list[float]:
        return [x * k, y * k, (x + w) * k - 1, (y + h) * k - 1]

    def dot(x: float, y: float, d: float, colour: str) -> None:
        draw.ellipse(box(x - d / 2, y - d / 2, d, d), fill=colour)

    for s in shapes:
        match s:
            case Rect():
                if s.stroke:  # the stroke is centred on the outline, as in SVG
                    o = s.width / 2
                    draw.rounded_rectangle(
                        box(s.x - o, s.y - o, s.w + s.width, s.h + s.width), (s.r + o) * k, fill=s.stroke
                    )
                    draw.rounded_rectangle(
                        box(s.x + o, s.y + o, s.w - s.width, s.h - s.width), (s.r - o) * k, fill=s.fill
                    )
                elif s.r:
                    draw.rounded_rectangle(box(s.x, s.y, s.w, s.h), s.r * k, fill=s.fill)
                else:
                    draw.rectangle(box(s.x, s.y, s.w, s.h), fill=s.fill)
            case Polygon():
                draw.polygon([(x * k, y * k) for x, y in s.points], fill=s.fill)
            case Circle():
                if s.stroke:
                    dot(s.cx, s.cy, 2 * s.r + s.width, s.stroke)
                    dot(s.cx, s.cy, 2 * s.r - s.width, s.fill)
                else:
                    dot(s.cx, s.cy, 2 * s.r, s.fill)
            case Line():
                draw.line([(s.x1 * k, s.y1 * k), (s.x2 * k, s.y2 * k)], fill=s.colour, width=round(s.width * k))
                dot(s.x1, s.y1, s.width, s.colour)
                dot(s.x2, s.y2, s.width, s.colour)
            case Arc():
                outer = s.r + s.width / 2
                draw.arc(
                    box(s.cx - outer, s.cy - outer, 2 * outer, 2 * outer),
                    s.start,
                    s.end,
                    fill=s.colour,
                    width=round(s.width * k),
                )
                for angle in (s.start, s.end):
                    rad = math.radians(angle)
                    dot(s.cx + s.r * math.cos(rad), s.cy + s.r * math.sin(rad), s.width, s.colour)
    return image.resize((pixels, pixels), Image.Resampling.LANCZOS)


def main() -> None:
    """Write all icons."""
    BRAND.mkdir(exist_ok=True)
    BRIDGE.mkdir(exist_ok=True)
    for name, shapes in (
        ("icon", integration_icon("#1F2A44", "#3A4A6B")),
        ("dark_icon", integration_icon("#2C3E63", "#4B5F88", border="#5B6F99")),
    ):
        (DOCS / f"{name}.svg").write_text(svg(shapes), encoding="utf-8", newline="\n")
        png(shapes, 256).save(BRAND / f"{name}.png", optimize=True)
        png(shapes, 512).save(BRAND / f"{name}@2x.png", optimize=True)
        print(f"{name}: svg, 256, 512")

    full, simple = bridge_icon(), bridge_icon_simple()
    (DOCS / "bridge_icon.svg").write_text(svg(full), encoding="utf-8", newline="\n")
    png(full, 256).save(BRIDGE / "bridge.png", optimize=True)
    for name in ("icon.png", "logo.png"):
        png(full, 256).save(ADDON / name, optimize=True)
    images = [png(simple, p) for p in ICO_SIMPLE] + [png(full, p) for p in ICO_FULL]
    images[-1].save(
        BRIDGE / "bridge.ico",
        sizes=[(p, p) for p in ICO_SIMPLE + ICO_FULL],
        append_images=images[:-1],
    )
    print(f"bridge: svg, png, ico {ICO_SIMPLE + ICO_FULL}")


if __name__ == "__main__":
    main()
