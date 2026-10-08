"""Narration cache, transcription alignment, and caption artifact use case."""

from __future__ import annotations

import hashlib
import io
import json
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PIL import ImageFont

from clipfactory.ports.storage import MediaStorage
from clipfactory.ports.transcription import TranscriptionProvider
from clipfactory.ports.tts import SpeechRequest, TTSProvider
from clipfactory.production.alignment import AlignedWord, AlignmentResult, align_transcript
from clipfactory.production.captions import CaptionTrack, FontMetrics, build_caption_track, render_ass


@dataclass(frozen=True, slots=True)
class AudioCaptionResult:
    narration_key: str
    narration_sha256: str
    narration_duration_seconds: float
    caption_key: str
    alignment: AlignmentResult
    captions: CaptionTrack
    cached: bool


@dataclass(frozen=True, slots=True)
class NarrationResult:
    narration_key: str
    narration_sha256: str
    narration_duration_seconds: float
    cached: bool


async def generate_narration(
    *,
    script_segments: tuple[str, ...],
    language: str,
    voice_id: str,
    speaking_rate: float,
    min_seconds: float,
    max_seconds: float,
    lead_in_seconds: float,
    tail_seconds: float,
    speaking_words_per_minute: int,
    tts: TTSProvider,
    storage: MediaStorage,
    force_refresh: bool = False,
) -> NarrationResult:
    text = "\n".join(script_segments)
    cache_identity = json.dumps(
        {"provider": tts.name, "voice": voice_id, "rate": speaking_rate, "language": language, "text": text},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    cache_key = f"cache/tts/{hashlib.sha256(cache_identity).hexdigest()}.wav"
    cached = not force_refresh and await storage.exists(cache_key)
    if not cached:
        speech = await tts.synthesize(SpeechRequest(script_segments, language, voice_id, speaking_rate))
        await storage.put_bytes(cache_key, speech.wav_bytes)
    audio_bytes = await storage.read_bytes(cache_key)
    narration_duration = _wav_duration(audio_bytes)
    clip_duration = narration_duration + lead_in_seconds + tail_seconds
    if clip_duration < min_seconds or clip_duration > max_seconds:
        delta = min_seconds - clip_duration if clip_duration < min_seconds else clip_duration - max_seconds
        word_delta = 1 if clip_duration < min_seconds else -1
        raise NarrationDurationGateError(
            delta_seconds=delta, word_delta=word_delta, words_per_minute=speaking_words_per_minute
        )
    digest = hashlib.sha256(audio_bytes).hexdigest()
    narration_key = f"assets/narration/{digest}.wav"
    if not await storage.exists(narration_key):
        await storage.put_bytes(narration_key, audio_bytes)
    return NarrationResult(narration_key, digest, narration_duration, cached)


async def transcribe_narration(
    *,
    narration_key: str,
    script_segments: tuple[str, ...],
    language: str,
    transcription: TranscriptionProvider,
    storage: MediaStorage,
) -> AlignmentResult:
    transcript = await transcription.transcribe(storage.local_path(narration_key), language)
    return align_transcript(script_segments, transcript)


async def build_captions(
    *,
    run_id: UUID,
    attempt: int,
    alignment: AlignmentResult,
    storage: MediaStorage,
    font_file: Path,
    font_loader: Callable[[str, int], FontMetrics] = ImageFont.truetype,
    lead_in_seconds: float = 0,
) -> tuple[str, CaptionTrack]:
    shifted = tuple(
        AlignedWord(
            word.text,
            word.start_seconds + lead_in_seconds,
            word.end_seconds + lead_in_seconds,
            word.script_segment_index,
        )
        for word in alignment.words
    )
    captions = build_caption_track(shifted, font_file=font_file, font_loader=font_loader)
    caption_key = f"work/{run_id}/attempt-{attempt}/captions.ass"
    await storage.put_bytes(caption_key, render_ass(captions).encode("utf-8"))
    return (caption_key, captions)


async def produce_narration_and_captions(
    *,
    run_id: UUID,
    attempt: int,
    script_segments: tuple[str, ...],
    language: str,
    voice_id: str,
    speaking_rate: float,
    min_seconds: float,
    max_seconds: float,
    lead_in_seconds: float,
    tail_seconds: float,
    tts: TTSProvider,
    transcription: TranscriptionProvider,
    storage: MediaStorage,
    font_file: Path,
    speaking_words_per_minute: int,
    font_loader: Callable[[str, int], FontMetrics] = ImageFont.truetype,
) -> AudioCaptionResult:
    narration = await generate_narration(
        script_segments=script_segments,
        language=language,
        voice_id=voice_id,
        speaking_rate=speaking_rate,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        lead_in_seconds=lead_in_seconds,
        tail_seconds=tail_seconds,
        speaking_words_per_minute=speaking_words_per_minute,
        tts=tts,
        storage=storage,
    )
    alignment = await transcribe_narration(
        narration_key=narration.narration_key,
        script_segments=script_segments,
        language=language,
        transcription=transcription,
        storage=storage,
    )
    caption_key, captions = await build_captions(
        run_id=run_id,
        attempt=attempt,
        alignment=alignment,
        storage=storage,
        font_file=font_file,
        font_loader=font_loader,
    )
    return AudioCaptionResult(
        narration.narration_key,
        narration.narration_sha256,
        narration.narration_duration_seconds,
        caption_key,
        alignment,
        captions,
        narration.cached,
    )


class NarrationDurationGateError(ValueError):
    def __init__(self, *, delta_seconds: float, word_delta: int, words_per_minute: int) -> None:
        action_words = max(1, round(delta_seconds * words_per_minute / 60 + 0.999))
        direction = "add" if word_delta > 0 else "remove"
        super().__init__(
            "".join(
                [
                    "Narration duration is outside the profile range; ",
                    f"{direction}",
                    " at least ",
                    f"{action_words}",
                    " words",
                ]
            )
        )
        self.code = "narration_too_short" if word_delta > 0 else "narration_too_long"
        self.delta_seconds = delta_seconds
        self.word_delta = word_delta
        self.action_word_count = action_words


def _wav_duration(value: bytes) -> float:
    with wave.open(io.BytesIO(value), "rb") as wav_file:
        if wav_file.getframerate() <= 0:
            raise ValueError("narration WAV has an invalid sample rate")
        return wav_file.getnframes() / wav_file.getframerate()
