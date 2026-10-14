from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from clipfactory.domain.models import ContentCategory
from clipfactory.ports.news import ArticleRef
from clipfactory.research.articles import extract_article
from clipfactory.research.discovery import RetrievedArticle
from clipfactory.research.llm_tasks import RankedStoryDraft
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
@pytest.mark.req("CF-REQ-101")
@pytest.mark.req("CF-REQ-105")
def test_same_publisher_navigation_does_not_merge_unrelated_stories() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    navigation = "<nav>" + "Scores Transfers Tickets Teams Leagues Schedules " * 20 + "</nav>"
    articles = []
    for index, (title, body) in enumerate(
        [
            ("Broadcast rights agreement", "A broadcaster acquired tournament rights for the next competition."),
            ("Coach responds to celebrations", "The manager defended players celebrating their away victory."),
        ]
    ):
        url = f"https://news.example/{index}"
        value = extract_article(
            f"<body>{navigation}<article class='ad-300'></article><article><p>{body}</p></article></body>",
            url,
        )
        text = value["text"]
        assert text is not None
        assert text == body
        articles.append(fetched(url, "Same Publisher", title, text, now))
    candidates = precluster_articles(articles)
    assert [candidate.article_indexes for candidate in candidates] == [(0,), (1,)]
    assert [candidate.summary for candidate in candidates] == [article.text for article in articles]


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


@pytest.mark.req("CF-REQ-108")
@pytest.mark.req("CF-REQ-107")
@pytest.mark.parametrize("category", [ContentCategory.SPORTS, ContentCategory.GENERAL])
def test_politics_is_not_eligible_for_sports_even_with_perfect_ratings(category: ContentCategory) -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    candidates = precluster_articles(
        [
            fetched("https://news.example/politics", "BBC", "Houthis attack Aramco", "Regional conflict.", now),
            fetched("https://news.example/football", "Sport", "Champions League result", "Football match.", now),
        ]
    )
    candidates = [
        replace(candidates[0], category=ContentCategory.POLITICS),
        replace(candidates[1], category=ContentCategory.SPORTS),
    ]
    scored = score_stories(
        candidates,
        [StoryRating(1, 1), StoryRating(0.1, 0.1)],
        now=now,
        max_article_age_hours=24,
        preferred_independent_sources=3,
        profile_category=category,
    )
    assert [item.candidate.category for item in scored] == (
        [ContentCategory.SPORTS]
        if category == ContentCategory.SPORTS
        else [ContentCategory.POLITICS, ContentCategory.SPORTS]
    )


@pytest.mark.req("CF-REQ-108")
def test_ranked_candidate_requires_honest_classification_not_profile_stamping() -> None:
    with pytest.raises(ValidationError) as error:
        RankedStoryDraft.model_validate(
            {
                "candidate_indexes": [0],
                "title": "Houthis attack Aramco",
                "summary": "Regional conflict.",
                "profile_relevance": 1,
                "newsworthiness": 1,
                "rationale": "Major event",
            }
        )
    assert error.value.errors()[0]["loc"] == ("category",)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-107")
def test_selection_weights_must_sum_to_one() -> None:
    weights = SelectionWeights(profile_relevance=0.5)
    with pytest.raises(ValueError, match="sum to 1"):
        weights.validate()
