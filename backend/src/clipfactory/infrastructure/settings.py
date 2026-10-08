"""Validated process environment settings. Credentials are never serialized."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = Field(default="development", alias="APP_ENV")
    database_url: SecretStr = Field(default=SecretStr(""), alias="DATABASE_URL")
    dragonfly_url: SecretStr = Field(default=SecretStr("redis://127.0.0.1:6380/0"), alias="DRAGONFLY_URL")
    data_dir: Path = Field(default=Path("./data"), alias="DATA_DIR")
    public_media_dir: Path = Field(default=Path("./public-media"), alias="PUBLIC_MEDIA_DIR")
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, ge=1, le=65535, alias="PORT")
    api_token: SecretStr | None = Field(default=None, alias="API_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: Literal["json", "console"] | None = Field(default=None, alias="LOG_FORMAT")
    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    ffprobe_path: str = Field(default="ffprobe", alias="FFPROBE_PATH")
    node_path: str = Field(default="node", alias="NODE_PATH")
    hyperframes_package_dir: Path = Field(default=Path("./renderers/hyperframes"), alias="HYPERFRAMES_PACKAGE_DIR")
    hyperframes_path: Path | None = Field(default=None, alias="HYPERFRAMES_PATH")
    manim_path: str | None = Field(default=None, alias="MANIM_PATH")
    graphics_fps: int = Field(default=30, ge=1, le=60, alias="GRAPHICS_FPS")
    graphics_timeout_seconds: int = Field(default=180, ge=1, le=3600, alias="GRAPHICS_TIMEOUT_SECONDS")
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")

    llm_provider: str = Field(default="openai_compatible", alias="LLM_PROVIDER")
    news_sources: str = Field(default="rss", alias="NEWS_SOURCES")
    media_sources: str = Field(default="pexels,pixabay,unsplash,wikimedia_commons", alias="MEDIA_SOURCES")
    image_providers: str = Field(default="comfyui,higgsfield", alias="IMAGE_PROVIDERS")
    video_providers: str = Field(default="comfyui,wan_local,higgsfield", alias="VIDEO_PROVIDERS")
    tts_provider: str = Field(default="google", alias="TTS_PROVIDER")
    transcription_provider: str = Field(default="whisper_local", alias="TRANSCRIPTION_PROVIDER")
    publishers: str = Field(default="youtube,instagram,tiktok,facebook", alias="PUBLISHERS")
    storage_provider: Literal["local"] = Field(default="local", alias="STORAGE_PROVIDER")

    llm_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="LLM_BASE_URL")
    llm_api_key: SecretStr | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="google/gemma-4-31b-it:free", alias="LLM_MODEL")
    llm_model_evaluation: str | None = Field(default=None, alias="LLM_MODEL_EVALUATION")
    llm_request_timeout_seconds: int = Field(default=120, ge=1, le=600, alias="LLM_REQUEST_TIMEOUT_SECONDS")
    google_application_credentials: Path | None = Field(default=None, alias="GOOGLE_APPLICATION_CREDENTIALS")
    whisper_model: str = Field(default="large-v3-turbo", alias="WHISPER_MODEL")
    whisper_device: Literal["auto", "cpu", "cuda"] = Field(default="auto", alias="WHISPER_DEVICE")
    whisper_compute_type: str = Field(default="default", alias="WHISPER_COMPUTE_TYPE")

    pexels_api_key: SecretStr | None = Field(default=None, alias="PEXELS_API_KEY")
    pixabay_api_key: SecretStr | None = Field(default=None, alias="PIXABAY_API_KEY")
    unsplash_access_key: SecretStr | None = Field(default=None, alias="UNSPLASH_ACCESS_KEY")
    wikimedia_user_agent: str | None = Field(default=None, alias="WIKIMEDIA_USER_AGENT")
    comfyui_url: str = Field(default="http://127.0.0.1:8188", alias="COMFYUI_URL")
    comfyui_workflows_dir: Path | None = Field(default=None, alias="COMFYUI_WORKFLOWS_DIR")
    wan_model: str = Field(default="Wan-AI/Wan2.1-T2V-1.3B-Diffusers", alias="WAN_MODEL")
    wan_device: Literal["cuda", "cpu"] = Field(default="cuda", alias="WAN_DEVICE")
    wan_fps: int = Field(default=16, ge=1, le=60, alias="WAN_FPS")
    wan_inference_steps: int = Field(default=50, ge=1, le=100, alias="WAN_INFERENCE_STEPS")
    wan_max_generations_per_run: int = Field(default=2, ge=0, le=100, alias="WAN_MAX_GENERATIONS_PER_RUN")
    wan_model_license: str = Field(default="Apache-2.0", min_length=1, alias="WAN_MODEL_LICENSE")
    higgsfield_api_key: SecretStr | None = Field(default=None, alias="HIGGSFIELD_API_KEY")

    public_media_base_url: str | None = Field(default=None, alias="PUBLIC_MEDIA_BASE_URL")
    media_url_signing_key: SecretStr | None = Field(default=None, alias="MEDIA_URL_SIGNING_KEY")
    youtube_client_secrets_file: Path | None = Field(default=None, alias="YOUTUBE_CLIENT_SECRETS_FILE")
    instagram_access_token: SecretStr | None = Field(default=None, alias="INSTAGRAM_ACCESS_TOKEN")
    instagram_user_id: str | None = Field(default=None, alias="INSTAGRAM_USER_ID")
    tiktok_client_key: SecretStr | None = Field(default=None, alias="TIKTOK_CLIENT_KEY")
    tiktok_client_secret: SecretStr | None = Field(default=None, alias="TIKTOK_CLIENT_SECRET")
    facebook_access_token: SecretStr | None = Field(default=None, alias="FACEBOOK_ACCESS_TOKEN")
    facebook_page_id: SecretStr | None = Field(default=None, alias="FACEBOOK_PAGE_ID")

    @field_validator("host")
    @classmethod
    def nonempty_host(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("HOST must not be empty")
        return value

    @model_validator(mode="after")
    def validate_security_and_provider_selection(self) -> EnvironmentSettings:
        if not self.database_url.get_secret_value():
            raise ValueError("DATABASE_URL is required")
        try:
            is_loopback = ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            is_loopback = self.host.lower() == "localhost"
        if not is_loopback and (self.api_token is None or len(self.api_token.get_secret_value()) < 32):
            raise ValueError("API_TOKEN is required and must contain at least 32 characters for non-loopback HOST")

        selections = {
            "LLM_PROVIDER": (self.llm_provider, {"openai_compatible", "fake"}),
            "NEWS_SOURCES": (self.news_sources, {"rss", "fake"}),
            "TTS_PROVIDER": (self.tts_provider, {"google", "fake"}),
            "TRANSCRIPTION_PROVIDER": (self.transcription_provider, {"whisper_local", "fake"}),
        }
        for variable, (raw_values, allowed) in selections.items():
            values = {value.strip() for value in raw_values.split(",") if value.strip()}
            unknown = values - allowed
            if unknown:
                raise ValueError(f"{variable} contains unsupported provider names")
            if self.app_env == "test" and values != {"fake"}:
                raise ValueError(f"{variable} must use only fake providers in APP_ENV=test")
        if self.public_media_base_url and self.media_url_signing_key:
            if len(self.media_url_signing_key.get_secret_value().encode()) < 32:
                raise ValueError("MEDIA_URL_SIGNING_KEY must contain at least 32 bytes")
        elif self.public_media_base_url or self.media_url_signing_key:
            raise ValueError("PUBLIC_MEDIA_BASE_URL and MEDIA_URL_SIGNING_KEY must be configured together")
        return self

    @property
    def effective_log_format(self) -> Literal["json", "console"]:
        return self.log_format or ("json" if self.app_env == "production" else "console")

    def credential_status(self) -> dict[str, bool]:
        """Return presence only, never credential values."""
        return {
            "llm": self.llm_api_key is not None,
            "google_tts": self.google_application_credentials is not None,
            "pexels": self.pexels_api_key is not None,
            "pixabay": self.pixabay_api_key is not None,
            "unsplash": self.unsplash_access_key is not None,
            "higgsfield": self.higgsfield_api_key is not None,
            "instagram": self.instagram_access_token is not None and self.instagram_user_id is not None,
            "tiktok": self.tiktok_client_key is not None and self.tiktok_client_secret is not None,
            "facebook": self.facebook_access_token is not None and self.facebook_page_id is not None,
            "youtube": self.youtube_client_secrets_file is not None,
        }
