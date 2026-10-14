"""Deterministic Manual URL ingestion into the grounded research model."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from clipfactory.domain.models import Claim, ContentProfile
from clipfactory.ports.llm import LLMProvider
from clipfactory.ports.news import ArticleRef
from clipfactory.ports.research import (
    ClaimExtractionRepository,
    ResearchRepository,
    ResearchSnapshot,
    ResearchSourceRecord,
    ResearchStoryRecord,
)
from clipfactory.research.articles import extract_article
from clipfactory.research.discovery import ByteFetcher, RetrievedArticle
from clipfactory.research.grounding import GroundedSource
from clipfactory.research.llm_tasks import extract_story_claims


class ManualURLFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ManualURLResult:
    story_id: UUID
    source_id: UUID
    title: str


@dataclass(frozen=True, slots=True)
class ManualURLClaimsResult:
    story_id: UUID
    claims: tuple[Claim, ...]


class ManualURLIngest:
    def __init__(self, fetcher: ByteFetcher, repository: ResearchRepository) -> None:
        self._fetcher = fetcher
        self._repository = repository

    async def execute(
        self,
        run_id: UUID,
        url: str,
        profile: ContentProfile,
        *,
        now: datetime,
        max_article_bytes: int,
        publisher_quality: dict[str, str],
    ) -> ManualURLResult:
        try:
            payload, final_url, _headers = await self._fetcher.get_bytes(url, max_bytes=max_article_bytes)
        except Exception as exc:
            raise ManualURLFailure("url_unreachable", "The URL could not be retrieved") from exc

        try:
            article = extract_article(payload.decode("utf-8", errors="replace"), final_url)
        except (TypeError, ValueError) as exc:
            raise ManualURLFailure("url_not_article", "The response is not an extractable article") from exc
        title = article["title"]
        text = article["text"]
        canonical_url = article["canonical_url"]
        text_hash = article["text_hash"]
        if not title or not text or not canonical_url or not text_hash:
            raise ManualURLFailure("url_not_article", "The response is not an extractable article")

        host = (urlsplit(canonical_url).hostname or "").casefold()
        blocked = {value.casefold() for value in profile.research.blocked_publishers}
        quality_tier = publisher_quality.get(host, "standard")
        if host in blocked or quality_tier == "blocked":
            raise ManualURLFailure("url_blocked_source", "The publisher is blocked by the Content Profile")

        source_id = uuid4()
        story_id = uuid4()
        source = ResearchSourceRecord(
            id=source_id,
            url=final_url,
            canonical_url=canonical_url,
            publisher=host,
            origin_publisher=host,
            title=title,
            text=text,
            text_hash=text_hash,
            quality_tier=quality_tier,
            retrieved_at=now,
            published_at=None,
            author=article["author"],
            syndication_of=None,
        )
        story = ResearchStoryRecord(
            id=story_id,
            status="selected",
            title=title,
            summary=_lead(text),
            category=profile.category.value,
            selection_score=None,
            score_breakdown=None,
            selection_rationale="Owner-selected Manual URL",
            rejection_reason=None,
            source_ids=(source_id,),
        )
        await asyncio.to_thread(
            self._repository.persist,
            ResearchSnapshot(
                run_id=run_id,
                sources=(source,),
                stories=(story,),
                selected_story_id=story_id,
                claims=(),
            ),
        )
        return ManualURLResult(story_id=story_id, source_id=source_id, title=title)


class ManualURLClaimExtractor:
    def __init__(self, llm: LLMProvider, repository: ClaimExtractionRepository) -> None:
        self._llm = llm
        self._repository = repository

    async def execute(self, run_id: UUID, *, max_input_chars: int) -> ManualURLClaimsResult:
        context = await asyncio.to_thread(self._repository.selected_story_context, run_id)
        sources = tuple(_grounded_source(source) for source in context.sources)
        claims, key_fact_ids, title, summary = await extract_story_claims(
            self._llm,
            context.story_id,
            sources,
            max_input_chars=max_input_chars,
        )
        if sum(claim.status.value == "accepted" for claim in claims) < 3:
            raise ManualURLFailure(
                "insufficient_claims", "The selected Story produced fewer than three accepted Claims"
            )
        await asyncio.to_thread(
            self._repository.persist_claims,
            context.story_id,
            tuple(claims),
            tuple(key_fact_ids),
            title,
            summary,
        )
        return ManualURLClaimsResult(story_id=context.story_id, claims=tuple(claims))


def _lead(text: str) -> str:
    sentence_end = text.find(".")
    if 0 <= sentence_end < 499:
        return text[: sentence_end + 1]
    return text[:500]


def _grounded_source(source: ResearchSourceRecord) -> GroundedSource:
    reference = ArticleRef(
        url=source.url,
        title=source.title,
        publisher=source.publisher,
        published_at=source.published_at,
    )
    article = RetrievedArticle(
        reference=reference,
        canonical_url=source.canonical_url,
        title=source.title,
        text=source.text,
        author=source.author,
        text_hash=source.text_hash,
        quality_tier=source.quality_tier,
    )
    return GroundedSource(
        id=source.id,
        article=article,
        origin_publisher=source.origin_publisher,
        syndication_of=source.syndication_of,
    )
