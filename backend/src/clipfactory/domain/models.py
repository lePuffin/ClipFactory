"""Canonical domain entities and value objects."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContentCategory(StrEnum):
    GENERAL = "general"
    TECHNOLOGY = "technology"
    AI = "ai"
    FINANCE = "finance"
    BUSINESS = "business"
    SCIENCE = "science"
    GAMING = "gaming"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    POLITICS = "politics"


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    RUN_NOW = "run_now"
    MANUAL_URL = "manual_url"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunOutcome(StrEnum):
    PUBLISHED = "published"
    PARTIALLY_PUBLISHED = "partially_published"
    NOT_PUBLISHED = "not_published"
    AWAITING_APPROVAL = "awaiting_approval"


class Stage(StrEnum):
    RESEARCH = "research"
    INGEST_URL = "ingest_url"
    CLUSTER_STORIES = "cluster_stories"
    SELECT_STORY = "select_story"
    GATHER_SOURCES = "gather_sources"
    EXTRACT_CLAIMS = "extract_claims"
    BUILD_STORY_PACKAGE = "build_story_package"
    WRITE_SCRIPT = "write_script"
    PLAN_VISUALS = "plan_visuals"
    SELECT_ASSETS = "select_assets"
    GENERATE_NARRATION = "generate_narration"
    TRANSCRIBE_NARRATION = "transcribe_narration"
    BUILD_CAPTIONS = "build_captions"
    COMPOSE_CLIP = "compose_clip"
    VALIDATE_CLIP = "validate_clip"
    EVALUATE_CLIP = "evaluate_clip"
    PLAN_RETRY = "plan_retry"
    PUBLISH = "publish"


class AssetOrigin(StrEnum):
    EXTERNAL = "external"
    GENERATED = "generated"
    RENDERED = "rendered"
    IMPORTED = "imported"


class AssetStatus(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class ClipStatus(StrEnum):
    RENDERED = "rendered"
    REJECTED = "rejected"
    APPROVED = "approved"


class EvaluationLayer(StrEnum):
    STAGE_GATE = "stage_gate"
    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


class IssueSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class ActionType(StrEnum):
    GATHER_MORE_SOURCES = "gather_more_sources"
    REMOVE_CLAIM = "remove_claim"
    REVISE_SCRIPT = "revise_script"
    REPLAN_VISUALS = "replan_visuals"
    RESELECT_ASSET = "reselect_asset"
    REGENERATE_NARRATION = "regenerate_narration"
    RECOMPOSE = "recompose"
    ABORT = "abort"


class SupportLevel(StrEnum):
    CORROBORATED = "corroborated"
    SINGLE_SOURCE = "single_source"
    UNSUPPORTED = "unsupported"


class ClaimStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ClaimKind(StrEnum):
    FACT = "fact"
    FIGURE = "figure"
    QUOTE = "quote"
    STATEMENT_ATTRIBUTED = "statement_attributed"


class DurationPolicy(StrictModel):
    min_seconds: float = Field(gt=0)
    target_seconds: float = Field(gt=0)
    max_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered_bounds(self) -> DurationPolicy:
        if not self.min_seconds <= self.target_seconds <= self.max_seconds:
            raise ValueError("duration must satisfy min_seconds <= target_seconds <= max_seconds")
        return self


class OutputSpec(StrictModel):
    width: int = Field(default=720, gt=0)
    height: int = Field(default=1280, gt=0)
    fps: int = Field(default=30, ge=24, le=60)

    @model_validator(mode="after")
    def vertical_nine_sixteenths(self) -> OutputSpec:
        if self.width * 16 != self.height * 9:
            raise ValueError("output must have a 9:16 aspect ratio")
        if self.width % 2 or self.height % 2:
            raise ValueError("output dimensions must be even")
        return self


class VoiceSpec(StrictModel):
    provider_voice_id: str = Field(min_length=1)
    speaking_rate: float = Field(default=1.0, gt=0)
    words_per_minute: int = Field(default=150, gt=0)


class VisualStyle(StrictModel):
    description: str = "clean, factual news style"
    caption_style: str = "bold_white_on_dark_box"
    motion_intensity: Literal["low", "medium", "high"] = "medium"
    allow_generated_media: bool = True

    @field_validator("motion_intensity")
    @classmethod
    def valid_motion_intensity(cls, value: str) -> str:
        if value not in {"low", "medium", "high"}:
            raise ValueError("motion_intensity must be low, medium or high")
        return value


class Schedule(StrictModel):
    enabled: bool = True
    local_time: str = "05:00"
    timezone: str = "Europe/Lisbon"

    @field_validator("local_time")
    @classmethod
    def valid_local_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("local_time must use HH:MM")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class ResearchPolicy(StrictModel):
    max_candidate_articles: int = Field(default=20, ge=1, le=50)
    min_sources: int = Field(default=1, ge=1)
    preferred_independent_sources: int = Field(default=3, ge=1)
    max_article_age_hours: int = Field(default=24, gt=0)
    allowed_publishers: list[str] | None = None
    blocked_publishers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def minimum_does_not_exceed_preferred(self) -> ResearchPolicy:
        if self.min_sources > self.preferred_independent_sources:
            raise ValueError("min_sources must not exceed preferred_independent_sources")
        return self


class MusicPolicy(StrictModel):
    enabled: bool = True
    mood_tags: list[str] = Field(default_factory=lambda: ["news", "neutral"])
    energy: str | None = "low"
    ducked_level_db: float = -20
    unducked_level_db: float = -12


class GenerationPolicy(StrictModel):
    image_providers: list[str] = Field(default_factory=lambda: ["comfyui", "higgsfield"])
    video_providers: list[str] = Field(default_factory=lambda: ["comfyui", "wan_local", "higgsfield"])


class ContentProfile(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = "Global News (English)"
    is_active: bool = True
    language: str = "en"
    category: ContentCategory = ContentCategory.GENERAL
    topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=lambda: ["global"])
    markets: list[str] = Field(default_factory=lambda: ["global"])
    voice: VoiceSpec = Field(default_factory=lambda: VoiceSpec(provider_voice_id="en-US-Chirp3-HD-Leda"))
    duration: DurationPolicy = Field(
        default_factory=lambda: DurationPolicy(min_seconds=60, target_seconds=70, max_seconds=90)
    )
    output: OutputSpec = Field(default_factory=OutputSpec)
    visual_style: VisualStyle = Field(default_factory=VisualStyle)
    platforms: list[Platform] = Field(default_factory=list)
    schedule: Schedule = Field(default_factory=Schedule)
    research: ResearchPolicy = Field(default_factory=ResearchPolicy)
    music: MusicPolicy = Field(default_factory=MusicPolicy)
    generation: GenerationPolicy = Field(default_factory=GenerationPolicy)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("language")
    @classmethod
    def valid_language_tag(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
            raise ValueError("language must be a BCP 47 language tag")
        return value


class Evidence(StrictModel):
    source_id: UUID
    excerpt: str = Field(min_length=1)
    verified: bool = False


class Claim(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    story_id: UUID
    text: str = Field(min_length=1)
    kind: ClaimKind = ClaimKind.FACT
    evidence: list[Evidence] = Field(default_factory=list)
    support_level: SupportLevel = SupportLevel.UNSUPPORTED
    status: ClaimStatus = ClaimStatus.REJECTED
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def accepted_claim_must_be_supported(self) -> Claim:
        if self.status == ClaimStatus.ACCEPTED and self.support_level == SupportLevel.UNSUPPORTED:
            raise ValueError("unsupported Claims cannot be accepted")
        return self


class Provenance(StrictModel):
    origin: AssetOrigin
    provider: str = Field(min_length=1)
    license: str = Field(min_length=1)
    source_url: str | None = None
    download_url: str | None = None
    author: str | None = None
    license_url: str | None = None
    allowed_platforms: list[Platform] | None = None
    attribution_text: str | None = None
    attribution_required: bool = False
    generation: dict[str, Any] | None = None
    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def provenance_invariants(self) -> Provenance:
        if self.origin == AssetOrigin.EXTERNAL and not self.source_url:
            raise ValueError("external Assets require a source_url")
        if self.origin == AssetOrigin.GENERATED and self.generation is None:
            raise ValueError("generated Assets require generation metadata")
        if self.attribution_required and not self.attribution_text:
            raise ValueError("attribution_text is required when attribution is required")
        return self


class MusicInfo(StrictModel):
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    mood: list[str] = Field(default_factory=list)
    energy: Literal["low", "medium", "high"]
    bpm: int | None = Field(default=None, gt=0)
    loopable: bool = False
    allowed_platforms: list[Platform] | None = None


class Asset(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    media_type: str
    category: str
    storage_key: str
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    mime_type: str
    size_bytes: int = Field(gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration_seconds: float | None = Field(default=None, gt=0)
    description: str
    tags: list[str] = Field(default_factory=list)
    subjects: list[str] = Field(default_factory=list)
    provenance: Provenance
    music: MusicInfo | None = None
    reusable: bool = True
    status: AssetStatus = AssetStatus.ACTIVE
    quality_score: float | None = Field(default=None, ge=0, le=1)
    usage_count: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def music_metadata_matches_category(self) -> Asset:
        if (self.category == "music") != (self.music is not None):
            raise ValueError("music metadata is required exactly for music Assets")
        return self


class Run(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    trigger: RunTrigger
    manual_url: str | None = None
    profile_id: UUID
    profile_snapshot: dict[str, Any]
    status: RunStatus = RunStatus.QUEUED
    outcome: RunOutcome | None = None
    current_stage: Stage | None = None
    attempt: int = Field(default=1, ge=1)
    revision_retries_used: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def manual_url_matches_trigger(self) -> Run:
        if (self.trigger == RunTrigger.MANUAL_URL) != (self.manual_url is not None):
            raise ValueError("manual_url is required only for manual_url Runs")
        return self


class Issue(StrictModel):
    code: str = Field(min_length=1)
    severity: IssueSeverity
    stage: Stage
    message: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    refs: dict[str, Any] = Field(default_factory=dict)


class Action(StrictModel):
    type: ActionType
    target_stage: Stage
    instructions: str = ""
    refs: dict[str, Any] = Field(default_factory=dict)


class Evaluation(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    clip_id: UUID | None = None
    attempt: int = Field(ge=1)
    layer: EvaluationLayer
    issues: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    evaluator: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def passed(self) -> bool:
        return not any(issue.severity == IssueSeverity.BLOCKING for issue in self.issues)


def normalize_evidence_text(value: str) -> str:
    """Normalize whitespace, case and common quote/dash variants for evidence checks."""
    normalized = unicodedata.normalize("NFC", value).casefold()
    normalized = normalized.translate(
        str.maketrans({"'": '"', "‘": '"', "’": '"', "“": '"', "”": '"', "–": "-", "—": "-"})  # noqa: RUF001
    )
    return " ".join(normalized.split())


def verify_evidence_excerpt(excerpt: str, source_text: str) -> bool:
    return normalize_evidence_text(excerpt) in normalize_evidence_text(source_text)


def compute_support_level(independent_verified_sources: int) -> SupportLevel:
    if independent_verified_sources >= 2:
        return SupportLevel.CORROBORATED
    if independent_verified_sources == 1:
        return SupportLevel.SINGLE_SOURCE
    return SupportLevel.UNSUPPORTED


def money_total(amounts: list[Decimal]) -> Decimal:
    return sum(amounts, start=Decimal("0"))
