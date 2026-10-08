"""Application use case for research, grounding, persistence, and Run Events."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import ContentProfile
from clipfactory.ports.llm import LLMProvider
from clipfactory.ports.news import NewsSource
from clipfactory.ports.research import ResearchRepository
from clipfactory.research.discovery import ByteFetcher, ResearchPolicy
from clipfactory.research.pipeline import (
    GroundedStoryResult,
    make_research_snapshot,
    research_grounded_story,
)
from clipfactory.research.selection import SelectionWeights


class RunEventWriter(Protocol):
    def append_event(
        self,
        run_id: UUID,
        event_type: str,
        message: str,
        *,
        stage: str | None = None,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class ResearchUseCase:
    def __init__(
        self,
        *,
        news_sources: tuple[NewsSource, ...],
        fetcher: ByteFetcher,
        llm: LLMProvider,
        repository: ResearchRepository,
        events: RunEventWriter,
    ) -> None:
        self.news_sources = news_sources
        self.fetcher = fetcher
        self.llm = llm
        self.repository = repository
        self.events = events

    async def execute(
        self,
        run_id: UUID,
        profile: ContentProfile,
        policy: ResearchPolicy,
        *,
        now: datetime,
        selection_weights: SelectionWeights | None = None,
        recently_covered_titles: tuple[str, ...] = (),
        max_claim_input_chars: int = 60_000,
        emit_events: bool = True,
    ) -> GroundedStoryResult:
        async def progress(message: str, payload: dict[str, object]) -> None:
            await asyncio.to_thread(
                self.events.append_event, run_id, "progress", message, stage="research", payload=dict(payload)
            )

        result = await research_grounded_story(
            self.news_sources,
            self.fetcher,
            self.llm,
            profile,
            policy,
            now=now,
            selection_weights=selection_weights or SelectionWeights(),
            recently_covered_titles=recently_covered_titles,
            max_claim_input_chars=max_claim_input_chars,
            progress=progress,
        )
        snapshot = make_research_snapshot(result, run_id=run_id, category=profile.category.value, now=now)
        await asyncio.to_thread(self.repository.persist, snapshot)
        if not emit_events:
            return result
        await asyncio.to_thread(
            self.events.append_event,
            run_id,
            "research_completed",
            "Research completed",
            stage="research",
            payload={
                "references_seen": result.research.references_seen,
                "articles_fetched": len(result.research.articles),
                "articles_skipped": result.research.articles_skipped,
            },
        )
        await asyncio.to_thread(
            self.events.append_event,
            run_id,
            "story_selected",
            "Story selected",
            stage="select_story",
            payload={
                "story_id": str(result.story_id),
                "title": result.title,
                "fallback_index": result.fallback_index,
            },
        )
        independent_count = sum(source.syndication_of is None for source in result.sources)
        await asyncio.to_thread(
            self.events.append_event,
            run_id,
            "sources_collected",
            "Evidence Sources collected",
            stage="gather_sources",
            payload={
                "article_count": len(result.sources),
                "independent_source_count": independent_count,
                "preferred": profile.research.preferred_independent_sources,
            },
        )
        await asyncio.to_thread(
            self.events.append_event,
            run_id,
            "claims_extracted",
            "Claims extracted and evidence verified",
            stage="extract_claims",
            payload={
                "accepted": sum(claim.status.value == "accepted" for claim in result.claims),
                "rejected": sum(claim.status.value == "rejected" for claim in result.claims),
                "corroborated": sum(claim.support_level.value == "corroborated" for claim in result.claims),
                "single_source": sum(claim.support_level.value == "single_source" for claim in result.claims),
            },
        )
        return result
