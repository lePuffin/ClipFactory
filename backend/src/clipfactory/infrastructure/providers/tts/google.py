"""Google Cloud Chirp TTS adapter; SDK operations run outside the event loop."""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any, Protocol

from google.cloud import texttospeech

from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.tts import SpeechRequest, SynthesizedSpeech


class SpeechClient(Protocol):
    def synthesize_speech(self, *, request: Any) -> Any: ...


class GoogleTTSProvider:
    name = "google"
    _MAX_CHUNK_CHARACTERS = 4_500

    def __init__(self, settings: EnvironmentSettings, client: SpeechClient | None = None) -> None:
        self.settings = settings
        self.client = client

    async def synthesize(self, request: SpeechRequest) -> SynthesizedSpeech:
        if not request.segments or not any(segment.strip() for segment in request.segments):
            raise ValueError("speech request must contain non-empty text")
        if request.speaking_rate <= 0:
            raise ValueError("speaking rate must be positive")
        chunks = _split_text("\n".join(request.segments), self._MAX_CHUNK_CHARACTERS)
        audio = await asyncio.to_thread(self._synthesize_chunks, request, chunks)
        return SynthesizedSpeech(
            wav_bytes=audio,
            character_count=len("\n".join(request.segments).strip()),
            provider=self.name,
            voice_id=request.voice_id,
        )

    def _synthesize_chunks(self, request: SpeechRequest, chunks: list[str]) -> bytes:
        client = self.client or texttospeech.TextToSpeechClient()
        language = request.language
        voice_parts = request.voice_id.split("-", maxsplit=2)
        if "-" not in language and len(voice_parts) == 3 and voice_parts[0].casefold() == language.casefold():
            language = "-".join(voice_parts[:2])
        raw_pcm: list[bytes] = []
        params: tuple[int, int, int] | None = None
        for chunk in chunks:
            result = client.synthesize_speech(
                request={
                    "input": texttospeech.SynthesisInput(text=chunk),
                    "voice": texttospeech.VoiceSelectionParams(
                        language_code=language,
                        name=request.voice_id,
                    ),
                    "audio_config": texttospeech.AudioConfig(
                        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                        sample_rate_hertz=48_000,
                        speaking_rate=request.speaking_rate,
                    ),
                }
            )
            pcm, chunk_params = _read_pcm_wave(result.audio_content)
            if chunk_params != (1, 2, 48_000):
                raise ValueError("Google TTS returned audio outside the required mono 48 kHz PCM format")
            if params is not None and params != chunk_params:
                raise ValueError("Google TTS returned inconsistent WAV chunk formats")
            params = chunk_params
            raw_pcm.append(pcm)
        if params is None:
            raise ValueError("Google TTS returned no audio chunks")
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(params[0])
            wav_file.setsampwidth(params[1])
            wav_file.setframerate(params[2])
            wav_file.writeframes(b"".join(raw_pcm))
        return output.getvalue()


def _read_pcm_wave(audio_bytes: bytes) -> tuple[bytes, tuple[int, int, int]]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        params = (wav_file.getnchannels(), wav_file.getsampwidth(), wav_file.getframerate())
        return wav_file.readframes(wav_file.getnframes()), params


def _split_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        boundary = max(
            remaining.rfind(". ", 0, limit),
            remaining.rfind("? ", 0, limit),
            remaining.rfind("! ", 0, limit),
        )
        if boundary < limit // 2:
            boundary = remaining.rfind(" ", 0, limit)
        if boundary <= 0:
            boundary = limit
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return chunks
