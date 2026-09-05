import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.clip import ClipCandidate
from app.models.job import JobRecord
from app.models.source import ReelSourceOrigin, ReelSourceType, Source
from app.models.transcript import TranscriptSegment
from app.services.tts import resolve_tts_service


def test_timestamped_models_reject_reversed_ranges() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(start=10, end=10, text="Not valid")

    with pytest.raises(ValidationError):
        ClipCandidate(start=20, end=10, score=80, title="Invalid", reason="Invalid range")


def test_reel_jobs_accept_normalized_video_and_article_sources() -> None:
    video = Source(
        id="video-01",
        type=ReelSourceType.VIDEO,
        origin=ReelSourceOrigin.YOUTUBE,
        name="Source video",
        reference="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    article = Source(
        id="article-01",
        type=ReelSourceType.ARTICLE,
        origin=ReelSourceOrigin.ARTICLE_TEXT,
        name="Pasted article",
        reference="A sufficiently long article reference for a local reel job.",
    )
    job = JobRecord(
        id="reel-job",
        job_type="reel",
        source_type="reel",
        source_name="Two-source news reel",
        sources=[video, article],
    )

    assert job.is_reel()
    assert job.sources == [video, article]
    assert not JobRecord(
        id="clip-job",
        source_type="upload",
        source_name="source.mp4",
    ).is_reel()

    with pytest.raises(ValidationError):
        Source(
            id="invalid-source",
            type=ReelSourceType.VIDEO,
            origin=ReelSourceOrigin.ARTICLE_TEXT,
            name="Invalid",
            reference="Some text",
        )
    with pytest.raises(ValidationError):
        JobRecord(
            id="duplicate-source-job",
            job_type="reel",
            source_type="reel",
            source_name="Invalid reel",
            sources=[article, article],
        )


def test_settings_accept_openrouter_alias_and_validate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WHISPER_COMPUTE_TYPE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-token")
    settings = Settings(_env_file=None)

    assert settings.llm_is_configured
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.whisper_compute_type == "default"
    assert settings.output_width == 1080
    assert settings.output_height == 1920
    assert settings.reel_min_duration_seconds == 30
    assert settings.reel_max_duration_seconds == 300
    assert settings.tts_rate == 175
    assert settings.smart_crop_detection_interval_seconds == 0.5
    assert settings.smart_crop_smoothing_strength == 0.35

    with pytest.raises(ValidationError):
        Settings(_env_file=None, min_clip_duration_seconds=90, max_clip_duration_seconds=30)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, smart_crop_max_camera_speed_pixels_per_second=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, output_width=1000, output_height=1920)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tts_rate=90)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, reel_min_duration_seconds=300, reel_max_duration_seconds=300)


def test_chatterbox_turbo_config_and_backend_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_BACKEND", "chatterbox")
    monkeypatch.setenv("TTS_MODEL", "turbo")
    monkeypatch.setenv("TTS_LANGUAGE", "en")

    settings = Settings(_env_file=None)

    assert settings.tts_backend == "chatterbox"
    assert settings.tts_model == "turbo"
    assert settings.tts_language == "en"

    service = resolve_tts_service(settings)
    assert service.__class__.__name__ == "ChatterboxTTSService"
