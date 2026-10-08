"""Deterministic Story pre-clustering and weighted candidate selection."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from clipfactory.research.discovery import RetrievedArticle


@dataclass(frozen=True, slots=True)
class StoryCandidate:
    article_indexes: tuple[int, ...]
    title: str
    summary: str
    articles: tuple[RetrievedArticle, ...]

    @property
    def newest_published_at(self) -> datetime | None:
        published = [article.reference.published_at for article in self.articles if article.reference.published_at]
        return max(published) if published else None

    @property
    def independent_source_count(self) -> int:
        return len({article.reference.publisher.casefold() for article in self.articles})


@dataclass(frozen=True, slots=True)
class StoryRating:
    profile_relevance: float
    newsworthiness: float
    excluded_topic: bool = False
    recently_covered: bool = False
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class SelectionWeights:
    profile_relevance: float = 0.30
    newsworthiness: float = 0.25
    independent_sources: float = 0.20
    source_quality: float = 0.15
    recency: float = 0.10

    def validate(self) -> None:
        values = (
            self.profile_relevance,
            self.newsworthiness,
            self.independent_sources,
            self.source_quality,
            self.recency,
        )
        if any(value < 0 for value in values) or abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("selection weights must be non-negative and sum to 1")


@dataclass(frozen=True, slots=True)
class ScoredStory:
    candidate: StoryCandidate
    score: float
    breakdown: dict[str, float]
    rationale: str


def precluster_articles(
    articles: Sequence[RetrievedArticle], *, similarity_threshold: float = 0.35
) -> list[StoryCandidate]:
    """Group articles with similar title and lead terms; every input appears once."""
    groups: list[list[int]] = []
    for index, article in enumerate(articles):
        terms = _terms(f"{article.title} {article.text[:500]}")
        matching_group = next(
            (
                group
                for group in groups
                if _jaccard(
                    terms,
                    _terms(f"{articles[group[0]].title} {articles[group[0]].text[:500]}"),
                )
                >= similarity_threshold
            ),
            None,
        )
        if matching_group is None:
            groups.append([index])
        else:
            matching_group.append(index)
    return [
        StoryCandidate(
            article_indexes=tuple(group),
            title=articles[group[0]].title,
            summary=_lead(articles[group[0]].text),
            articles=tuple(articles[index] for index in group),
        )
        for group in groups
    ]


def validate_article_partition(groups: Sequence[Sequence[int]], article_count: int) -> None:
    flattened = [index for group in groups for index in group]
    if sorted(flattened) != list(range(article_count)):
        raise ValueError("Story partition must contain every article index exactly once")


def score_stories(
    candidates: Sequence[StoryCandidate],
    ratings: Sequence[StoryRating],
    *,
    now: datetime,
    max_article_age_hours: float,
    preferred_independent_sources: int,
    weights: SelectionWeights | None = None,
) -> list[ScoredStory]:
    if len(candidates) != len(ratings):
        raise ValueError("every Story candidate requires one rating")
    if max_article_age_hours <= 0 or preferred_independent_sources <= 0:
        raise ValueError("research scoring bounds must be positive")
    effective_weights = weights or SelectionWeights()
    effective_weights.validate()
    scored: list[ScoredStory] = []
    for candidate, rating in zip(candidates, ratings, strict=True):
        if not 0 <= rating.profile_relevance <= 1 or not 0 <= rating.newsworthiness <= 1:
            raise ValueError("LLM ratings must be between 0 and 1")
        if rating.excluded_topic or rating.recently_covered:
            continue
        age_hours = _age_hours(candidate.newest_published_at, now)
        breakdown = {
            "profile_relevance": rating.profile_relevance,
            "newsworthiness": rating.newsworthiness,
            "independent_sources": min(candidate.independent_source_count / preferred_independent_sources, 1.0),
            "source_quality": _mean_quality(candidate.articles),
            "recency": max(0.0, min(1.0, 1 - age_hours / max_article_age_hours)),
        }
        total = sum(getattr(effective_weights, key) * value for key, value in breakdown.items())
        scored.append(ScoredStory(candidate, total, breakdown, rating.rationale))
    return sorted(
        scored,
        key=lambda item: (
            item.score,
            item.candidate.independent_source_count,
            _published_timestamp(item.candidate.newest_published_at),
            item.candidate.title.casefold(),
        ),
        reverse=True,
    )


def _terms(value: str) -> set[str]:
    return {word for word in re.findall(r"[\w']+", value.casefold()) if len(word) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _lead(value: str) -> str:
    return re.split(r"(?<=[.!?])\s+", value.strip(), maxsplit=1)[0][:500]


def _mean_quality(articles: Sequence[RetrievedArticle]) -> float:
    values = {"high": 1.0, "standard": 0.6, "low": 0.2, "blocked": 0.0}
    return sum(values.get(article.quality_tier, 0.6) for article in articles) / len(articles) if articles else 0.0


def _age_hours(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return float("inf")
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=now.tzinfo)
    return max(0.0, (now - published_at).total_seconds() / 3600)


def _published_timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0
