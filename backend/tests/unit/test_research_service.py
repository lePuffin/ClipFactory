import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, select

from clipfactory.domain.models import ClaimKind, ContentProfile, RunTrigger
from clipfactory.domain.models import ResearchPolicy as ProfileResearchPolicy
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ClaimEvidenceRow, ClaimRow, SourceRow, StoryRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.research_repository import ResearchRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.ports.news import ArticleRef
from clipfactory.research.discovery import ResearchPolicy
from clipfactory.research.grounding import ClaimEvidenceDraft
from clipfactory.research.llm_tasks import (
    ExtractClaimsResult,
    ExtractedClaimDraft,
    RankedStoryDraft,
    RankStoriesResult,
)
from clipfactory.research.service import ResearchUseCase


class FakeNewsSource:
    name = "fake_news"
    supports_search = False

    async def latest(self, query: object) -> list[ArticleRef]:
        del query
        return [
            ArticleRef(
                "https://news.example/report",
                "Scientists confirm three results",
                "News Example",
                datetime(2026, 9, 30, tzinfo=UTC),
            )
        ]

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]:
        del text, since, limit
        return []


class GroundedFakeLLM:
    name = "fake"

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[Any],
        *,
        model_role: str = "default",
        images: list[Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[Any]:
        del schema, model_role, images, temperature
        if task == "rank_stories":
            value: object = RankStoriesResult(
                stories=[
                    RankedStoryDraft(
                        candidate_indexes=[0],
                        title="Scientists confirm three results",
                        summary="Researchers confirmed several results.",
                        profile_relevance=0.9,
                        newsworthiness=0.9,
                        rationale="Broad public relevance",
                    )
                ]
            )
        else:
            sources = json.loads(messages[1].content.split("\n", 1)[1].rsplit("\n<", 1)[0])
            source_id = sources[0]["source_id"]
            value = ExtractClaimsResult(
                claims=[
                    ExtractedClaimDraft(
                        ref=f"c{index}",
                        text=claim_text,
                        kind=ClaimKind.FACT,
                        evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt=excerpt)],
                    )
                    for index, (claim_text, excerpt) in enumerate(
                        (
                            ("Researchers confirmed three results", "confirmed three independent results"),
                            ("The team published a report", "team published its report on Tuesday"),
                            ("The study improved measurements", "study improved measurements significantly"),
                        ),
                        start=1,
                    )
                ],
                key_fact_refs=["c1", "c2", "c3"],
                refined_title="Scientists confirm three results",
                refined_summary="Researchers confirmed several results.",
            )
        return cast(LLMResult[Any], LLMResult(value, self.name, "test-model"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-118")
@pytest.mark.req("CF-REQ-850")
@pytest.mark.req("CF-REQ-113")
@pytest.mark.asyncio
async def test_research_use_case_persists_grounded_story_and_emits_events(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'research-service.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    runs = RunRepository(sessions)
    run = runs.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    html = (
        b"<article><title>Scientists confirm three results</title>"
        b"<p>Researchers confirmed three independent results.</p>"
        b"<p>The team published its report on Tuesday.</p>"
        b"<p>The study improved measurements significantly.</p></article>"
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=html))
    fetcher = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    research = ResearchUseCase(
        news_sources=(FakeNewsSource(),),
        fetcher=fetcher,
        llm=GroundedFakeLLM(),
        repository=ResearchRepository(sessions),
        events=runs,
    )
    profile = ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1))
    result = await research.execute(
        UUID(run["run_id"]),
        profile,
        ResearchPolicy(
            max_candidate_articles=10,
            max_article_age_hours=24,
            max_article_bytes=100_000,
            feeds=[],
            publisher_quality={},
            blocked_publishers=[],
        ),
        now=datetime(2026, 9, 30, tzinfo=UTC),
    )
    with sessions() as session:
        assert session.scalar(select(SourceRow.id)) is not None
        assert session.scalar(select(StoryRow.id).where(StoryRow.status == "selected")) == result.story_id
        assert len(list(session.scalars(select(ClaimRow.id)))) == 3
        assert len(list(session.scalars(select(ClaimEvidenceRow.id)))) == 3
    detail = runs.get(UUID(run["run_id"]))
    assert [event["type"] for event in detail["events"]][-4:] == [
        "research_completed",
        "story_selected",
        "sources_collected",
        "claims_extracted",
    ]
    engine.dispose()
