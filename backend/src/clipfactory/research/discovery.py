"""Deterministic news reference selection and safe article retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from clipfactory.ports.news import ArticleRef, NewsQuery, NewsSource
from clipfactory.research.articles import extract_article


class ByteFetcher(Protocol):
    async def get_bytes(self, url: str, *, max_bytes: int) -> tuple[bytes, str, object]: ...


@dataclass(frozen=True, slots=True)
class ResearchPolicy:
    max_candidate_articles: int
    max_article_age_hours: int
    max_article_bytes: int
    feeds: list[tuple[str, str]]
    publisher_quality: dict[str, str]
    blocked_publishers: list[str]
    allowed_publishers: list[str] | None = None
    excluded_topics: list[str] | None = None
    preferred_topics: list[str] | None = None


@dataclass(frozen=True, slots=True)
class RetrievedArticle:
    reference: ArticleRef
    canonical_url: str
    title: str
    text: str
    author: str | None
    text_hash: str
    quality_tier: str


@dataclass(frozen=True, slots=True)
class ResearchResult:
    references_seen: int
    articles_skipped: int
    articles: tuple[RetrievedArticle, ...]
    provider_warnings: tuple[str, ...]


async def research_articles(
    news_sources: Sequence[NewsSource],
    fetcher: ByteFetcher,
    policy: ResearchPolicy,
    *,
    now: datetime,
) -> ResearchResult:
    references: list[ArticleRef] = []
    warnings: list[str] = []
    query = _FeedQuery(policy.feeds)
    for source in news_sources:
        try:
            references.extend(await source.latest(query))
        except Exception as exc:
            warnings.append(f"{source.name}: {type(exc).__name__}")

    eligible = [ref for ref in references if _eligible_reference(ref, policy, now)]
    ranked = sorted(eligible, key=lambda ref: _rank_key(ref, policy), reverse=True)
    chosen = ranked[: policy.max_candidate_articles]
    skipped = len(references) - len(chosen)
    articles: list[RetrievedArticle] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()

    for reference in chosen:
        try:
            payload, final_url, _ = await fetcher.get_bytes(reference.url, max_bytes=policy.max_article_bytes)
            extracted = extract_article(payload.decode("utf-8", errors="replace"), final_url)
        except Exception as exc:
            warnings.append(f"article retrieval skipped: {type(exc).__name__}")
            skipped += 1
            continue
        title = extracted["title"] or reference.title.strip()
        text = extracted["text"] or ""
        canonical = extracted["canonical_url"]
        text_hash = extracted["text_hash"]
        if not title or not text or not canonical or not text_hash:
            skipped += 1
            continue
        if canonical in seen_urls or text_hash in seen_hashes:
            continue
        seen_urls.add(canonical)
        seen_hashes.add(text_hash)
        quality_tier = _quality_tier(reference, policy, text)
        articles.append(
            RetrievedArticle(
                reference=reference,
                canonical_url=canonical,
                title=title,
                text=text,
                author=extracted["author"],
                text_hash=text_hash,
                quality_tier=quality_tier,
            )
        )
    return ResearchResult(len(references), skipped, tuple(articles), tuple(warnings))


class _FeedQuery(NewsQuery):
    def __init__(self, feeds: list[tuple[str, str]]) -> None:
        self.feeds = feeds


def _eligible_reference(reference: ArticleRef, policy: ResearchPolicy, now: datetime) -> bool:
    publisher = reference.publisher.casefold()
    host = (urlsplit(reference.url).hostname or "").casefold()
    blocked = {item.casefold() for item in policy.blocked_publishers}
    if publisher in blocked or host in blocked or policy.publisher_quality.get(host, "standard") == "blocked":
        return False
    allowed = {item.casefold() for item in policy.allowed_publishers or []}
    if allowed and publisher not in allowed and host not in allowed:
        return False
    if reference.published_at is not None:
        published_at = reference.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=now.tzinfo)
        if (now - published_at).total_seconds() > policy.max_article_age_hours * 3600:
            return False
    excluded = [topic.casefold() for topic in policy.excluded_topics or []]
    text = f"{reference.title} {reference.summary}".casefold()
    return not any(topic and topic in text for topic in excluded)


def _rank_key(reference: ArticleRef, policy: ResearchPolicy) -> tuple[float, int, float, str]:
    host = (urlsplit(reference.url).hostname or "").casefold()
    tier_score = {"high": 3.0, "standard": 2.0, "low": 1.0}.get(policy.publisher_quality.get(host, "standard"), 0.0)
    preferred = {topic.casefold() for topic in policy.preferred_topics or []}
    overlap = sum(topic in f"{reference.title} {reference.summary}".casefold() for topic in preferred)
    published = reference.published_at.timestamp() if reference.published_at else 0.0
    return tier_score, overlap, published, reference.title.casefold()


def _quality_tier(reference: ArticleRef, policy: ResearchPolicy, text: str) -> str:
    host = (urlsplit(reference.url).hostname or "").casefold()
    tier = policy.publisher_quality.get(host, "standard")
    word_count = len(text.split())
    if tier == "high" and (word_count < 150 or reference.published_at is None):
        return "standard"
    if tier == "standard" and (word_count < 150 or reference.published_at is None):
        return "low"
    if tier == "low" and (word_count < 150 or reference.published_at is None):
        return "blocked"
    return tier
