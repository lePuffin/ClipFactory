"""Validation models for editable application-settings sections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clipfactory.infrastructure.settings import EnvironmentSettings


class EnvironmentRuntimeSettings(BaseModel):
    """Non-secret environment keys that may be overridden per Run; defaults come from `.env`."""

    model_config = ConfigDict(extra="forbid")
    llm_model: str = Field(min_length=1, max_length=200)
    llm_model_evaluation: str | None = Field(default=None, max_length=200)
    llm_request_timeout_seconds: int = Field(ge=1, le=600)
    whisper_model: str = Field(min_length=1, max_length=200)
    whisper_device: Literal["auto", "cpu", "cuda"]
    whisper_compute_type: str = Field(min_length=1, max_length=50)
    wan_fps: int = Field(ge=1, le=60)
    wan_inference_steps: int = Field(ge=1, le=100)
    wan_max_generations_per_run: int = Field(default=2, ge=0, le=100, strict=True)
    graphics_fps: int = Field(default=30, ge=1, le=60)
    graphics_timeout_seconds: int = Field(default=180, ge=1, le=3600)

    @field_validator("llm_model", "whisper_model", "whisper_compute_type")
    @classmethod
    def strip_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("llm_model_evaluation")
    @classmethod
    def blank_means_default_model(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


def runtime_environment_defaults(settings: EnvironmentSettings) -> dict[str, Any]:
    return {name: getattr(settings, name) for name in EnvironmentRuntimeSettings.model_fields}


def apply_runtime_environment(
    target: EnvironmentSettings, baseline: EnvironmentSettings, overrides: Mapping[str, Any]
) -> None:
    """Point the shared provider settings at a Run's snapshot, falling back to `.env` values."""
    validated = EnvironmentRuntimeSettings.model_validate({**runtime_environment_defaults(baseline), **overrides})
    for name, value in validated.model_dump().items():
        setattr(target, name, value)


class ProviderCallSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_call_retries: int = Field(default=3, ge=0, le=10)
    call_retry_base_delay_seconds: float = Field(default=2, ge=0.1, le=60)
    call_retry_max_delay_seconds: float = Field(default=60, ge=1, le=600)
    default_timeout_seconds: float = Field(default=60, ge=1, le=600)
    llm_max_schema_repairs: int = Field(default=1, ge=0, le=5)


class WorkflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_revision_retries: int = Field(default=3, ge=0, le=10)
    resume_interrupted_runs: bool = True
    stage_timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class PublishingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["disabled", "dry_run", "live"] = "dry_run"
    approval_required: bool = True
    auto_publish_enabled: bool = False
    auto_publish_after_minutes: int = Field(default=10, ge=1, le=10080)
    public_media_url_ttl_minutes: int = Field(default=60, ge=5, le=1440)


class AnalyticsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_offsets: list[str] = Field(default_factory=lambda: ["1h", "6h", "24h", "48h", "7d", "30d"])
    rpm_by_platform: dict[str, float] = Field(
        default_factory=lambda: {
            "youtube": 0.05,
            "instagram": 0.01,
            "tiktok": 0.40,
            "facebook": 0.02,
        }
    )
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")

    @field_validator("snapshot_offsets")
    @classmethod
    def valid_offsets(cls, values: list[str]) -> list[str]:
        invalid = any(
            len(value) < 2 or value[-1] not in {"h", "d"} or not value[:-1].isdigit() or int(value[:-1]) <= 0
            for value in values
        )
        if not values or invalid:
            raise ValueError("snapshot_offsets must contain positive hour/day values such as 1h or 7d")
        return values


_EDITABLE_MODELS: dict[str, type[BaseModel]] = {
    "environment": EnvironmentRuntimeSettings,
    "providers": ProviderCallSettings,
    "workflow": WorkflowSettings,
    "publishing": PublishingSettings,
    "analytics": AnalyticsSettings,
}


def validate_settings_section(section: str, value: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    if section not in defaults or not isinstance(defaults[section], dict):
        raise ValueError(f"Unknown settings section: {section}")
    model = _EDITABLE_MODELS.get(section)
    if model is None:
        unknown = set(value) - set(defaults[section])
        if unknown:
            raise ValueError(f"Unknown settings keys: {', '.join(sorted(unknown))}")
        return value
    return model.model_validate({**defaults[section], **value}).model_dump(mode="json")
