"""Provider-neutral narration synthesis, caching, and timing for v0.5 reels."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import FFmpegError
from app.models.reel import (
    NarrationAudioSegment,
    NarrationMetadata,
    NarrationSegment,
    NarrationTimingPolicy,
    Scene,
    TTSOptions,
)
from app.models.script import ClipScript, ScriptSentence
from app.services.ffmpeg import FFmpegService
from app.services.tts import ChatterboxTTSService, Pyttsx3TTSService, TTSError

_ACRONYM = re.compile(r"\b[A-Z]{2,6}\b")


class TTSProvider(Protocol):
    """Provider boundary consumed by the reel narration service."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def speed_applied_by_provider(self) -> bool: ...

    @property
    def is_available(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def synthesize(self, text: str, destination: Path, options: TTSOptions) -> Path: ...


class Pyttsx3TTSProvider:
    """Provider adapter for the existing local system-speech backend."""

    provider_name = "pyttsx3"
    speed_applied_by_provider = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service: Pyttsx3TTSService | None = None

    @property
    def model_name(self) -> str:
        return self.settings.tts_model

    @property
    def is_available(self) -> bool:
        return self._get_service().is_available

    @property
    def unavailable_reason(self) -> str | None:
        return self._get_service().unavailable_reason

    def synthesize(self, text: str, destination: Path, options: TTSOptions) -> Path:
        self._validate_language(options.language)
        service = self._get_service(options)
        script = ClipScript(
            title="Reel narration",
            sentences=[ScriptSentence(text=text, duration_seconds=1)],
        )
        return service.synthesize(script, destination).path

    def _get_service(self, options: TTSOptions | None = None) -> Pyttsx3TTSService:
        if self._service is None:
            selected = options or _options_from_settings(self.settings)
            rate = round(self.settings.tts_rate * selected.speed)
            provider_settings = self.settings.model_copy(
                update={
                    "tts_language": selected.language,
                    "tts_rate": rate,
                    "tts_sentence_pause_seconds": 0,
                    "tts_voice_id": selected.voice,
                }
            )
            self._service = Pyttsx3TTSService.from_settings(provider_settings)
        return self._service

    def _validate_language(self, language: str) -> None:
        if language.casefold() not in {"en", "en-us", "en-gb"}:
            raise TTSError(
                "The configured pyttsx3 provider only supports its installed English voices"
            )


class ChatterboxTTSProvider:
    """Provider adapter for Chatterbox Turbo without implicit provider fallback."""

    provider_name = "chatterbox"
    speed_applied_by_provider = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service = ChatterboxTTSService(settings, fallback_enabled=False)

    @property
    def model_name(self) -> str:
        return self.settings.tts_model

    @property
    def is_available(self) -> bool:
        return self._service.is_available

    @property
    def unavailable_reason(self) -> str | None:
        return self._service.unavailable_reason

    def synthesize(self, text: str, destination: Path, options: TTSOptions) -> Path:
        if options.language.casefold() not in {"en", "en-us", "en-gb"}:
            raise TTSError("The configured Chatterbox Turbo provider currently supports English")
        if options.voice is not None:
            raise TTSError(
                "Chatterbox Turbo does not expose named voice selection in this provider"
            )
        script = ClipScript(
            title="Reel narration",
            sentences=[ScriptSentence(text=text, duration_seconds=1)],
        )
        return self._service.synthesize(script, destination).path


def resolve_reel_tts_provider(settings: Settings) -> TTSProvider:
    """Resolve only the configured provider; v0.5 never silently changes providers."""
    if settings.tts_provider == "chatterbox":
        return ChatterboxTTSProvider(settings)
    return Pyttsx3TTSProvider(settings)


def build_reel_narration_service(
    settings: Settings,
    ffmpeg: FFmpegService,
    cache_dir: Path,
) -> NarrationService:
    """Construct one job-scoped service for the supplied immutable narration settings."""
    return NarrationService(settings, resolve_reel_tts_provider(settings), ffmpeg, cache_dir)


class NarrationSegmenter:
    """Uses existing scene boundaries as stable, meaningful speech synthesis units."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def segment(self, scenes: Sequence[Scene]) -> tuple[NarrationSegment, ...]:
        if not scenes:
            raise TTSError("Narration requires at least one planned scene")
        segments: list[NarrationSegment] = []
        for index, scene in enumerate(scenes, start=1):
            segments.append(
                NarrationSegment(
                    id=f"narration_{index:02d}",
                    script_section_id=scene.script_section_id,
                    scene_id=scene.id,
                    order=index,
                    text=scene.narration,
                    tts_text=preprocess_for_tts(scene.narration),
                    evidence=scene.evidence,
                    pause_after=(
                        self.settings.tts_sentence_pause_seconds if index < len(scenes) else 0
                    ),
                )
            )
        return tuple(segments)


class NarrationService:
    """Generates, measures, caches, and assembles provider-neutral narration audio."""

    def __init__(
        self,
        settings: Settings,
        provider: TTSProvider,
        ffmpeg: FFmpegService,
        cache_dir: Path,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.ffmpeg = ffmpeg
        self.cache_dir = cache_dir

    def synthesize(
        self,
        segments: Sequence[NarrationSegment],
        workspace: Path,
        destination: Path,
    ) -> NarrationMetadata:
        """Create an ordered assembled WAV and retain measured per-scene audio timing."""
        if not segments:
            raise TTSError("Narration requires at least one segment")
        _validate_segment_order(segments)
        options = _options_from_settings(self.settings)
        segment_directory = workspace / "narration-segments"
        raw_directory = workspace / "narration-raw"
        segment_directory.mkdir(parents=True, exist_ok=True)
        raw_directory.mkdir(parents=True, exist_ok=True)
        audio_paths: list[Path] = []
        audio_segments: list[NarrationAudioSegment] = []
        cursor = 0.0
        provider_checked = False
        try:
            for segment in segments:
                cache_key = narration_cache_key(
                    self.provider.provider_name,
                    self.provider.model_name,
                    options,
                    segment.tts_text,
                    self.settings.tts_audio_sample_rate,
                )
                segment_path = segment_directory / f"{segment.id}.wav"
                cached = self._restore_cached_audio(cache_key, segment_path)
                if not cached:
                    if not provider_checked:
                        self._require_provider()
                        provider_checked = True
                    raw_path = raw_directory / f"{segment.id}.wav"
                    self._generate_audio(segment, raw_path, segment_path, options)
                    self._cache_audio(cache_key, segment_path)
                duration = self._measure_audio(segment_path)
                start = cursor + segment.pause_before
                end = start + duration
                audio_paths.append(segment_path)
                audio_segments.append(
                    NarrationAudioSegment(
                        id=segment.id,
                        script_section_id=segment.script_section_id,
                        scene_id=segment.scene_id,
                        order=segment.order,
                        text=segment.text,
                        tts_text=segment.tts_text,
                        evidence=segment.evidence,
                        cache_key=cache_key,
                        cached=cached,
                        duration=duration,
                        start=start,
                        end=end,
                        pause_after=segment.pause_after,
                    )
                )
                cursor = end + segment.pause_after
            self.ffmpeg.assemble_narration_audio(
                audio_paths,
                [segment.pause_after for segment in segments],
                destination,
                self.settings.tts_audio_sample_rate,
            )
            measured_duration = self._measure_audio(destination)
            if abs(measured_duration - cursor) > 0.05:
                raise TTSError("Assembled narration duration does not match its segment timeline")
            return NarrationMetadata(
                provider=self.provider.provider_name,
                model=self.provider.model_name,
                options=options,
                timing_policy=NarrationTimingPolicy(self.settings.tts_timing_policy),
                narration_volume=self.settings.tts_narration_volume,
                source_audio_enabled=self.settings.tts_source_audio_enabled,
                source_audio_volume=self.settings.tts_source_audio_volume,
                ducking_enabled=self.settings.tts_ducking_enabled,
                sample_rate=self.settings.tts_audio_sample_rate,
                duration=measured_duration,
                segments=audio_segments,
            )
        except FFmpegError as error:
            destination.unlink(missing_ok=True)
            raise TTSError(f"Narration audio processing failed: {error}") from error
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(raw_directory, ignore_errors=True)
            shutil.rmtree(segment_directory, ignore_errors=True)

    def _restore_cached_audio(self, cache_key: str, destination: Path) -> bool:
        if not self.settings.tts_cache_enabled:
            return False
        cache_path = self.cache_dir / f"{cache_key}.wav"
        if not cache_path.is_file():
            return False
        try:
            self._measure_audio(cache_path)
        except TTSError:
            cache_path.unlink(missing_ok=True)
            return False
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_path, destination)
        return True

    def _generate_audio(
        self,
        segment: NarrationSegment,
        raw_path: Path,
        destination: Path,
        options: TTSOptions,
    ) -> None:
        produced = self.provider.synthesize(segment.tts_text, raw_path, options)
        if produced != raw_path or not raw_path.is_file() or raw_path.stat().st_size == 0:
            raise TTSError("The configured TTS provider did not produce the requested audio file")
        speed = 1.0 if self.provider.speed_applied_by_provider else options.speed
        self.ffmpeg.normalize_audio(
            raw_path,
            destination,
            self.settings.tts_audio_sample_rate,
            speed,
        )
        if not destination.is_file() or destination.stat().st_size == 0:
            raise TTSError("Narration audio normalization did not produce a WAV file")

    def _cache_audio(self, cache_key: str, source_path: Path) -> None:
        if not self.settings.tts_cache_enabled:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_dir / f"{cache_key}.wav"
        temporary_path = cache_path.with_suffix(".tmp")
        shutil.copy2(source_path, temporary_path)
        temporary_path.replace(cache_path)

    def _measure_audio(self, path: Path) -> float:
        if not path.is_file() or path.stat().st_size == 0:
            raise TTSError("Narration audio file is unavailable")
        try:
            return self.ffmpeg.probe_audio_duration(path)
        except FFmpegError as error:
            raise TTSError(f"Could not measure generated narration audio: {error}") from error

    def _require_provider(self) -> None:
        if not self.provider.is_available:
            reason = self.provider.unavailable_reason or "unknown provider error"
            raise TTSError(
                f"Configured TTS provider '{self.provider.provider_name}' is unavailable: {reason}"
            )


def reconcile_scene_timing(
    scenes: Sequence[Scene], narration: NarrationMetadata
) -> tuple[Scene, ...]:
    """Extend each scene to the measured narration interval without truncating speech."""
    if narration.timing_policy is not NarrationTimingPolicy.EXTEND_SCENE:
        raise TTSError("The configured narration timing policy is unsupported")
    by_scene = {segment.scene_id: segment for segment in narration.segments}
    if len(by_scene) != len(narration.segments) or set(by_scene) != {scene.id for scene in scenes}:
        raise TTSError("Narration segments must map one-to-one with planned scenes")
    cursor = 0.0
    reconciled: list[Scene] = []
    for scene in scenes:
        segment = by_scene[scene.id]
        duration = segment.duration + segment.pause_after
        if duration <= 0:
            raise TTSError("Measured narration duration must be positive")
        reconciled.append(
            scene.model_copy(
                update={
                    "start": cursor,
                    "duration": duration,
                    "narration_segment_ids": [segment.id],
                }
            )
        )
        cursor += duration
    if abs(cursor - narration.duration) > 0.05:
        raise TTSError("Reconciled scene timing does not match narration duration")
    return tuple(reconciled)


def assign_scene_starts(scenes: Sequence[Scene]) -> tuple[Scene, ...]:
    """Populate an inspectable sequential timeline for a silent reel as well."""
    cursor = 0.0
    timeline: list[Scene] = []
    for scene in scenes:
        timeline.append(scene.model_copy(update={"start": cursor}))
        cursor += scene.duration
    return tuple(timeline)


def narration_cache_key(
    provider: str,
    model: str,
    options: TTSOptions,
    text: str,
    sample_rate: int,
) -> str:
    """Hash every input that can affect normalized generated speech."""
    payload = {
        "format_version": 1,
        "provider": provider,
        "model": model,
        "options": options.model_dump(mode="json"),
        "text": text,
        "sample_rate": sample_rate,
    }
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def preprocess_for_tts(text: str) -> str:
    """Make isolated uppercase acronyms speakable without altering stored script text."""
    normalized = " ".join(text.split())
    return _ACRONYM.sub(lambda match: " ".join(match.group()), normalized)


def _options_from_settings(settings: Settings) -> TTSOptions:
    return TTSOptions(
        voice=settings.tts_voice_id,
        language=settings.tts_language,
        speed=settings.tts_speed,
    )


def _validate_segment_order(segments: Sequence[NarrationSegment]) -> None:
    identifiers = [segment.id for segment in segments]
    if len(identifiers) != len(set(identifiers)):
        raise TTSError("Narration segments contain duplicate identifiers")
    expected_order = list(range(1, len(segments) + 1))
    if [segment.order for segment in segments] != expected_order:
        raise TTSError("Narration segments must use consecutive scene order")