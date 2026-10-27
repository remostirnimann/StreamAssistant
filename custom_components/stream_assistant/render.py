"""Render key images with Pillow. Blocking, run in the executor."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import io
import json
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from .capabilities import DeckCapabilities

ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True, slots=True)
class KeyVisual:
    """Everything needed to draw one key. Hashable, used as render cache key."""

    title: str = ""
    subtitle: str = ""
    icon: str | None = None
    background: str = "#000000"
    foreground: str | None = None
    font_size: int | None = None
    image: str | None = None
    # 0..1 shown as a bar on touch strip segments (brightness, volume, position, ...)
    level: float | None = None


@cache
def _mdi_codepoints() -> dict[str, int]:
    return json.loads((ASSETS / "mdi.json").read_text(encoding="utf-8"))


@cache
def _icon_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "mdi.ttf"), size)


@cache
def _text_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(ASSETS / "Roboto-Medium.woff"), size)
    except OSError:
        # FreeType without WOFF support: Pillow's built-in font (no umlauts)
        return ImageFont.load_default(size=size)


def icon_exists(name: str) -> bool:
    """Return True if an MDI icon name (without 'mdi:') is known."""
    return name in _mdi_codepoints()


def _contrast(background: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = (c / 255 for c in background)
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (26, 26, 26) if luminance > 0.55 else (242, 242, 242)


def _fit_text(
    draw: ImageDraw.ImageDraw, text: str, size: int, max_width: int
) -> tuple[str, ImageFont.ImageFont | ImageFont.FreeTypeFont]:
    """Shrink the font until the text fits, then cut it with an ellipsis."""
    for font_size in range(size, max(7, size - 6) - 1, -1):
        font = _text_font(font_size)
        if draw.textlength(text, font=font) <= max_width:
            return text, font
    font = _text_font(max(7, size - 6))
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…", font


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def render_key(caps: DeckCapabilities, visual: KeyVisual) -> bytes:
    """Return an image ready to send to a deck with these capabilities."""
    image = _draw(caps.key_size, visual)
    if caps.rotation:
        # PIL rotates counter-clockwise; the deck needs the image turned by `rotation`
        image = image.rotate(-caps.rotation, expand=True)
    return _jpeg(image)


def render_preview(size: int, visual: KeyVisual) -> bytes:
    """Upright JPEG for the editor, at the deck's key size."""
    return _jpeg(_draw(size, visual))


def render_segment(width: int, height: int, visual: KeyVisual) -> bytes:
    """Upright JPEG of a dial's part of the touch strip: icon, title, state and level."""
    background = ImageColor.getrgb(visual.background)
    image = Image.new("RGB", (width, height), background)
    foreground = ImageColor.getrgb(visual.foreground) if visual.foreground else _contrast(background)
    draw = ImageDraw.Draw(image)
    margin = max(4, height // 12)
    bar = max(4, height // 16) if visual.level is not None else 0
    content_height = height - (bar + margin if bar else 0)

    codepoint = _mdi_codepoints().get(visual.icon) if visual.icon else None
    left = margin
    if codepoint is not None:
        icon_size = round(content_height * 0.55)
        font = _icon_font(icon_size)
        glyph = chr(codepoint)
        box = draw.textbbox((0, 0), glyph, font=font)
        draw.text((left - box[0], (content_height - (box[3] - box[1])) / 2 - box[1]), glyph, font=font, fill=foreground)
        left += box[2] - box[0] + margin

    title_size = visual.font_size or max(10, round(height * 0.2))
    lines = []
    if visual.title:
        lines.append(_fit_text(draw, visual.title, title_size, width - left - margin))
    if visual.subtitle:
        lines.append(_fit_text(draw, visual.subtitle, max(9, round(title_size * 0.9)), width - left - margin))
    heights = [font.getbbox("Hg")[3] for _, font in lines]
    y = (content_height - sum(heights) - 3 * max(0, len(lines) - 1)) / 2
    for (text, font), line_height in zip(lines, heights, strict=False):
        draw.text((left, y), text, font=font, fill=foreground)
        y += line_height + 3

    if bar and visual.level is not None:
        top = height - margin - bar
        track = tuple((f + b * 2) // 3 for f, b in zip(foreground, background, strict=False))
        draw.rounded_rectangle((margin, top, width - margin, top + bar), radius=bar // 2, fill=track)
        filled = round((width - 2 * margin) * max(0.0, min(1.0, visual.level)))
        if filled > 0:
            draw.rounded_rectangle((margin, top, margin + filled, top + bar), radius=bar // 2, fill=foreground)
    return _jpeg(image)


def _draw(size: int, visual: KeyVisual) -> Image.Image:
    background = ImageColor.getrgb(visual.background)
    image = Image.new("RGB", (size, size), background)
    foreground = ImageColor.getrgb(visual.foreground) if visual.foreground else _contrast(background)
    draw = ImageDraw.Draw(image)

    if visual.image:
        path = Path(visual.image)
        if path.is_file():
            with Image.open(path) as source:
                picture = ImageOps.fit(source.convert("RGBA"), (size, size))
                image.paste(picture, (0, 0), picture)

    codepoint = _mdi_codepoints().get(visual.icon) if visual.icon else None
    margin = max(3, size // 18)
    title_size = visual.font_size or max(9, round(size * 0.16))
    sub_size = max(8, round(title_size * 0.82))
    lines: list[tuple[str, ImageFont.ImageFont | ImageFont.FreeTypeFont]] = []
    if visual.title:
        lines.append(_fit_text(draw, visual.title, title_size, size - 2 * margin))
    if visual.subtitle:
        lines.append(_fit_text(draw, visual.subtitle, sub_size, size - 2 * margin))

    line_heights = [font.getbbox("Hg")[3] for _, font in lines]
    text_height = sum(line_heights) + max(0, len(lines) - 1) * 2

    if codepoint is not None:
        icon_size = round(size * (0.42 if lines else 0.6))
        font = _icon_font(icon_size)
        glyph = chr(codepoint)
        box = draw.textbbox((0, 0), glyph, font=font)
        glyph_w, glyph_h = box[2] - box[0], box[3] - box[1]
        block = glyph_h + (4 + text_height if lines else 0)
        top = (size - block) / 2
        draw.text(((size - glyph_w) / 2 - box[0], top - box[1]), glyph, font=font, fill=foreground)
        y = top + glyph_h + 4
    else:
        y = (size - text_height) / 2

    for (text, font), height in zip(lines, line_heights, strict=False):
        width = draw.textlength(text, font=font)
        draw.text(((size - width) / 2, y), text, font=font, fill=foreground)
        y += height + 2

    return image
