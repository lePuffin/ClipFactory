"""Opt-in acceptance coverage for a real configured local TTS provider."""

import os
import wave
from array import array
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.reel import EvidenceReference, NarrationSegment
from app.services.ffmpeg import FFmpegService
from app.services.reel_narration import (
    NarrationService,
    resolve_reel_tts_provider,
)


@pytest.mark.real_tts
@pytest.mark.skipif(
    os.environ.get("CLIPFACTORY_REAL_TTS") != "1",
    reason="Set CLIPFACTORY_REAL_TTS=1 to run against the configured local TTS provider",
)
def test_real_configured_tts_provider_generates_audible_wav(tmp_path: Path) -> None:
    settings = Settings()
    if not settings.tts_enabled:
        pytest.skip("TTS_ENABLED is false")
    provider = resolve_reel_tts_provider(settings)
    if not provider.is_available:
        pytest.fail(provider.unavailable_reason or "Configured TTS provider is unavailable")
    service = NarrationService(
        settings,
        provider,
        FFmpegService(),
        tmp_path / "tts-cache",
    )
    segment = NarrationSegment(
        id="narration_01",
        script_section_id="section_01",
        scene_id="scene_01",
        order=1,
        text="ClipFactory generated this narration for a real local voice check.",
        tts_text="ClipFactory generated this narration for a real local voice check.",
        evidence=[EvidenceReference(source_id="source-01", asset_id="asset-01")],
    )
    destination = tmp_path / "narration.wav"

    narration = service.synthesize([segment], tmp_path / "workspace", destination)

    assert narration.duration > 0.25
    assert destination.is_file()
    with wave.open(str(destination), "rb") as output:
        samples = array("h")
        samples.frombytes(output.readframes(output.getnframes()))
    assert any(samples)