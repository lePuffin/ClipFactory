import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.models.clip import ClipCandidate
from app.models.job import JobRecord
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.models.transcript import TranscriptSegment
from app.services.reel_narration import resolve_reel_tts_provider
from app.services.tts import resolve_tts_service


def test_timestamped_models_reject_reversed_ranges() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(start=10, end=10, text="Not valid")

    with pytest.raises(ValidationError):
        ClipCandidate(start=20, end=10, score=80, title="Invalid", reason="Invalid range")


def test_clip_jobs_accept_normalized_video_and_article_sources() -> None:
    video = Source(
        id="video-01",
        type=ClipSourceType.VIDEO,
        origin=ClipSourceOrigin.YOUTUBE,
        name="Source video",
        reference="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    article = Source(
        id="article-01",
        type=ClipSourceType.ARTICLE,
        origin=ClipSourceOrigin.ARTICLE_TEXT,
        name="Pasted article",
        reference="A sufficiently long article reference for a local clip job.",
    )
    job = JobRecord(
        id="clip-job",
        job_type="clip",
        source_type="clip",
        source_name="Two-source news clip",
        sources=[video, article],
    )

    assert job.is_clip()
    assert job.sources == [video, article]
    assert not JobRecord(
        id="clip-job",
        source_type="upload",
        source_name="source.mp4",
    ).is_clip()

    with pytest.raises(ValidationError):
        Source(
            id="invalid-source",
            type=ClipSourceType.VIDEO,
            origin=ClipSourceOrigin.ARTICLE_TEXT,
            name="Invalid",
            reference="Some text",
        )
    with pytest.raises(ValidationError):
        JobRecord(
            id="duplicate-source-job",
            job_type="clip",
            source_type="clip",
            source_name="Invalid clip",
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
    assert settings.llm_rate_limit_retries == 3
    assert settings.llm_rate_limit_max_wait_seconds == 60
    assert settings.llm_script_max_tokens == 8_000
    assert settings.whisper_compute_type == "default"
    assert settings.output_width == 1080
    assert settings.output_height == 1920
    assert settings.clip_min_duration_seconds == 30
    assert settings.clip_max_duration_seconds == 300
    assert settings.reel_min_duration_seconds == 20
    assert settings.reel_max_duration_seconds == 60
    assert settings.reel_words_per_minute == 155
    assert sum(settings.editorial_score_weights.values()) == 1
    assert settings.tts_rate == 175
    assert not settings.tts_fallback_enabled
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
        Settings(_env_file=None, tts_speed=1.3)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_rate_limit_retries=-1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_rate_limit_max_wait_seconds=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_script_max_tokens=511)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tts_audio_sample_rate=6_000)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, clip_min_duration_seconds=300, clip_max_duration_seconds=300)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, reel_min_duration_seconds=60, reel_max_duration_seconds=60)
    with pytest.raises(ValidationError, match="editorial score weight"):
        Settings(
            _env_file=None,
            editorial_importance_weight=0,
            editorial_novelty_weight=0,
            editorial_audience_interest_weight=0,
            editorial_clarity_weight=0,
            editorial_storytelling_potential_weight=0,
            editorial_factual_support_weight=0,
            editorial_visual_potential_weight=0,
            editorial_source_coverage_weight=0,
        )


def test_chatterbox_turbo_config_and_backend_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TTS_BACKEND", "chatterbox")
    monkeypatch.setenv("TTS_MODEL", "turbo")
    monkeypatch.setenv("TTS_LANGUAGE", "en")

    settings = Settings(_env_file=None)

    assert settings.tts_backend == "chatterbox"
    assert settings.tts_model == "turbo"
    assert settings.tts_language == "en"
    assert not settings.tts_fallback_enabled

    service = resolve_tts_service(settings)
    assert service.__class__.__name__ == "ChatterboxTTSService"


def test_reel_tts_provider_selection_uses_the_explicit_provider() -> None:
    pyttsx3 = resolve_reel_tts_provider(Settings(_env_file=None, tts_provider="pyttsx3"))
    chatterbox = resolve_reel_tts_provider(Settings(_env_file=None, tts_provider="chatterbox"))

    assert pyttsx3.__class__.__name__ == "Pyttsx3TTSProvider"
    assert chatterbox.__class__.__name__ == "ChatterboxTTSProvider"
