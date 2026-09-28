"""Narration synthesis with local pyttsx3 or Chatterbox Turbo backends."""

from __future__ import annotations

import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Self

import numpy as np

from app.core.config import Settings
from app.core.exceptions import ClipFactoryError
from app.models.script import ClipScript, NarrationTiming


class TTSError(ClipFactoryError):
    """Raised when the configured local speech engine cannot synthesize narration."""


@dataclass(frozen=True, slots=True)
class NarrationAudio:
    """The assembled local narration and its measured sentence boundaries."""

    path: Path
    duration: float
    timings: tuple[NarrationTiming, ...]


class TTSService(Protocol):
    """Synthesizes a validated narration script into a local WAV file."""

    @property
    def is_available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def synthesize(self, script: ClipScript, destination: Path) -> NarrationAudio: ...


class ChatterboxTTSService:
    """Uses Chatterbox Turbo, with an explicitly configured optional pyttsx3 fallback."""

    def __init__(self, settings: Settings, fallback_enabled: bool = False) -> None:
        self.settings = settings
        self.fallback_enabled = fallback_enabled
        self._model: Any | None = None
        self._availability_error: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(settings, fallback_enabled=settings.tts_fallback_enabled)

    @property
    def is_available(self) -> bool:
        try:
            self._get_model()
        except TTSError as error:
            self._availability_error = str(error)
            return False
        return True

    @property
    def unavailable_reason(self) -> str | None:
        if self.is_available:
            return None
        return self._availability_error

    def synthesize(self, script: ClipScript, destination: Path) -> NarrationAudio:
        try:
            model = self._get_model()
            destination.parent.mkdir(parents=True, exist_ok=True)
            segment_directory = destination.parent / "tts-segments"
            shutil.rmtree(segment_directory, ignore_errors=True)
            segment_directory.mkdir(parents=True, exist_ok=True)
            segment_paths = self._synthesize_sentences(model, script, segment_directory)
            narration = self._assemble_wav(segment_paths, destination)
            return narration
        except TTSError as error:
            if not self.fallback_enabled:
                destination.unlink(missing_ok=True)
                raise
            fallback = Pyttsx3TTSService.from_settings(self.settings)
            if fallback.is_available:
                return fallback.synthesize(script, destination)
            destination.unlink(missing_ok=True)
            raise TTSError(
                str(error) or fallback.unavailable_reason or "Chatterbox Turbo is unavailable"
            ) from error
        except Exception as error:
            if not self.fallback_enabled:
                destination.unlink(missing_ok=True)
                raise TTSError(f"Chatterbox narration synthesis failed: {error}") from error
            fallback = Pyttsx3TTSService.from_settings(self.settings)
            if fallback.is_available:
                return fallback.synthesize(script, destination)
            destination.unlink(missing_ok=True)
            raise TTSError(f"Chatterbox narration synthesis failed: {error}") from error
        finally:
            if (destination.parent / "tts-segments").exists():
                shutil.rmtree(destination.parent / "tts-segments", ignore_errors=True)

    @staticmethod
    def _patch_perth_watermarker_compatibility() -> None:
        import logging

        logger = logging.getLogger("app.services.tts")
        try:
            import perth
        except Exception:
            return

        if getattr(perth, "PerthImplicitWatermarker", None) is not None:
            return

        if hasattr(perth, "DummyWatermarker"):
            logger.warning(
                "TTS: Perth implicit watermarking is unavailable; using a dummy no-op "
                "watermarker compatibility shim."
            )
            perth.PerthImplicitWatermarker = perth.DummyWatermarker
            if "PerthImplicitWatermarker" not in getattr(perth, "__all__", []):
                perth.__all__.append("PerthImplicitWatermarker")
            return

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
            from chatterbox.tts_turbo import ChatterboxTurboTTS
        except Exception as error:
            raise TTSError(
                "Chatterbox Turbo is not available in this environment. Install the package "
                "and ensure the model can download successfully."
            ) from error

        try:
            import logging

            logger = logging.getLogger("app.services.tts")
            self._patch_perth_watermarker_compatibility()

            # Determine target device
            if self.settings.tts_force_cpu:
                device = "cpu"
                logger.info("TTS: Using CPU (forced by TTS_FORCE_CPU)")
            elif torch.cuda.is_available():
                device = "cuda"
                logger.info("TTS: CUDA available, attempting to load on GPU")
            else:
                device = "cpu"
                logger.info("TTS: CUDA not available, using CPU")

            # Attempt model load
            try:
                self._model = ChatterboxTurboTTS.from_pretrained(device=device)
                logger.info(f"TTS: Model loaded successfully on {device}")
                return self._model
            except RuntimeError as cuda_error:
                # CUDA device incompatibility or CUDA out of memory
                error_msg = str(cuda_error).lower()
                if device == "cuda" and (
                    "no kernel image is available" in error_msg
                    or "cuda" in error_msg
                    or "out of memory" in error_msg
                ):
                    logger.warning(
                        f"TTS: GPU initialization failed ({error_msg[:100]}), falling back to CPU"
                    )
                    device = "cpu"
                    self._model = ChatterboxTurboTTS.from_pretrained(device=device)
                    logger.info("TTS: Model loaded successfully on CPU fallback")
                    return self._model
                raise
        except Exception as error:
            raise TTSError(
                "Chatterbox Turbo could not initialize. Check the package installation and the "
                "available model download permissions."
            ) from error

    def _synthesize_sentences(
        self,
        model: Any,
        script: ClipScript,
        segment_directory: Path,
    ) -> tuple[Path, ...]:
        paths: list[Path] = []
        for index, sentence in enumerate(script.sentences):
            path = segment_directory / f"sentence-{index:03d}.wav"
            audio = model.generate(sentence.text)
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            waveform = np.asarray(audio).squeeze(0)
            if waveform.ndim == 0:
                raise TTSError("Chatterbox Turbo did not produce an audio waveform")
            sample_rate = int(getattr(model, "sr", 24000))
            pcm = np.clip(waveform, -1.0, 1.0)
            int16 = np.int16(pcm * 32767.0)
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(int16.tobytes())
            if not path.is_file() or path.stat().st_size == 0:
                raise TTSError("Chatterbox Turbo did not produce a WAV file")
            paths.append(path)
        return tuple(paths)

    def _assemble_wav(self, paths: tuple[Path, ...], destination: Path) -> NarrationAudio:
        if not paths:
            raise TTSError("The clip script does not contain narration sentences")
        reference_params: tuple[int, int, int, str, str] | None = None
        cursor = 0.0
        timings: list[NarrationTiming] = []
        with wave.open(str(destination), "wb") as output:
            for index, path in enumerate(paths):
                try:
                    with wave.open(str(path), "rb") as input_file:
                        params = (
                            input_file.getnchannels(),
                            input_file.getsampwidth(),
                            input_file.getframerate(),
                            input_file.getcomptype(),
                            input_file.getcompname(),
                        )
                        if reference_params is None:
                            reference_params = params
                            output.setparams(input_file.getparams())
                        elif params != reference_params:
                            raise TTSError("Chatterbox Turbo produced incompatible WAV segments")
                        frame_count = input_file.getnframes()
                        frame_rate = input_file.getframerate()
                        output.writeframes(input_file.readframes(frame_count))
                except wave.Error as error:
                    raise TTSError("Chatterbox Turbo produced an invalid WAV segment") from error

                spoken_duration = frame_count / frame_rate
                pause = self.settings.tts_sentence_pause_seconds if index < len(paths) - 1 else 0
                if pause:
                    output.writeframes(self._silence_frames(reference_params, pause))
                end = cursor + spoken_duration + pause
                timings.append(NarrationTiming(sentence_index=index, start=cursor, end=end))
                cursor = end
        return NarrationAudio(path=destination, duration=cursor, timings=tuple(timings))

    def _silence_frames(
        self,
        params: tuple[int, int, int, str, str] | None,
        duration: float,
    ) -> bytes:
        if params is None:
            raise TTSError("No Chatterbox audio parameters were available")
        channels, sample_width, frame_rate, _, _ = params
        frame_count = round(frame_rate * duration)
        silent_sample = b"\x80" if sample_width == 1 else b"\0"
        return silent_sample * frame_count * channels * sample_width


