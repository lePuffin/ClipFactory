import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from clipfactory.domain.models import ClaimKind, ClaimStatus
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.ports.news import ArticleRef
from clipfactory.research.discovery import RetrievedArticle
from clipfactory.research.grounding import ClaimEvidenceDraft, GroundedSource
from clipfactory.research.llm_tasks import (
    ExtractClaimsResult,
    ExtractedClaimDraft,
    RankedStoryDraft,
    RankStoriesResult,
    extract_story_claims,
    rank_story_candidates,
)
from clipfactory.research.selection import precluster_articles


class ScriptedLLM:
    name = "fake"

    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls: list[tuple[str, list[LLMMessage]]] = []

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
        self.calls.append((task, messages))
        return cast(LLMResult[Any], LLMResult(self.value, "fake", "test-model"))


def fetched(index: int, title: str, text: str) -> RetrievedArticle:
    url = f"https://news{index}.example/article"
    reference = ArticleRef(url, title, f"Publisher {index}", datetime(2026, 9, 30, tzinfo=UTC))
    return RetrievedArticle(reference, url, title, text, None, f"hash-{index}", "high")


def source(index: int, text: str, tier: str = "high") -> GroundedSource:
    article = fetched(index, f"Report {index}", text)
    article = RetrievedArticle(
        article.reference, article.canonical_url, article.title, article.text, None, article.text_hash, tier
    )
    return GroundedSource(uuid4(), article, article.reference.publisher)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-105")
@pytest.mark.req("CF-REQ-107")
@pytest.mark.asyncio
async def test_rank_stories_makes_one_call_and_validates_merge_partition() -> None:
    articles = [
        fetched(
            1, "Flood damages bridge after storm", "Rising flood water damages a bridge after severe overnight rain."
        ),
        fetched(2, "River flooding closes northern crossing", "River flooding shuts a key road crossing in the north."),
        fetched(3, "Bank changes rates", "Central bank changes the national interest rate."),
    ]
    candidates = precluster_articles(articles)
    llm = ScriptedLLM(
        RankStoriesResult(
            stories=[
                RankedStoryDraft(
                    candidate_indexes=[0, 1],
                    title="Bridge flooding",
                    summary="Floodwater closed a bridge.",
                    profile_relevance=0.9,
                    newsworthiness=0.8,
                    rationale="Wide impact",
                ),
                RankedStoryDraft(
                    candidate_indexes=[2],
                    title="Interest rate decision",
                    summary="The central bank changed its rate.",
                    profile_relevance=0.8,
                    newsworthiness=0.7,
                    rationale="Economic impact",
                ),
            ]
        )
    )
    result = await rank_story_candidates(llm, candidates, topics=["world"], excluded_topics=[])
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "rank_stories"
    assert result[0].candidate.article_indexes == (0, 1)
    assert len(result[0].candidate.articles) == 2
    assert "<untrusted-story-candidates>" in llm.calls[0][1][1].content


class SequencedLLM(ScriptedLLM):
    def __init__(self, values: list[Any]) -> None:
        super().__init__(None)
        self.values = values

    async def generate_structured(self, task: str, messages: list[LLMMessage], schema: type[Any], **kwargs: Any):
        self.calls.append((task, messages))
        return cast(LLMResult[Any], LLMResult(self.values[len(self.calls) - 1], "fake", "test-model"))


