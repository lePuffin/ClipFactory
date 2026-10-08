"""Local faster-whisper adapter with model execution off the asyncio loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.transcription import RecognizedWord, Transcript

logger = logging.getLogger(__name__)


class WhisperLocalTranscriptionProvider:
    name = "whisper_local"

    def __init__(
        self,
        settings: EnvironmentSettings,
        *,
        model_factory: Callable[..., Any] = WhisperModel,
    ) -> None:
        self.settings = settings
        self.model_factory = model_factory
        self._model: Any | None = None
        self._model_key: tuple[str, str, str] | None = None

    async def transcribe(self, audio_path: Path, language: str) -> Transcript:
        path = await asyncio.to_thread(lambda: audio_path.expanduser().resolve(strict=True))
        return await asyncio.to_thread(self._transcribe_sync, path, language)

    def _transcribe_sync(self, audio_path: Path, language: str) -> Transcript:
        key = (self.settings.whisper_model, self.settings.whisper_device, self.settings.whisper_compute_type)
        model = self._model if self._model_key == key else None
        try:
            if model is None:
                model = self.model_factory(key[0], device=key[1], compute_type=key[2])
                self._model = model
                self._model_key = key
            return self._transcribe_model(model, audio_path, language)
        except RuntimeError as exc:
            if key[1] != "auto" or not any(name in str(exc) for name in ("libcublas.so", "libcudnn.so")):
                raise
            logger.warning("Whisper automatic CUDA selection lacks runtime libraries; retrying on CPU/int8")
            self._model = self.model_factory(key[0], device="cpu", compute_type="int8")
            self._model_key = key
            return self._transcribe_model(self._model, audio_path, language)

    def _transcribe_model(self, model: Any, audio_path: Path, language: str) -> Transcript:
        segments, info = model.transcribe(str(audio_path), language=language, word_timestamps=True)
        words: list[RecognizedWord] = []
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        for segment in _iter_segments(segments):
            duration = max(duration, float(getattr(segment, "end", 0.0) or 0.0))
            for word in getattr(segment, "words", None) or []:
                start = max(0.0, float(getattr(word, "start", 0.0) or 0.0))
                end = max(start, float(getattr(word, "end", start) or start))
                text = str(getattr(word, "word", "")).strip()
                if text:
                    probability = getattr(word, "probability", None)
                    words.append(
                        RecognizedWord(
                            text=text,
                            start_seconds=start,
                            end_seconds=end,
                            confidence=float(probability) if probability is not None else None,
                        )
                    )
        if not words:
            raise ValueError("transcription returned no word timestamps")
        return Transcript(tuple(words), duration, str(getattr(info, "language", language) or language))


def _iter_segments(value: Iterable[Any]) -> Iterable[Any]:
    return value