def resolve_tts_service(settings: Settings) -> TTSService:
    """Resolve the configured narration backend without silently downgrading the user choice."""
    if settings.tts_backend == "chatterbox":
        return ChatterboxTTSService.from_settings(settings)
    return Pyttsx3TTSService.from_settings(settings)


class Pyttsx3TTSService:
    """Uses the platform's local pyttsx3 backend, such as eSpeak-ng or Windows SAPI."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: Any | None = None
        self._availability_error: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(settings)

    @property
    def is_available(self) -> bool:
        try:
            self._get_engine()
        except TTSError as error:
            self._availability_error = str(error)
            return False
        return True

    @property
    def unavailable_reason(self) -> str | None:
        if self.is_available:
            return None
        return self._availability_error

    def synthesize(self, script: ClipScript, destination: Path) -> NarrationAudio:
        engine = self._get_engine()
        destination.parent.mkdir(parents=True, exist_ok=True)
        segment_directory = destination.parent / "tts-segments"
        shutil.rmtree(segment_directory, ignore_errors=True)
        segment_directory.mkdir(parents=True, exist_ok=True)
        try:
            self._configure_engine(engine)
            segment_paths = self._synthesize_sentences(engine, script, segment_directory)
            narration = self._assemble_wav(segment_paths, destination)
        except TTSError:
            destination.unlink(missing_ok=True)
            raise
        except Exception as error:
            destination.unlink(missing_ok=True)
            raise TTSError(f"Local narration synthesis failed: {error}") from error
        finally:
            shutil.rmtree(segment_directory, ignore_errors=True)
        return narration

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        try:
            import pyttsx3

            self._engine = pyttsx3.init()
            return self._engine
        except Exception as error:
            raise TTSError(
                "Local text-to-speech is unavailable. Install a supported system speech engine "
                "such as eSpeak-ng on Linux."
            ) from error

    def _configure_engine(self, engine: Any) -> None:
        engine.setProperty("rate", self.settings.tts_rate)
        if not self.settings.tts_voice_id:
            return
        voices = engine.getProperty("voices") or []
        matching_voice = next(
            (voice for voice in voices if getattr(voice, "id", None) == self.settings.tts_voice_id),
            None,
        )
        if matching_voice is None:
            raise TTSError("The configured local TTS voice was not found")
        engine.setProperty("voice", matching_voice.id)

    def _synthesize_sentences(
        self,
        engine: Any,
        script: ClipScript,
        segment_directory: Path,
    ) -> tuple[Path, ...]:
        paths: list[Path] = []
        for index, sentence in enumerate(script.sentences):
            path = segment_directory / f"sentence-{index:03d}.wav"
            engine.save_to_file(sentence.text, str(path))
            engine.runAndWait()
            if not path.is_file() or path.stat().st_size == 0:
                raise TTSError("The local TTS engine did not produce a WAV file")
            paths.append(path)
        return tuple(paths)

    def _assemble_wav(self, paths: tuple[Path, ...], destination: Path) -> NarrationAudio:
        if not paths:
            raise TTSError("The clip script does not contain narration sentences")
        reference_params: tuple[int, int, int, str, str] | None = None
        cursor = 0.0
        timings: list[NarrationTiming] = []
        with wave.open(str(destination), "wb") as output:
            for index, path in enumerate(paths):
                try:
                    with wave.open(str(path), "rb") as input_file:
                        params = (
                            input_file.getnchannels(),
                            input_file.getsampwidth(),
                            input_file.getframerate(),
                            input_file.getcomptype(),
                            input_file.getcompname(),
                        )
                        if reference_params is None:
                            reference_params = params
                            output.setparams(input_file.getparams())
                        elif params != reference_params:
                            raise TTSError(
                                "The local TTS engine produced incompatible WAV segments"
                            )
                        frame_count = input_file.getnframes()
                        frame_rate = input_file.getframerate()
                        output.writeframes(input_file.readframes(frame_count))
                except wave.Error as error:
                    raise TTSError(
                        "The local TTS engine produced an invalid WAV segment"
                    ) from error

                spoken_duration = frame_count / frame_rate
                pause = self.settings.tts_sentence_pause_seconds if index < len(paths) - 1 else 0
                if pause:
                    output.writeframes(self._silence_frames(reference_params, pause))
                end = cursor + spoken_duration + pause
                timings.append(NarrationTiming(sentence_index=index, start=cursor, end=end))
                cursor = end
        return NarrationAudio(path=destination, duration=cursor, timings=tuple(timings))

    def _silence_frames(
        self,
        params: tuple[int, int, int, str, str] | None,
        duration: float,
    ) -> bytes:
        if params is None:
            raise TTSError("No local TTS audio parameters were available")
        channels, sample_width, frame_rate, _, _ = params
        frame_count = round(frame_rate * duration)
        silent_sample = b"\x80" if sample_width == 1 else b"\0"
        return silent_sample * frame_count * channels * sample_width
