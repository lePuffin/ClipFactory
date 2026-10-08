"""Evidence-bound editorial graphics, separate from spoken-word captions."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True, slots=True)
class EditorialCue:
    kind: Literal["headline", "person", "place", "source", "quote", "number"]
    text: str
    start_seconds: float
    end_seconds: float
    claim_ids: tuple[UUID, ...] = ()
    source_ids: tuple[UUID, ...] = ()
    asset_id: UUID | None = None
    secondary: str = ""
    placement: Literal["top", "context"] = "top"


@dataclass(frozen=True, slots=True)
class EditorialGraphic:
    png_bytes: bytes
    sha256: str
    width: int
    height: int
    x: int
    y: int


def render_editorial_graphic(
    cue: EditorialCue,
    *,
    font_file: Path,
    accepted_claim_ids: frozenset[UUID],
    known_source_ids: frozenset[UUID],
    verified_identities: dict[UUID, frozenset[str]] | None = None,
    width: int = 720,
    height: int = 1280,
    min_dwell_seconds: float = 2,
    reading_words_per_second: float = 3,
) -> EditorialGraphic:
    if not cue.text.strip() or cue.start_seconds < 0 or cue.end_seconds <= cue.start_seconds:
        raise ValueError("editorial cue text and timing are invalid")
    if not set(cue.claim_ids) <= accepted_claim_ids or not set(cue.source_ids) <= known_source_ids:
        raise ValueError("editorial cue cites unknown evidence")
    if cue.kind == "source":
        if not cue.source_ids:
            raise ValueError("Source label requires Source evidence")
    elif not cue.claim_ids:
        raise ValueError("factual editorial cue requires accepted Claims")
    if cue.kind == "person":
        names = (verified_identities or {}).get(cue.asset_id, frozenset()) if cue.asset_id else frozenset()
        if cue.text.casefold() not in {name.casefold() for name in names}:
            raise ValueError("person label requires verified identity for the displayed Asset")
    readable = max(min_dwell_seconds, len((cue.text + " " + cue.secondary).split()) / reading_words_per_second)
    if cue.end_seconds - cue.start_seconds - 0.4 < readable:
        raise ValueError("editorial cue has insufficient readable dwell")
    scale = width / 720
    panel_width = round(536 * scale)
    margin = round(44 * scale)
    padding = round(24 * scale)
    size = round((46 if cue.kind == "headline" else 32) * scale)
    font = ImageFont.truetype(str(font_file), size)
    secondary_font = ImageFont.truetype(str(font_file), round(22 * scale))
    lines: list[str] = []
    line = ""
    for word in cue.text.split():
        candidate = f"{line} {word}".strip()
        if font.getlength(candidate) > panel_width - 2 * padding:
            if not line or font.getlength(word) > panel_width - 2 * padding:
                raise ValueError("editorial label contains a token too wide for safe placement")
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > 3 or secondary_font.getlength(cue.secondary) > panel_width - 2 * padding:
        raise ValueError("editorial label cannot fit within safe bounds")
    line_height = sum(font.getmetrics())
    panel_height = 2 * padding + len(lines) * line_height + (38 * scale if cue.secondary else 0)
    panel_height = round(panel_height)
    position_y = round((112 if cue.placement == "top" else 650) * height / 1280)
    if position_y + panel_height > round(height * 0.72):
        raise ValueError("editorial cue would enter the subtitle or platform control region")
    image = Image.new("RGBA", (panel_width, panel_height), (13, 17, 22, 238))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, round(6 * scale), panel_height), fill=(231, 51, 61, 255))
    for index, text in enumerate(lines):
        draw.text((padding, padding + index * line_height), text, font=font, fill="white", anchor="lt")
    if cue.secondary:
        draw.text(
            (padding, panel_height - padding), cue.secondary, font=secondary_font, fill=(197, 211, 219), anchor="lb"
        )
    output = io.BytesIO()
    image.save(output, format="PNG")
    content = output.getvalue()
    return EditorialGraphic(content, hashlib.sha256(content).hexdigest(), panel_width, panel_height, margin, position_y)
