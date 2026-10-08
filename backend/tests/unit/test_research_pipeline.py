import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from clipfactory.domain.models import ClaimKind, ContentProfile
from clipfactory.domain.models import ResearchPolicy as ProfileResearchPolicy
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
from clipfactory.research.pipeline import research_grounded_story


class FakeNews:
    name = "fake"
    supports_search = False

    def __init__(self) -> None:
        now = datetime(2026, 9, 30, tzinfo=UTC)
        self.references = [
            ArticleRef("https://news.example/story", "A major science discovery", "News", now),
            ArticleRef("https://other.example/story", "A major science discovery", "Other", now),
        ]

    async def latest(self, query: object) -> list[ArticleRef]:
        del query
        return self.references

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]:
        del text, since, limit
        return []


class ScriptedLLM:
    name = "fake"

    def __init__(self) -> None:
        self.tasks: list[str] = []

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
        self.tasks.append(task)
        if task == "rank_stories":
            value: object = make_ranked()
        else:
            payload = json.loads(messages[1].content.split("\n", maxsplit=1)[1].rsplit("\n<", maxsplit=1)[0])
            source_id = payload[0]["source_id"]
            value = ExtractClaimsResult(
                claims=[
                    ExtractedClaimDraft(
                        ref=f"c{index}",
                        text=text,
                        kind=ClaimKind.FACT,
                        evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt=excerpt)],
                    )
                    for index, (text, excerpt) in enumerate(
                        (
                            ("Three results were confirmed", "confirmed three independent results"),
                            ("The team published findings", "team published its findings in a journal"),
                            ("The method improved measurements", "new method improved measurements significantly"),
                        ),
                        start=1,
                    )
                ],
                key_fact_refs=["c1", "c2", "c3"],
                refined_title="Science discovery confirmed",
                refined_summary="Researchers confirmed new findings.",
            )
        return cast(LLMResult[Any], LLMResult(value, "fake", "test-model"))


def make_ranked() -> RankStoriesResult:
    return RankStoriesResult(
        stories=[
            RankedStoryDraft(
                candidate_indexes=[0],
                title="A major science discovery",
                summary="Researchers report an important result.",
                profile_relevance=0.9,
                newsworthiness=0.9,
                rationale="High public impact",
            )
        ]
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.req("CF-REQ-105")
@pytest.mark.req("CF-REQ-107")
@pytest.mark.req("CF-REQ-112")
@pytest.mark.req("CF-REQ-117")
@pytest.mark.asyncio
async def test_research_pipeline_runs_once_per_llm_task_and_returns_grounded_claims() -> None:
    article_html = (
        b"<article><title>A major science discovery</title><p>Scientists confirmed three independent results today.</p>"
        b"<p>The research team published its findings in a journal.</p>"
        b"<p>They said the new method improved measurements significantly.</p></article>"
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=article_html))
    fetcher = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    news = FakeNews()
    llm = ScriptedLLM()
    policy = ResearchPolicy(
        max_candidate_articles=10,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[],
        publisher_quality={},
        blocked_publishers=[],
    )
    result = await research_grounded_story(
        (news,),
        fetcher,
        llm,
        ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1)),
        policy,
        now=datetime(2026, 9, 30, tzinfo=UTC),
    )
    assert llm.tasks == ["rank_stories", "extract_claims"]
    assert len(result.claims) == 3
    assert all(claim.evidence[0].verified for claim in result.claims)
    assert len(result.key_fact_claim_ids) == 3
