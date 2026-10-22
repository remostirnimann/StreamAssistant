"""Render key images with Pillow. Blocking, run in the executor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import io
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from .protocol import DeckModel

DEFAULT_BACKGROUND = "#000000"
DEFAULT_TEXT_COLOR = "#ffffff"


@dataclass(slots=True)
class KeyAppearance:
    """What a key shows. Stored as a plain dict in the config storage."""

    text: str = ""
    background_color: str = DEFAULT_BACKGROUND
    text_color: str = DEFAULT_TEXT_COLOR
    font_size: int | None = None
    image: str | None = None

    def as_dict(self) -> dict:
        """Return a JSON serialisable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> KeyAppearance:
        """Create from a stored dict, ignoring unknown fields."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def render_key(model: DeckModel, appearance: KeyAppearance) -> bytes:
    """Return a JPEG ready to send to the given model."""
    size = model.key_size
    image = Image.new("RGB", (size, size), ImageColor.getrgb(appearance.background_color))

    if appearance.image:
        path = Path(appearance.image)
        if path.is_file():
            with Image.open(path) as source:
                picture = ImageOps.fit(source.convert("RGBA"), (size, size))
                image.paste(picture, (0, 0), picture)

    if appearance.text:
        draw = ImageDraw.Draw(image)
        font_size = appearance.font_size or max(10, size // 5)
        font = _font(font_size)
        box = draw.multiline_textbbox((0, 0), appearance.text, font=font, align="center")
        width, height = box[2] - box[0], box[3] - box[1]
        draw.multiline_text(
            ((size - width) / 2 - box[0], (size - height) / 2 - box[1]),
            appearance.text,
            font=font,
            fill=ImageColor.getrgb(appearance.text_color),
            align="center",
        )

    if model.rotate_180:
        image = image.transpose(Image.Transpose.ROTATE_180)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()
