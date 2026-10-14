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


@dataclass(frozen=True, slots=True)
class CoveredStory:
    """The selected Story of a successfully completed Run, used by the novelty rule."""

    title: str
    canonical_urls: frozenset[str]


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


class ResearchRepository(Protocol):
    def persist(self, snapshot: ResearchSnapshot) -> None: ...


class StoryFallbackRepository(ResearchRepository, ClaimExtractionRepository, Protocol):
    def select_fallback(self, run_id: UUID, rejected_story_id: UUID, min_sources: int) -> tuple[UUID, int] | None: ...
