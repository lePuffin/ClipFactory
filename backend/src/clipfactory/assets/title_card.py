"""Deterministic title-card image generation used when no visual Asset is available."""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True, slots=True)
class RenderedTitleCard:
    png_bytes: bytes
    sha256: str
    width: int
    height: int
    text: str


class FontMetrics(Protocol):
    def getlength(self, text: str) -> float: ...


def render_title_card(
    text: str,
    *,
    width: int = 720,
    height: int = 1280,
    background: str = "#152020",
    foreground: str = "#f3f5ef",
    accent: str = "#c7f36b",
    font_file: Path | None = None,
    background_image: Path | None = None,
) -> RenderedTitleCard:
    if width <= 0 or height <= 0 or width * 16 != height * 9:
        raise ValueError("title-card output must be positive 9:16 dimensions")
    normalized = " ".join(unicodedata.normalize("NFC", text).split())
    if not normalized:
        raise ValueError("title-card text must not be empty")
    image = (
        _photo_backdrop(background_image, width, height)
        if background_image
        else Image.new("RGB", (width, height), background)
    )
    draw = ImageDraw.Draw(image)
    margin = round(width * 0.09)
    font_size = round(width * (0.0625 if background_image else 0.075))
    font = ImageFont.truetype(str(font_file), font_size) if font_file else ImageFont.load_default(size=font_size)
    lines = _wrap(normalized, font, width - 2 * margin)
    line_height = round(font_size * 1.28)
    block_height = line_height * len(lines)
    # A photo keeps its subject visible above a text block that ends clear of the burned-in captions.
    start_y = round(height * 0.76) - block_height if background_image else (height - block_height) // 2
    draw.rectangle((margin, start_y - 28, margin + 52, start_y - 20), fill=accent)
    for index, line in enumerate(lines):
        draw.text(
            (margin, start_y + index * line_height),
            line,
            font=font,
            fill=foreground,
            stroke_width=2 if background_image else 0,
            stroke_fill="#000000",
        )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=9)
    value = output.getvalue()
    return RenderedTitleCard(value, hashlib.sha256(value).hexdigest(), width, height, normalized)


def _photo_backdrop(source: Path, width: int, height: int) -> Image.Image:
    with Image.open(source) as original:
        photo = original.convert("RGB")
    scale = max(width / photo.width, height / photo.height)
    photo = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.Resampling.LANCZOS)
    left = (photo.width - width) // 2
    photo = photo.crop((left, 0, left + width, height))
    shade = Image.new("L", (width, height))
    fade_start = round(height * 0.35)
    for y in range(height):
        depth = 0.0 if y < fade_start else (y - fade_start) / (height - fade_start)
        shade.paste(round(70 + 150 * depth), (0, y, width, y + 1))
    return Image.composite(Image.new("RGB", (width, height), "#000000"), photo, shade)


def _wrap(text: str, font: FontMetrics, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in re.findall(r"\S+", text):
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
