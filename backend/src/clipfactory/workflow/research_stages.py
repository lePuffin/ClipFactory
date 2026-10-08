"""Workflow adapters for the persisted grounded-research application service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from clipfactory.domain.models import ContentProfile, Stage
from clipfactory.ports.errors import ProviderError
from clipfactory.research.discovery import ResearchPolicy
from clipfactory.research.pipeline import ResearchFailure
from clipfactory.research.service import ResearchUseCase
from clipfactory.workflow.executor import StageFailure, StageUseCase
from clipfactory.workflow.graph import WorkflowState


class ResearchStageUseCase:
    def __init__(self, research: ResearchUseCase, research_repository: Any, runs: Any) -> None:
        self._research = research
        self._repository = research_repository
        self._runs = runs

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        detail = await asyncio.to_thread(self._runs.get, run_id)
        persisted = await asyncio.to_thread(self._repository.summary, run_id)
        if persisted is not None:
            return {"story_id": str(persisted["story_id"])}
        profile = ContentProfile.model_validate(detail["profile_snapshot"])
        configured = detail["settings_snapshot"].get("research", {})
        policy = ResearchPolicy(
            max_candidate_articles=profile.research.max_candidate_articles,
            max_article_age_hours=profile.research.max_article_age_hours,
            max_article_bytes=int(configured.get("max_article_bytes", 5_000_000)),
            feeds=[tuple(item) for item in configured.get("feeds", [])],
            publisher_quality=dict(configured.get("publisher_quality", {})),
            blocked_publishers=profile.research.blocked_publishers,
            allowed_publishers=profile.research.allowed_publishers,
            excluded_topics=profile.excluded_topics,
            preferred_topics=profile.topics,
        )
        try:
            result = await self._research.execute(
                run_id,
                profile,
                policy,
                now=datetime.now(UTC),
                max_claim_input_chars=int(detail["settings_snapshot"].get("llm", {}).get("max_input_chars", 60_000)),
                emit_events=False,
            )
        except ResearchFailure as exc:
            raise StageFailure(exc.code, str(exc)) from exc
        except ProviderError as exc:
            code = "llm_invalid_output" if exc.code == "llm_invalid_output" else "llm_unavailable"
            raise StageFailure(code, str(exc)) from exc
        await asyncio.to_thread(
            self._runs.append_event,
            run_id,
            "research_completed",
            "Research completed",
            stage=Stage.RESEARCH.value,
            payload={
                "references_seen": result.research.references_seen,
                "articles_fetched": len(result.research.articles),
                "articles_skipped": result.research.articles_skipped,
            },
        )
        return {"story_id": str(result.story_id), "story_fallbacks_used": result.fallback_index}


class PersistedResearchStageUseCase:
    def __init__(self, stage: Stage, research_repository: Any, runs: Any) -> None:
        self._stage = stage
        self._repository = research_repository
        self._runs = runs

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        summary = await asyncio.to_thread(self._repository.summary, run_id)
        if summary is None:
            raise StageFailure("internal_error", "Persisted grounded research output is missing")
        detail = await asyncio.to_thread(self._runs.get, run_id)
        event_type, message, payload = self._event(summary, state, detail)
        await asyncio.to_thread(
            self._runs.append_event,
            run_id,
            event_type,
            message,
            stage=self._stage.value,
            payload=payload,
        )
        return {"story_id": str(summary["story_id"])}

    def _event(
        self, summary: dict[str, object], state: WorkflowState, detail: dict[str, Any]
    ) -> tuple[str, str, dict[str, object]]:
        if self._stage == Stage.CLUSTER_STORIES:
            return "stories_clustered", "Stories clustered", {"story_candidates": summary["story_candidates"]}
        if self._stage == Stage.SELECT_STORY:
            return (
                "story_selected",
                "Story selected",
                {
                    "story_id": str(summary["story_id"]),
                    "title": summary["title"],
                    "fallback_index": state.get("story_fallbacks_used", 0),
                },
            )
        if self._stage == Stage.GATHER_SOURCES:
            return (
                "sources_collected",
                "Evidence Sources collected",
                {
                    "article_count": summary["article_count"],
                    "independent_source_count": summary["independent_source_count"],
                    "preferred": detail["profile_snapshot"]["research"]["preferred_independent_sources"],
                },
            )
        return (
            "claims_extracted",
            "Claims extracted and evidence verified",
            {key: summary[key] for key in ("accepted", "rejected", "corroborated", "single_source")},
        )


def research_stage_handlers(
    research: ResearchUseCase, research_repository: Any, runs: Any
) -> dict[Stage, StageUseCase]:
    return {
        Stage.RESEARCH: ResearchStageUseCase(research, research_repository, runs),
        **{
            stage: PersistedResearchStageUseCase(stage, research_repository, runs)
            for stage in (
                Stage.CLUSTER_STORIES,
                Stage.SELECT_STORY,
                Stage.GATHER_SOURCES,
                Stage.EXTRACT_CLAIMS,
            )
        },
    }
