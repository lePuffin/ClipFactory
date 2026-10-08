"""Provider-neutral text-to-speech contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    segments: tuple[str, ...]
    language: str
    voice_id: str
    speaking_rate: float


@dataclass(frozen=True, slots=True)
class SynthesizedSpeech:
    wav_bytes: bytes
    character_count: int
    provider: str
    voice_id: str


class TTSProvider(Protocol):
    name: str

    async def synthesize(self, request: SpeechRequest) -> SynthesizedSpeech: ...
