"""Timestamped transcription through faster-whisper with an automatic CPU fallback."""

import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ClipFactoryError
from app.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptionError(ClipFactoryError):
    """Raised when faster-whisper cannot return a usable transcription."""


class FasterWhisperTranscriber:
    """Loads faster-whisper lazily, so health checks and unit tests remain lightweight."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        try:
            segments, _ = self._get_model().transcribe(
                str(audio_path),
                beam_size=5,
                vad_filter=True,
                word_timestamps=False,
            )
            transcript = [
                TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
                for segment in segments
                if segment.text.strip() and segment.end > segment.start
            ]
        except Exception as error:
            raise TranscriptionError(f"Transcription failed: {error}") from error
        if not transcript:
            raise TranscriptionError("No speech was detected in the source video")
        return transcript

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.settings.whisper_model,
                device=self.settings.whisper_device,
                compute_type=self.settings.whisper_compute_type,
            )
            return self._model
        except Exception as error:
            logger.exception("Could not load faster-whisper model %s", self.settings.whisper_model)
            raise TranscriptionError(f"Could not load transcription model: {error}") from error
