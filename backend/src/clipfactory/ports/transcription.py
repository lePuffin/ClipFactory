"""Provider-neutral word-level transcription contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RecognizedWord:
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    words: tuple[RecognizedWord, ...]
    duration_seconds: float
    language: str


class TranscriptionProvider(Protocol):
    name: str

    async def transcribe(self, audio_path: Path, language: str) -> Transcript: ...
