"""Runtime configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local application settings with OpenRouter as the default LLM endpoint."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "LLM_API_KEY"),
    )
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices("OPENROUTER_BASE_URL", "LLM_BASE_URL"),
    )
    llm_model: str = Field(
        default="openai/gpt-4o-mini",
        validation_alias=AliasChoices("LLM_MODEL", "OPENROUTER_MODEL"),
    )
    whisper_model: str = "small"
    whisper_device: Literal["auto", "cpu", "cuda"] = "auto"
    whisper_compute_type: str = "default"
    output_width: int = Field(default=1080, gt=0)
    output_height: int = Field(default=1920, gt=0)
    output_dir: Path = Path("./output")
    temp_dir: Path = Path("./temp")
    download_dir: Path = Path("./downloads")
    data_dir: Path = Path("./data")
    max_upload_size_bytes: int = 20 * 1024 * 1024 * 1024
    default_clip_count: int = 5
    min_clip_duration_seconds: int = 30
    max_clip_duration_seconds: int = 90
    reel_min_duration_seconds: int = Field(default=30, ge=15, le=600)
    reel_max_duration_seconds: int = Field(default=300, ge=30, le=600)
    tts_backend: Literal["pyttsx3", "chatterbox"] = Field(
        default="chatterbox",
        validation_alias=AliasChoices("TTS_BACKEND", "tts_backend"),
    )
    tts_model: str = Field(
        default="turbo",
        validation_alias=AliasChoices("TTS_MODEL", "tts_model"),
    )
    tts_language: str = Field(
        default="en",
        validation_alias=AliasChoices("TTS_LANGUAGE", "tts_language"),
    )
    tts_rate: int = Field(default=175, ge=100, le=300)
    tts_voice_id: str | None = Field(default=None, max_length=300)
    tts_sentence_pause_seconds: float = Field(default=0.15, ge=0, le=2)
    tts_force_cpu: bool = Field(
        default=False,
        validation_alias=AliasChoices("TTS_FORCE_CPU", "tts_force_cpu"),
    )
    smart_crop_enabled: bool = True
    smart_crop_detection_interval_seconds: float = Field(default=0.5, gt=0)
    smart_crop_detection_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    smart_crop_tracking_confidence_threshold: float = Field(default=0.5, ge=0, le=1)
    smart_crop_smoothing_strength: float = Field(default=0.35, gt=0, le=1)
    smart_crop_dead_zone_pixels: float = Field(default=32, ge=0)
    smart_crop_max_camera_speed_pixels_per_second: float = Field(default=480, gt=0)
    smart_crop_scene_change_threshold: float = Field(default=0.35, gt=0, le=1)
    smart_crop_tracking_grace_seconds: float = Field(default=1.5, ge=0)
    smart_crop_debug: bool = False

    @model_validator(mode="after")
    def validate_clip_limits(self) -> "Settings":
        if self.max_upload_size_bytes <= 0:
            raise ValueError("max_upload_size_bytes must be positive")
        if self.default_clip_count < 1:
            raise ValueError("default_clip_count must be at least one")
        if self.min_clip_duration_seconds >= self.max_clip_duration_seconds:
            raise ValueError("minimum clip duration must be less than maximum clip duration")
        if self.reel_min_duration_seconds >= self.reel_max_duration_seconds:
            raise ValueError("minimum reel duration must be less than maximum reel duration")
        if self.output_width * 16 != self.output_height * 9:
            raise ValueError("output dimensions must use a 9:16 aspect ratio")
        if self.output_width % 2 or self.output_height % 2:
            raise ValueError("output dimensions must be even for H.264 yuv420p rendering")
        return self

    @property
    def llm_is_configured(self) -> bool:
        return self.llm_api_key is not None and bool(self.llm_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
