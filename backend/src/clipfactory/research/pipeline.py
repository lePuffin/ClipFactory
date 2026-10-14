"""Research-stage orchestration from news references through accepted Claims."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from math import ceil
from uuid import UUID, uuid4

from clipfactory.domain.models import Claim, ContentProfile
from clipfactory.ports.llm import LLMProvider
from clipfactory.ports.news import NewsSource
from clipfactory.ports.research import CoveredStory, ResearchSnapshot, ResearchSourceRecord, ResearchStoryRecord
from clipfactory.research.discovery import ByteFetcher, ResearchPolicy, ResearchResult, research_articles
from clipfactory.research.grounding import GroundedSource, detect_syndication, independent_source_count
from clipfactory.research.llm_tasks import RankedStory, extract_story_claims, rank_story_candidates
from clipfactory.research.selection import ScoredStory, SelectionWeights, precluster_articles, score_stories


class ResearchFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ProgressSink = Callable[[str, dict[str, object]], Awaitable[None]]

MIN_CLAIMS = 3
EVIDENCE_WORD_RATIO = 0.4


def minimum_evidence_words(profile: ContentProfile) -> int:
    """Accepted-Claim words needed to narrate the minimum duration without invented padding."""
    minimum_narration_words = profile.duration.min_seconds * profile.voice.words_per_minute / 60
    return ceil(minimum_narration_words * EVIDENCE_WORD_RATIO)


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


async def _apply_novelty(
    ranked: list[RankedStory],
    recently_covered: tuple[CoveredStory, ...],
    report: Callable[..., Awaitable[None]],
) -> list[RankedStory]:
    """CF-REQ-109: drop covered evidence articles and reject candidates judged the same as a recent Story."""
    covered_by_url = {url: story.title for story in recently_covered for url in story.canonical_urls}
    checked: list[RankedStory] = []
    for item in ranked:
        title = item.candidate.title
        candidate = item.candidate
        kept = tuple(
            (index, article)
            for index, article in zip(candidate.article_indexes, candidate.articles, strict=True)
            if article.canonical_url not in covered_by_url
        )
        if len(kept) < len(candidate.articles):
            shared = next(
                covered_by_url[a.canonical_url] for a in candidate.articles if a.canonical_url in covered_by_url
            )
            candidate = replace(
                candidate,
                article_indexes=tuple(index for index, _ in kept),
                articles=tuple(article for _, article in kept),
            )
            if not kept:
                await report(
                    f"Skipping '{title}': recently_covered (all its articles were evidence for the recent Clip "
                    f"'{shared}')",
                    reason="recently_covered",
                    covered_title=shared,
                )
                checked.append(RankedStory(candidate, replace(item.rating, recently_covered=True)))
                continue
            await report(
                f"Removed {len(item.candidate.articles) - len(kept)} article(s) from '{title}' already used as "
                f"evidence for the recent Clip '{shared}'",
                reason="recently_covered",
                covered_title=shared,
            )
        if item.rating.recently_covered:
            await report(
                f"Skipping '{title}': recently_covered (judged the same Story as a recent Clip)",
                reason="recently_covered",
            )
        checked.append(RankedStory(candidate, item.rating))
    return checked


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
    recently_covered: tuple[CoveredStory, ...] = (),
    max_claim_input_chars: int = 60_000,
    progress: ProgressSink | None = None,
    outage_retry_delays_seconds: tuple[float, ...] = (60.0, 180.0, 300.0),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> GroundedStoryResult:
    async def report(message: str, **payload: object) -> None:
        if progress is not None:
            await progress(message, payload)

    await report(f"Collecting articles from {len(policy.feeds)} feeds")
    excluded_urls = {url for story in recently_covered for url in story.canonical_urls}
    research_result = await research_articles(news_sources, fetcher, policy, now=now, excluded_urls=excluded_urls)
    for delay in outage_retry_delays_seconds:
        if research_result.references_seen or not research_result.provider_warnings:
            break
        # Every source failed: treat it as a host connectivity outage and collect again later (CF-REQ-100).
        await report(
            f"Every news source failed; retrying collection in {delay:.0f} s",
            provider_warnings=list(research_result.provider_warnings),
            retry_in_seconds=delay,
        )
        await sleep(delay)
        research_result = await research_articles(news_sources, fetcher, policy, now=now, excluded_urls=excluded_urls)
    await report(
        f"Fetched {len(research_result.articles)} usable articles from {research_result.references_seen} references "
        f"({research_result.articles_skipped} skipped)",
        articles_fetched=len(research_result.articles),
        references_seen=research_result.references_seen,
        articles_skipped=research_result.articles_skipped,
    )
    if research_result.provider_warnings:
        await report(
            f"{len(research_result.provider_warnings)} news source(s) failed: "
            + "; ".join(research_result.provider_warnings)[:900],
            provider_warnings=list(research_result.provider_warnings),
        )
    if research_result.articles_covered:
        await report(
            f"Skipped {research_result.articles_covered} article(s) already used as evidence for recent Clips",
            reason="recently_covered",
            articles_covered=research_result.articles_covered,
        )
    if not research_result.articles and research_result.articles_covered:
        raise ResearchFailure("no_suitable_story", "Every retrieved article was evidence for a recent Clip")
    if not research_result.articles:
        detail = "; ".join(research_result.provider_warnings)[:900]
        raise ResearchFailure(
            "no_candidates",
            "No usable article candidates were retrieved" + (f". Source errors: {detail}" if detail else ""),
        )

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
        profile_category=profile.category,
        recently_covered_titles=tuple(story.title for story in recently_covered),
    )
    ranked = await _apply_novelty(ranked, recently_covered, report)
    for item in ranked:
        if profile.category.value != "general" and item.candidate.category != profile.category:
            await report(
                f"Skipping '{item.candidate.title}': category_mismatch "
                f"({item.candidate.category.value}, profile {profile.category.value})",
                reason="category_mismatch",
                category=item.candidate.category.value,
                profile_category=profile.category.value,
            )
    scored = score_stories(
        [item.candidate for item in ranked],
        [item.rating for item in ranked],
        now=now,
        max_article_age_hours=profile.research.max_article_age_hours,
        preferred_independent_sources=profile.research.preferred_independent_sources,
        weights=selection_weights or SelectionWeights(),
        profile_category=profile.category,
    )
    if not scored:
        raise ResearchFailure("no_suitable_story", "All Story candidates were excluded by profile or novelty rules")
    await report(
        "Top Story candidates: "
        + "; ".join(f"{index}. {item.candidate.title} ({item.score:.2f})" for index, item in enumerate(scored[:3], 1))
    )

    required_evidence_words = minimum_evidence_words(profile)
    fallbacks_used = 0
    for scored_story in scored:
        if fallbacks_used > story_fallback_limit:
            break
        title = scored_story.candidate.title
        candidate_sources = detect_syndication(
            scored_story.candidate.articles, threshold=profile.research.near_duplicate_threshold
        )
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
        evidence_words = sum(len(claim.text.split()) for claim in accepted_claims)
        shortfall = ""
        if len(accepted_claims) < MIN_CLAIMS:
            shortfall = f"; at least {MIN_CLAIMS} needed, trying the next Story"
        elif evidence_words < required_evidence_words:
            shortfall = (
                f"; only {evidence_words} words of accepted evidence, {required_evidence_words} needed "
                "to fill the minimum duration, trying the next Story"
            )
        await report(
            f"'{title}': {len(accepted_claims)} Claims accepted, {len(claims) - len(accepted_claims)} rejected"
            + shortfall
        )
        if not shortfall:
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
    raise ResearchFailure(
        "insufficient_claims", "No eligible Story produced enough accepted Claims to fill the minimum duration"
    )


def make_research_snapshot(
    result: GroundedStoryResult,
    *,
    run_id: UUID,
    now: datetime,
    near_duplicate_threshold: float = 0.8,
) -> ResearchSnapshot:
    selected_source_ids = {source.article.canonical_url: source.id for source in result.sources}
    grounded_sources = detect_syndication(
        result.research.articles, source_ids=selected_source_ids, threshold=near_duplicate_threshold
    )
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
    selected_rank = next(
        index
        for index, scored in enumerate(result.candidates)
        if {article.canonical_url for article in scored.candidate.articles} == selected_urls
    )
    for rank, scored in enumerate(result.candidates):
        candidate_urls = {article.canonical_url for article in scored.candidate.articles}
        is_selected = candidate_urls == selected_urls
        candidate_source_ids = tuple(source_id_by_url[url] for url in candidate_urls if url in source_id_by_url)
        story_records.append(
            ResearchStoryRecord(
                id=result.story_id if is_selected else uuid4(),
                status="selected" if is_selected else "rejected",
                title=result.title if is_selected else scored.candidate.title,
                summary=result.summary if is_selected else scored.candidate.summary,
                category=scored.candidate.category.value,
                selection_score=scored.score,
                score_breakdown={**scored.breakdown, "candidate_rank": rank},
                selection_rationale=scored.rationale,
                rejection_reason=None
                if is_selected
                else ("grounding_failed" if rank < selected_rank else "lower_selection_score"),
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
