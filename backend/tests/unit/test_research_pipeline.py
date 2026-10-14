import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from clipfactory.domain.models import ClaimKind, ContentCategory, ContentProfile
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

    def __init__(self, claim_texts: tuple[str, ...] | None = None) -> None:
        self.tasks: list[str] = []
        self.claim_texts = claim_texts or (
            "Scientists confirmed three independent results today after a two year study of ocean samples",
            "The research team published its findings in a peer reviewed journal on Tuesday morning",
            "The new method improved measurement accuracy significantly compared with"
            " the older laboratory techniques used until now",
            "Researchers said the results will be shared with coastal monitoring agencies"
            " and regional fishing authorities next month",
        )

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
                        zip(
                            self.claim_texts,
                            (
                                "confirmed three independent results",
                                "team published its findings in a journal",
                                "new method improved measurements significantly",
                                "confirmed three independent results",
                            ),
                            strict=False,
                        ),
                        start=1,
                    )
                ],
                key_fact_refs=[f"c{index}" for index in range(1, min(len(self.claim_texts), 4) + 1)],
                refined_title="Science discovery confirmed",
                refined_summary="Researchers confirmed new findings.",
            )
        return cast(LLMResult[Any], LLMResult(value, "fake", "test-model"))


def make_ranked() -> RankStoriesResult:
    return RankStoriesResult(
        stories=[
            RankedStoryDraft(
                candidate_indexes=[0],
                category=ContentCategory.SCIENCE,
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
    assert len(result.claims) == 4
    assert all(claim.evidence[0].verified for claim in result.claims)
    assert len(result.key_fact_claim_ids) == 4


@pytest.mark.req("CF-REQ-108")
@pytest.mark.req("CF-REQ-107")
@pytest.mark.asyncio
async def test_sports_run_rejects_politics_before_claim_extraction_using_existing_ranking_call() -> None:
    from clipfactory.research.pipeline import ResearchFailure

    class PoliticsLLM(ScriptedLLM):
        async def generate_structured(
            self, task: str, messages: list[LLMMessage], schema: type[Any], **kwargs: Any
        ) -> LLMResult[Any]:
            assert task == "rank_stories"
            self.tasks.append(task)
            assert "Profile category: sports" in messages[1].content
            assert "independently of the profile" in messages[0].content
            value = RankStoriesResult(
                stories=[
                    RankedStoryDraft(
                        candidate_indexes=[0],
                        title="Houthis attack Aramco",
                        summary="Regional political conflict.",
                        category=ContentCategory.POLITICS,
                        profile_relevance=1,
                        newsworthiness=1,
                        rationale="Major global event",
                    )
                ]
            )
            return LLMResult(value, "fake", "test-model")

    html = b"<article><title>Houthis attack Aramco</title><p>Regional conflict escalates.</p></article>"
    fetcher = SafeHTTPClient(
        resolver=lambda _host, _port: ["93.184.216.34"],
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=html)),
    )
    llm = PoliticsLLM()
    policy = ResearchPolicy(
        max_candidate_articles=10,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[("BBC World", "https://news.example/rss")],
        publisher_quality={},
        blocked_publishers=[],
    )
    events: list[dict[str, object]] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        events.append(payload)

    with pytest.raises(ResearchFailure) as error:
        await research_grounded_story(
            (FakeNews(),),
            fetcher,
            llm,
            ContentProfile(category=ContentCategory.SPORTS),
            policy,
            now=datetime(2026, 9, 30, tzinfo=UTC),
            progress=progress,
        )
    assert error.value.code == "no_suitable_story"
    assert llm.tasks == ["rank_stories"]
    assert any(event.get("reason") == "category_mismatch" and event.get("category") == "politics" for event in events)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-117")
def test_minimum_evidence_words_follow_the_profile_minimum_duration_and_speaking_rate() -> None:
    from clipfactory.research.pipeline import minimum_evidence_words

    assert minimum_evidence_words(ContentProfile()) == 60


@pytest.mark.unit
@pytest.mark.req("CF-REQ-117")
@pytest.mark.asyncio
async def test_a_story_with_three_short_claims_is_skipped_for_too_little_evidence() -> None:
    from clipfactory.research.pipeline import ResearchFailure

    article_html = (
        b"<article><title>A major science discovery</title><p>Scientists confirmed three independent results today.</p>"
        b"<p>The research team published its findings in a journal.</p>"
        b"<p>They said the new method improved measurements significantly.</p></article>"
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=article_html))
    fetcher = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    llm = ScriptedLLM(
        ("Three results were confirmed", "The team published findings", "The method improved measurements")
    )
    events: list[str] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        del payload
        events.append(message)

    policy = ResearchPolicy(
        max_candidate_articles=10,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[],
        publisher_quality={},
        blocked_publishers=[],
    )
    with pytest.raises(ResearchFailure) as failure:
        await research_grounded_story(
            (FakeNews(),),
            fetcher,
            llm,
            ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1)),
            policy,
            now=datetime(2026, 9, 30, tzinfo=UTC),
            progress=progress,
        )
    assert failure.value.code == "insufficient_claims"
    assert any("12 words of accepted evidence, 60 needed" in message for message in events)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_all_feeds_failing_reports_each_feed_error_as_warning_and_in_no_candidates() -> None:
    from clipfactory.research.pipeline import ResearchFailure

    class DownNews(FakeNews):
        async def latest(self, query: Any) -> list[ArticleRef]:
            raise OSError(f"{query.feeds[0][0]} unreachable")

    events: list[tuple[str, dict[str, object]]] = []
    waits: list[float] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        events.append((message, payload))

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    policy = ResearchPolicy(
        max_candidate_articles=5,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[("BBC", "https://bbc.example/f"), ("DW", "https://dw.example/f")],
        publisher_quality={},
        blocked_publishers=[],
    )
    with pytest.raises(ResearchFailure) as failure:
        await research_grounded_story(
            (DownNews(),),
            SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"]),
            cast(Any, ScriptedLLM()),
            ContentProfile(),
            policy,
            now=datetime(2026, 9, 30, tzinfo=UTC),
            progress=progress,
            sleep=fake_sleep,
        )
    assert waits == [60.0, 180.0, 300.0]
    assert failure.value.code == "no_candidates"
    assert "fake/BBC: OSError (BBC unreachable)" in str(failure.value)
    assert "fake/DW: OSError (DW unreachable)" in str(failure.value)
    assert events[-1][1]["provider_warnings"] == [
        "fake/BBC: OSError (BBC unreachable)",
        "fake/DW: OSError (DW unreachable)",
    ]


