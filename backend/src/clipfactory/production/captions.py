"""Pixel-measured caption cue layout and safe ASS serialization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import ImageFont

from clipfactory.production.alignment import AlignedWord


@dataclass(frozen=True, slots=True)
class CaptionCue:
    index: int
    start_seconds: float
    end_seconds: float
    lines: tuple[str, ...]
    x: int
    y: int
    width: int
    height: int
    font_size_px: int


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    cues: tuple[CaptionCue, ...]
    font_file: str
    output_width: int
    output_height: int
    font_family: str = "DejaVu Sans"


class CaptionLayoutError(ValueError):
    pass


class FontMetrics(Protocol):
    def getlength(self, text: str) -> float: ...

    def getmetrics(self) -> tuple[int, int]: ...


FontLoader = Callable[[str, int], FontMetrics]


def build_caption_track(
    words: tuple[AlignedWord, ...],
    *,
    font_file: Path,
    width: int = 720,
    height: int = 1280,
    font_size_px: int = 56,
    max_lines: int = 2,
    max_cue_seconds: float = 3.0,
    horizontal_margin_pct: float = 6,
    max_text_width_pct: float = 88,
    bottom_margin_pct: float = 10,
    box_padding_px: int = 12,
    font_loader: FontLoader = ImageFont.truetype,
) -> CaptionTrack:
    if not words or max_lines != 2 or font_size_px <= 0 or (max_cue_seconds <= 0):
        raise CaptionLayoutError("caption layout requires words and valid two-line cue settings")
    side_margin = round(width * horizontal_margin_pct / 100)
    max_text_width = min(round(width * max_text_width_pct / 100), width - 2 * side_margin - 2 * box_padding_px)
    bottom_margin = round(height * bottom_margin_pct / 100)
    scale = width / 720
    base_font_size = round(font_size_px * scale)
    font = font_loader(str(font_file), base_font_size)
    cues: list[CaptionCue] = []
    offset = 0
    while offset < len(words):
        chosen: list[AlignedWord] = []
        best_lines: tuple[str, ...] = ()
        current_size = base_font_size
        while offset + len(chosen) < len(words):
            candidate = [*chosen, words[offset + len(chosen)]]
            lines = _wrap(candidate, font, max_text_width)
            duration = candidate[-1].end_seconds - candidate[0].start_seconds
            if chosen and (len(lines) > max_lines or duration > max_cue_seconds):
                break
            if len(lines) > max_lines:
                current_size = round(base_font_size * 0.8)
                font = font_loader(str(font_file), current_size)
                lines = _wrap(candidate, font, max_text_width)
                if len(lines) > max_lines:
                    raise CaptionLayoutError(f"caption token too wide at word index {offset}")
            chosen = candidate
            best_lines = tuple(lines)
            if _ends_sentence(chosen[-1].text) and duration >= max_cue_seconds * 0.55:
                break
        text_width = max((round(font.getlength(line)) for line in best_lines), default=0)
        if text_width > max_text_width:
            current_size = round(base_font_size * 0.8)
            font = font_loader(str(font_file), current_size)
            best_lines = tuple(_wrap(chosen, font, max_text_width))
            text_width = max((round(font.getlength(line)) for line in best_lines), default=0)
            if text_width > max_text_width or len(best_lines) > max_lines:
                raise CaptionLayoutError(f"caption cue {len(cues)} exceeds safe text width")
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
        box_width = text_width + 2 * box_padding_px
        box_height = line_height * len(best_lines) + 2 * box_padding_px
        cue_x = (width - box_width) // 2
        cue_y = height - bottom_margin - box_height
        if cue_x < side_margin or cue_x + box_width > width - side_margin or cue_y < 0:
            raise CaptionLayoutError(f"caption cue {len(cues)} is outside the safe area")
        cues.append(
            CaptionCue(
                len(cues),
                chosen[0].start_seconds,
                chosen[-1].end_seconds,
                best_lines,
                cue_x,
                cue_y,
                box_width,
                box_height,
                current_size,
            )
        )
        offset += len(chosen)
        font = font_loader(str(font_file), base_font_size)
    family = getattr(font, "getname", lambda: ("DejaVu Sans", "Bold"))()[0]
    return CaptionTrack(tuple(cues), str(font_file), width, height, str(family))


def render_ass(track: CaptionTrack) -> str:
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {track.output_width}",
        f"PlayResY: {track.output_height}",
        "[V4+ Styles]",
        "".join(
            [
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryCo",
                "lour, OutlineColour, BackColour, Bold, Italic, BorderStyle, ",
                "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encod",
                "ing",
            ]
        ),
        "".join(
            [
                "Style: Default,",
                f"{track.font_family.replace(',', ' ')}",
                ",56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,3,1,2,2",
                ",43,43,128,1",
            ]
        ),
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in track.cues:
        text = "\\N".join(_escape_ass(line) for line in cue.lines)
        position = "".join(
            [
                "{\\an2\\pos(",
                f"{track.output_width // 2}",
                ",",
                f"{cue.y + cue.height - 12}",
                ")\\fs",
                f"{cue.font_size_px}",
                "}",
            ]
        )
        header.append(
            "".join(
                [
                    "Dialogue: 0,",
                    f"{_ass_time(cue.start_seconds)}",
                    ",",
                    f"{_ass_time(cue.end_seconds)}",
                    ",Default,,0,0,0,,",
                    f"{position}",
                    f"{text}",
                ]
            )
        )
    return "\n".join(header) + "\n"


def _wrap(words: list[AlignedWord], font: FontMetrics, max_text_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word.text}".strip()
        if current and font.getlength(candidate) > max_text_width:
            lines.append(current)
            current = word.text
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _ends_sentence(text: str) -> bool:
    while text and text[-1] in "\"')]:;":
        text = text[:-1]
    return bool(text and text[-1] in ".!?")


def _escape_ass(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"
