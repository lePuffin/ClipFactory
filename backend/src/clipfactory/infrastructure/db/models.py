"""Persistence mappings; domain objects remain independent of SQLAlchemy."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from clipfactory.infrastructure.db.base import Base

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ContentProfileRow(Base):
    __tablename__ = "content_profile"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_content_profile_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )


class AppSettingsRow(Base):
    __tablename__ = "app_settings"

    section: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunRow(Base):
    __tablename__ = "run"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    manual_url: Mapped[str | None] = mapped_column(Text)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("content_profile.id"), nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    outcome: Mapped[str | None] = mapped_column(String(24))
    current_stage: Mapped[str | None] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision_retries_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_story_id: Mapped[UUID | None] = mapped_column(Uuid)
    story_package_id: Mapped[UUID | None] = mapped_column(Uuid)
    approved_clip_id: Mapped[UUID | None] = mapped_column(Uuid)
    failure_stage: Mapped[str | None] = mapped_column(String(40))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    cost_total: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[RunEventRow]] = relationship(back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "uq_run_one_active",
            text("(1)"),
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_run_created_at", "created_at"),
    )


class RunEventRow(Base):
    __tablename__ = "run_event"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(40))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(12), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[RunRow] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
        Index("ix_run_event_run", "run_id", "sequence"),
    )


class SourceRow(Base):
    __tablename__ = "source"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    origin_publisher: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    quality_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    syndication_of: Mapped[UUID | None] = mapped_column(ForeignKey("source.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)


class StoryRow(Base):
    __tablename__ = "story"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_score: Mapped[float | None]
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    selection_rationale: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    key_fact_claim_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)


class StorySourceRow(Base):
    __tablename__ = "story_source"

    story_id: Mapped[UUID] = mapped_column(ForeignKey("story.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("source.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_independent: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ClaimRow(Base):
    __tablename__ = "claim"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("story.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    support_level: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("source.id"), nullable=False, index=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (UniqueConstraint("claim_id", "source_id", "excerpt", name="uq_claim_evidence_excerpt"),)


class StoryPackageRow(Base):
    __tablename__ = "story_package"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False, unique=True)
    story_id: Mapped[UUID] = mapped_column(ForeignKey("story.id"), nullable=False)
    key_fact_claim_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScriptVersionRow(Base):
    __tablename__ = "script_version"

    story_package_id: Mapped[UUID] = mapped_column(ForeignKey("story_package.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)


class VisualPlanVersionRow(Base):
    __tablename__ = "visual_plan_version"

    story_package_id: Mapped[UUID] = mapped_column(ForeignKey("story_package.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)


class AssetRow(Base):
    __tablename__ = "asset"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None]
    height: Mapped[int | None]
    duration_seconds: Mapped[float | None]
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    subjects: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    music: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    reusable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_asset_positive_size"),
        Index("ix_asset_status_type", "status", "media_type"),
    )


class ClipRow(Base):
    __tablename__ = "clip"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True)
    story_package_id: Mapped[UUID] = mapped_column(ForeignKey("story_package.id"), nullable=False)
    story_package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[float] = mapped_column(nullable=False)
    video_codec: Mapped[str] = mapped_column(String(32), nullable=False)
    audio_codec: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    composition_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RenderRevisionRow(Base):
    __tablename__ = "render_revision"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    base_clip_id: Mapped[UUID] = mapped_column(ForeignKey("clip.id"), nullable=False, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetUsageRow(Base):
    __tablename__ = "asset_usage"

    clip_id: Mapped[UUID] = mapped_column(ForeignKey("clip.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("asset.id"), primary_key=True)
    visual_segment_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_seconds: Mapped[float] = mapped_column(nullable=False)
    end_seconds: Mapped[float] = mapped_column(nullable=False)


class EvaluationRow(Base):
    __tablename__ = "evaluation"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True)
    clip_id: Mapped[UUID | None] = mapped_column(ForeignKey("clip.id", ondelete="CASCADE"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    layer: Mapped[str] = mapped_column(String(24), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    evaluator: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StageArtifactRow(Base):
    __tablename__ = "stage_artifact"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationRow(Base):
    __tablename__ = "publication"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    clip_id: Mapped[UUID] = mapped_column(ForeignKey("clip.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    platform_post_id: Mapped[str | None] = mapped_column(String(255))
    platform_url: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    call_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("clip_id", "platform", name="uq_publication_clip_platform"),)


class MetricSnapshotRow(Base):
    __tablename__ = "metric_snapshot"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    publication_id: Mapped[UUID] = mapped_column(ForeignKey("publication.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(24), nullable=False)
    offset_label: Mapped[str] = mapped_column(String(12), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    shares: Mapped[int | None]
    watch_time_seconds: Mapped[float | None]
    average_retention_ratio: Mapped[float | None]
    followers_delta: Mapped[int | None]
    estimated_revenue: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    revenue_currency: Mapped[str | None] = mapped_column(String(3))
    revenue_basis: Mapped[str | None] = mapped_column(String(32))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)

    __table_args__ = (UniqueConstraint("publication_id", "offset_label", name="uq_metric_snapshot_offset"),)


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_task"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CostEntryRow(Base):
    __tablename__ = "cost_entry"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), nullable=False, index=True)
    clip_id: Mapped[UUID | None] = mapped_column(ForeignKey("clip.id"))
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    basis: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class LLMRequestRow(Base):
    __tablename__ = "llm_request"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("run.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    attempt_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    cost_reported: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    rate_limit_headers: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
