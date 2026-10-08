"""Research-stage orchestration from news references through accepted Claims."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from clipfactory.domain.models import Claim, ContentProfile
from clipfactory.ports.llm import LLMProvider
from clipfactory.ports.news import NewsSource
from clipfactory.ports.research import ResearchSnapshot, ResearchSourceRecord, ResearchStoryRecord
from clipfactory.research.discovery import ByteFetcher, ResearchPolicy, ResearchResult, research_articles
from clipfactory.research.grounding import GroundedSource, detect_syndication, independent_source_count
from clipfactory.research.llm_tasks import extract_story_claims, rank_story_candidates
from clipfactory.research.selection import ScoredStory, SelectionWeights, precluster_articles, score_stories


class ResearchFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ProgressSink = Callable[[str, dict[str, object]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class GroundedStoryResult:
    story_id: UUID
    title: str
    summary: str
    sources: tuple[GroundedSource, ...]
    claims: tuple[Claim, ...]
    key_fact_claim_ids: tuple[UUID, ...]
    candidates: tuple[ScoredStory, ...]
    research: ResearchResult
    fallback_index: int


async def research_grounded_story(
    news_sources: tuple[NewsSource, ...],
    fetcher: ByteFetcher,
    llm: LLMProvider,
    profile: ContentProfile,
    policy: ResearchPolicy,
    *,
    now: datetime,
    selection_weights: SelectionWeights | None = None,
    story_fallback_limit: int = 2,
    recently_covered_titles: tuple[str, ...] = (),
    max_claim_input_chars: int = 60_000,
    progress: ProgressSink | None = None,
) -> GroundedStoryResult:
    async def report(message: str, **payload: object) -> None:
        if progress is not None:
            await progress(message, payload)

    await report(f"Collecting articles from {len(policy.feeds)} feeds")
    research_result = await research_articles(news_sources, fetcher, policy, now=now)
    await report(
        f"Fetched {len(research_result.articles)} usable articles from {research_result.references_seen} references "
        f"({research_result.articles_skipped} skipped)",
        articles_fetched=len(research_result.articles),
        references_seen=research_result.references_seen,
        articles_skipped=research_result.articles_skipped,
    )
    if not research_result.articles:
        raise ResearchFailure("no_candidates", "No usable article candidates were retrieved")

    pre_groups = precluster_articles(research_result.articles)
    await report(
        f"Grouped articles into {len(pre_groups)} candidate Stories; asking the LLM to merge and rate them",
        story_candidates=len(pre_groups),
    )
    ranked = await rank_story_candidates(
        llm,
        pre_groups,
        topics=profile.topics,
        excluded_topics=profile.excluded_topics,
        recently_covered_titles=recently_covered_titles,
    )
    scored = score_stories(
        [item.candidate for item in ranked],
        [item.rating for item in ranked],
        now=now,
        max_article_age_hours=profile.research.max_article_age_hours,
        preferred_independent_sources=profile.research.preferred_independent_sources,
        weights=selection_weights or SelectionWeights(),
    )
    if not scored:
        raise ResearchFailure("no_suitable_story", "All Story candidates were excluded by profile or novelty rules")
    await report(
        "Top Story candidates: "
        + "; ".join(f"{index}. {item.candidate.title} ({item.score:.2f})" for index, item in enumerate(scored[:3], 1))
    )

    fallbacks_used = 0
    for scored_story in scored:
        if fallbacks_used > story_fallback_limit:
            break
        title = scored_story.candidate.title
        candidate_sources = detect_syndication(scored_story.candidate.articles)
        independent = independent_source_count(candidate_sources)
        if independent < profile.research.min_sources:
            await report(
                f"Skipping '{title}': {independent} independent Sources, {profile.research.min_sources} required"
            )
            fallbacks_used += 1
            continue
        await report(f"Extracting Claims for '{title}' from {len(candidate_sources)} Sources")
        story_id = uuid4()
        claims, key_fact_ids, refined_title, refined_summary = await extract_story_claims(
            llm,
            story_id,
            candidate_sources,
            max_input_chars=max_claim_input_chars,
            story_title=title,
            story_summary=scored_story.candidate.summary,
        )
        accepted_claims = [claim for claim in claims if claim.status.value == "accepted"]
        await report(
            f"'{title}': {len(accepted_claims)} Claims accepted, {len(claims) - len(accepted_claims)} rejected"
            + ("" if len(accepted_claims) >= 3 else "; at least 3 needed, trying the next Story")
        )
        if len(accepted_claims) >= 3:
            return GroundedStoryResult(
                story_id=story_id,
                title=refined_title,
                summary=refined_summary,
                sources=tuple(candidate_sources),
                claims=tuple(claims),
                key_fact_claim_ids=tuple(key_fact_ids),
                candidates=tuple(scored),
                research=research_result,
                fallback_index=fallbacks_used,
            )
        fallbacks_used += 1
    raise ResearchFailure("insufficient_claims", "No eligible Story produced at least three accepted Claims")


def make_research_snapshot(
    result: GroundedStoryResult,
    *,
    run_id: UUID,
    category: str,
    now: datetime,
) -> ResearchSnapshot:
    selected_source_ids = {source.article.canonical_url: source.id for source in result.sources}
    grounded_sources = detect_syndication(result.research.articles, source_ids=selected_source_ids)
    sources = tuple(
        ResearchSourceRecord(
            id=source.id,
            url=source.article.reference.url,
            canonical_url=source.article.canonical_url,
            publisher=source.article.reference.publisher,
            origin_publisher=source.origin_publisher,
            title=source.article.title,
            text=source.article.text,
            text_hash=source.article.text_hash,
            quality_tier=source.article.quality_tier,
            retrieved_at=now,
            published_at=source.article.reference.published_at,
            author=source.article.author,
            syndication_of=source.syndication_of,
        )
        for source in grounded_sources
    )
    source_id_by_url = {source.canonical_url: source.id for source in sources}
    selected_urls = {source.article.canonical_url for source in result.sources}
    story_records: list[ResearchStoryRecord] = []
    for scored in result.candidates:
        candidate_urls = {article.canonical_url for article in scored.candidate.articles}
        is_selected = candidate_urls == selected_urls
        candidate_source_ids = tuple(source_id_by_url[url] for url in candidate_urls if url in source_id_by_url)
        story_records.append(
            ResearchStoryRecord(
                id=result.story_id if is_selected else uuid4(),
                status="selected" if is_selected else "rejected",
                title=result.title if is_selected else scored.candidate.title,
                summary=result.summary if is_selected else scored.candidate.summary,
                category=category,
                selection_score=scored.score,
                score_breakdown=scored.breakdown,
                selection_rationale=scored.rationale,
                rejection_reason=None if is_selected else "lower_selection_score",
                source_ids=candidate_source_ids,
            )
        )
    if not any(story.id == result.story_id for story in story_records):
        raise ValueError("selected Story is missing from research candidates")
    return ResearchSnapshot(
        run_id=run_id,
        sources=sources,
        stories=tuple(story_records),
        selected_story_id=result.story_id,
        claims=result.claims,
        key_fact_claim_ids=result.key_fact_claim_ids,
    )