def _science_fixture() -> tuple[SafeHTTPClient, ResearchPolicy]:
    article_html = (
        b"<article><title>A major science discovery</title><p>Scientists confirmed three independent results today.</p>"
        b"<p>The research team published its findings in a journal.</p></article>"
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=article_html))
    fetcher = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    policy = ResearchPolicy(
        max_candidate_articles=10,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[],
        publisher_quality={},
        blocked_publishers=[],
    )
    return fetcher, policy


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
@pytest.mark.asyncio
async def test_a_candidate_whose_articles_were_all_recent_evidence_is_rejected_as_recently_covered() -> None:
    from clipfactory.ports.research import CoveredStory
    from clipfactory.research.articles import canonicalize_url
    from clipfactory.research.pipeline import ResearchFailure

    fetcher, policy = _science_fixture()
    events: list[tuple[str, dict[str, object]]] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        events.append((message, payload))

    llm = ScriptedLLM()
    with pytest.raises(ResearchFailure) as failure:
        await research_grounded_story(
            (FakeNews(),),
            fetcher,
            llm,
            ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1)),
            policy,
            now=datetime(2026, 9, 30, tzinfo=UTC),
            recently_covered=(
                CoveredStory(
                    "Science discovery confirmed",
                    frozenset(
                        {
                            canonicalize_url("https://news.example/story"),
                            canonicalize_url("https://other.example/story"),
                        }
                    ),
                ),
            ),
            progress=progress,
        )
    assert failure.value.code == "no_suitable_story"
    # Covered evidence is excluded during discovery, so no ranking request is spent on it.
    assert llm.tasks == []
    rejection = next(payload for _, payload in events if payload.get("reason") == "recently_covered")
    assert rejection == {"reason": "recently_covered", "articles_covered": 2}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