def ranked(*groups: list[int]) -> RankStoriesResult:
    return RankStoriesResult(
        stories=[
            RankedStoryDraft(
                candidate_indexes=group,
                title=f"Story {index}",
                summary="Summary.",
                profile_relevance=0.5,
                newsworthiness=0.5,
                rationale="Reason",
            )
            for index, group in enumerate(groups)
        ]
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-105")
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_rank_stories_repairs_invalid_grouping_once_with_specific_errors() -> None:
    articles = [
        fetched(1, "Flood", "Flood water."),
        fetched(2, "Rates", "Bank rates."),
        fetched(3, "Vote", "Election."),
    ]
    candidates = precluster_articles(articles)
    llm = SequencedLLM([ranked([0, 7], [0]), ranked([0], [1, 2])])

    result = await rank_story_candidates(llm, candidates, topics=[], excluded_topics=[])

    assert len(llm.calls) == 2
    repair_request = llm.calls[1][1][-1].content
    assert "unknown candidate_index values [7]" in repair_request
    assert "used more than once [0]" in repair_request
    assert "missing candidate_index values [1, 2]" in repair_request
    assert [item.candidate.article_indexes for item in result] == [(0,), (1, 2)]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_rank_stories_fails_as_invalid_llm_output_after_repairs() -> None:
    articles = [fetched(1, "Flood", "Flood water."), fetched(2, "Rates", "Bank rates.")]
    llm = SequencedLLM([ranked([5]), ranked([5])])

    with pytest.raises(ProviderError) as caught:
        await rank_story_candidates(llm, precluster_articles(articles), topics=[], excluded_topics=[])

    assert caught.value.code == "llm_invalid_output"
    assert "missing candidate_index values [0, 1]" in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-112")
@pytest.mark.req("CF-REQ-113")
@pytest.mark.req("CF-REQ-151")
@pytest.mark.asyncio
async def test_extract_claims_verifies_excerpts_and_returns_key_fact_ids() -> None:
    grounded = source(1, "The city opened a new bridge on Tuesday. The bridge cost 12 million dollars.")
    llm = ScriptedLLM(
        ExtractClaimsResult(
            claims=[
                ExtractedClaimDraft(
                    ref="c1",
                    text="The city opened a bridge.",
                    kind=ClaimKind.FACT,
                    evidence=[ClaimEvidenceDraft(source_id=grounded.id, excerpt="opened a new bridge")],
                ),
                ExtractedClaimDraft(
                    ref="c2",
                    text="The bridge cost 12 million dollars.",
                    kind=ClaimKind.FIGURE,
                    evidence=[ClaimEvidenceDraft(source_id=grounded.id, excerpt="cost 12 million dollars")],
                ),
                ExtractedClaimDraft(
                    ref="c3",
                    text="The bridge opened in 2024.",
                    kind=ClaimKind.FACT,
                    evidence=[ClaimEvidenceDraft(source_id=grounded.id, excerpt="opened in 2024")],
                ),
            ],
            key_fact_refs=["c1", "c2", "c3"],
            refined_title="New city bridge opens",
            refined_summary="The city opened a new bridge.",
        )
    )
    claims, key_fact_ids, title, summary = await extract_story_claims(llm, uuid4(), [grounded], max_input_chars=10_000)
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "extract_claims"
    assert claims[0].status == ClaimStatus.ACCEPTED
    assert claims[0].evidence[0].verified
    assert claims[2].status == ClaimStatus.REJECTED
    assert len(key_fact_ids) == 2
    assert title == "New city bridge opens"
    assert summary == "The city opened a new bridge."


@pytest.mark.unit
@pytest.mark.req("CF-REQ-112")
@pytest.mark.asyncio
async def test_claim_input_drops_low_quality_source_before_truncating_high_quality() -> None:
    long_text = "High quality source paragraph. " * 35
    high = source(1, long_text, "high")
    low = source(2, "LOW-QUALITY-SOURCE " + long_text, "low")
    llm = ScriptedLLM(
        ExtractClaimsResult(claims=[], key_fact_refs=[], refined_title="Title", refined_summary="Summary")
    )
    await extract_story_claims(llm, uuid4(), [high, low], max_input_chars=800)
    payload = json.loads(llm.calls[0][1][1].content.split("\n", maxsplit=1)[1].rsplit("\n<", maxsplit=1)[0])
    assert len(payload) == 1
    assert "LOW-QUALITY-SOURCE" not in payload[0]["text"]
    assert len(payload[0]["text"]) <= 800


def claims_result(grounded: GroundedSource, key_fact_refs: list[str], contradictions: list[list[str]]):
    return ExtractClaimsResult(
        claims=[
            ExtractedClaimDraft(
                ref=f"c{index}",
                text=text,
                kind=ClaimKind.FACT,
                evidence=[ClaimEvidenceDraft(source_id=grounded.id, excerpt=excerpt)],
            )
            for index, (text, excerpt) in enumerate(
                (("A bridge opened.", "opened a new bridge"), ("It cost 12 million.", "cost 12 million dollars")),
                start=1,
            )
        ],
        key_fact_refs=key_fact_refs,
        contradictions=contradictions,
        refined_title="Bridge",
        refined_summary="A bridge opened.",
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-151")
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_extract_claims_repairs_unknown_claim_refs_with_specific_errors() -> None:
    grounded = source(1, "The city opened a new bridge on Tuesday. The bridge cost 12 million dollars.")
    llm = SequencedLLM(
        [claims_result(grounded, ["c2", "c3"], [["c0", "c1"]]), claims_result(grounded, ["c2", "c1"], [])]
    )

    claims, key_fact_ids, _, _ = await extract_story_claims(llm, uuid4(), [grounded], max_input_chars=10_000)

    assert len(llm.calls) == 2
    repair_request = llm.calls[1][1][-1].content
    assert "unknown key_fact_refs ['c3']" in repair_request
    assert "unknown refs in contradictions ['c0']" in repair_request
    assert key_fact_ids == [claims[1].id, claims[0].id]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_extract_claims_fails_as_invalid_llm_output_after_repairs() -> None:
    grounded = source(1, "The city opened a new bridge on Tuesday. The bridge cost 12 million dollars.")
    llm = SequencedLLM([claims_result(grounded, ["c9"], []), claims_result(grounded, ["c9"], [])])

    with pytest.raises(ProviderError) as caught:
        await extract_story_claims(llm, uuid4(), [grounded], max_input_chars=10_000)

    assert caught.value.code == "llm_invalid_output"
    assert "unknown key_fact_refs ['c9']" in str(caught.value)
