"""Deterministic data-only description of one Clip render."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

MediaType = Literal["image", "video"]
Motion = Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns"]
Transition = Literal["cut", "crossfade", "fade_black", "slide_left", "slide_up"]


@dataclass(frozen=True, slots=True)
class VisualInput:
    path: Path
    media_type: MediaType
    width: int
    height: int
    duration_seconds: float
    motion: Motion = "none"
    transition_in: Transition = "cut"
    source_label: Literal["ARCHIVE", "ILLUSTRATIVE", "FILE"] | None = None


@dataclass(frozen=True, slots=True)
class OverlayInput:
    path: Path
    start_seconds: float
    end_seconds: float
    x: int
    y: int
    width: int
    height: int
    fade_seconds: float = 0.2


@dataclass(frozen=True, slots=True)
class AudioInput:
    path: Path
    start_seconds: float
    duration_seconds: float
    gain_db: float = -24
    fade_seconds: float = 0.15


@dataclass(frozen=True, slots=True)
class CompositionSpec:
    segments: tuple[VisualInput, ...]
    narration_path: Path
    caption_file: Path
    output_path: Path
    narration_duration_seconds: float
    music_path: Path | None = None
    narration_word_spans: tuple[tuple[float, float], ...] = ()
    width: int = 720
    height: int = 1280
    fps: int = 30
    lead_in_seconds: float = 0.3
    tail_seconds: float = 1.0
    transition_seconds: float = 0.4
    narration_loudness_lufs: float = -14
    video_codec: str = "libx264"
    crf: int = 23
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    audio_sample_rate: int = 48000
    music_ducked_level_db: float = -20
    music_unducked_level_db: float = -12
    motion_intensity: Literal["low", "medium", "high"] = "medium"
    fonts_dir: Path | None = None
    overlays: tuple[OverlayInput, ...] = ()
    sound_effects: tuple[AudioInput, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return self.lead_in_seconds + self.narration_duration_seconds + self.tail_seconds

    def sha256(self) -> str:
        payload = json.dumps(_json_value(asdict(self)), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
