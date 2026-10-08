from datetime import UTC, datetime, timedelta

import pytest

from clipfactory.ports.news import ArticleRef
from clipfactory.research.discovery import RetrievedArticle
from clipfactory.research.selection import (
    SelectionWeights,
    StoryRating,
    precluster_articles,
    score_stories,
    validate_article_partition,
)


def fetched(url: str, publisher: str, title: str, text: str, when: datetime) -> RetrievedArticle:
    return RetrievedArticle(ArticleRef(url, title, publisher, when), url, title, text, None, "hash", "high")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-105")
def test_precluster_partitions_related_and_unrelated_articles_once() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    articles = [
        fetched(
            "https://a.example/1",
            "A",
            "Flood closes bridge",
            "Flood closes bridge after heavy rain in northern region.",
            now,
        ),
        fetched(
            "https://b.example/1",
            "B",
            "Flood closes bridge",
            "Flood closes bridge after heavy rain in northern region.",
            now,
        ),
        fetched(
            "https://c.example/1",
            "C",
            "Central bank changes rates",
            "Central bank raises interest rates after inflation report.",
            now,
        ),
    ]
    candidates = precluster_articles(articles)
    validate_article_partition([candidate.article_indexes for candidate in candidates], len(articles))
    assert [len(candidate.articles) for candidate in candidates] == [2, 1]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-107")
def test_story_scoring_is_deterministic_and_excludes_llm_flagged_candidates() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    articles = [
        fetched(
            "https://a.example/1", "A", "Science discovery", "New science discovery changes satellite research.", now
        ),
        fetched(
            "https://b.example/1",
            "B",
            "Science discovery",
            "New science discovery changes satellite research.",
            now - timedelta(hours=2),
        ),
        fetched("https://c.example/1", "C", "Sports update", "Local club announces a new coach after season.", now),
    ]
    candidates = precluster_articles(articles)
    ratings = [StoryRating(0.9, 0.8, rationale="important"), StoryRating(0.8, 0.7, excluded_topic=True)]
    first = score_stories(candidates, ratings, now=now, max_article_age_hours=24, preferred_independent_sources=3)
    second = score_stories(candidates, ratings, now=now, max_article_age_hours=24, preferred_independent_sources=3)
    assert first == second
    assert len(first) == 1
    assert set(first[0].breakdown) == {
        "profile_relevance",
        "newsworthiness",
        "independent_sources",
        "source_quality",
        "recency",
    }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-107")
def test_selection_weights_must_sum_to_one() -> None:
    weights = SelectionWeights(profile_relevance=0.5)
    with pytest.raises(ValueError, match="sum to 1"):
        weights.validate()
