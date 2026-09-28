"""Metadata describing a source video stream."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    duration: float
    width: int
    height: int
    has_audio: bool