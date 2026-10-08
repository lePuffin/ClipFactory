"""Persistence contract for a Run's research output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import Claim


@dataclass(frozen=True, slots=True)
class ResearchSourceRecord:
    id: UUID
    url: str
    canonical_url: str
    publisher: str
    origin_publisher: str
    title: str
    text: str
    text_hash: str
    quality_tier: str
    retrieved_at: datetime
    published_at: datetime | None
    author: str | None
    syndication_of: UUID | None


@dataclass(frozen=True, slots=True)
class ResearchStoryRecord:
    id: UUID
    status: str
    title: str
    summary: str
    category: str
    selection_score: float | None
    score_breakdown: dict[str, Any] | None
    selection_rationale: str | None
    rejection_reason: str | None
    source_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ResearchSnapshot:
    run_id: UUID
    sources: tuple[ResearchSourceRecord, ...]
    stories: tuple[ResearchStoryRecord, ...]
    selected_story_id: UUID
    claims: tuple[Claim, ...]
    key_fact_claim_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class SelectedStoryContext:
    story_id: UUID
    sources: tuple[ResearchSourceRecord, ...]


class ResearchRepository(Protocol):
    def persist(self, snapshot: ResearchSnapshot) -> None: ...


class ClaimExtractionRepository(Protocol):
    def selected_story_context(self, run_id: UUID) -> SelectedStoryContext: ...

    def persist_claims(
        self,
        story_id: UUID,
        claims: tuple[Claim, ...],
        key_fact_claim_ids: tuple[UUID, ...],
        title: str,
        summary: str,
    ) -> None: ...