@pytest.mark.asyncio
async def test_covered_titles_reach_the_ranking_prompt_and_an_llm_flagged_duplicate_is_not_selected() -> None:
    from clipfactory.ports.research import CoveredStory
    from clipfactory.research.pipeline import ResearchFailure

    class FlaggingLLM(ScriptedLLM):
        def __init__(self) -> None:
            super().__init__()
            self.prompts: list[str] = []

        async def generate_structured(self, task: str, messages: list[LLMMessage], schema: type[Any], **kwargs: Any):
            self.prompts.append("\n".join(message.content for message in messages))
            ranked = make_ranked()
            ranked.stories[0].recently_covered = True
            return cast(LLMResult[Any], LLMResult(ranked, "fake", "test-model"))

    fetcher, policy = _science_fixture()
    llm = FlaggingLLM()
    with pytest.raises(ResearchFailure) as failure:
        await research_grounded_story(
            (FakeNews(),),
            fetcher,
            llm,
            ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1)),
            policy,
            now=datetime(2026, 9, 30, tzinfo=UTC),
            recently_covered=(
                CoveredStory("Earlier science breakthrough", frozenset({"https://elsewhere.example/a"})),
            ),
        )
    assert failure.value.code == "no_suitable_story"
    assert '"Earlier science breakthrough"' in llm.prompts[0]
    assert "Set `recently_covered` true for a Story about the same event" in llm.prompts[0]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
@pytest.mark.asyncio
async def test_covered_evidence_articles_are_removed_and_the_rest_of_the_candidate_stays_eligible() -> None:
    from clipfactory.ports.research import CoveredStory
    from clipfactory.research.llm_tasks import RankedStory
    from clipfactory.research.pipeline import _apply_novelty  # pyright: ignore[reportPrivateUsage]
    from clipfactory.research.selection import StoryCandidate, StoryRating

    def article(url: str) -> Any:
        return SimpleNamespace(canonical_url=url)

    candidate = StoryCandidate(
        (0, 1), "Ebola spreads", "Summary.", (article("https://a.example/old"), article("https://b.example/new"))
    )
    events: list[tuple[str, dict[str, object]]] = []

    async def report(message: str, **payload: object) -> None:
        events.append((message, payload))

    checked = await _apply_novelty(
        [RankedStory(candidate, StoryRating(0.9, 0.9, False, False, ""))],
        (CoveredStory("Earlier Clip", frozenset({"https://a.example/old"})),),
        report,
    )

    assert [a.canonical_url for a in checked[0].candidate.articles] == ["https://b.example/new"]
    assert checked[0].candidate.article_indexes == (1,)
    assert checked[0].rating.recently_covered is False
    assert events[0][1] == {"reason": "recently_covered", "covered_title": "Earlier Clip"}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_collection_is_repeated_after_a_full_connectivity_outage_and_recovers() -> None:
    class WakingNews(FakeNews):
        calls = 0

        async def latest(self, query: Any) -> list[ArticleRef]:
            WakingNews.calls += 1
            if WakingNews.calls <= 1:
                raise OSError("host could not be resolved")
            return await super().latest(query)

    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    article_html = (
        b"<article><title>A major science discovery</title><p>Scientists confirmed three independent results today.</p>"
        b"<p>The research team published its findings in a journal.</p>"
        b"<p>They said the new method improved measurements significantly.</p></article>"
    )
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=article_html))
    fetcher = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    _, policy = _science_fixture()
    llm = ScriptedLLM()
    result = await research_grounded_story(
        (WakingNews(),),
        fetcher,
        llm,
        ContentProfile(research=ProfileResearchPolicy(min_sources=1, preferred_independent_sources=1)),
        policy,
        now=datetime(2026, 9, 30, tzinfo=UTC),
        sleep=fake_sleep,
    )
    assert waits == [60.0]
    assert result.claims
