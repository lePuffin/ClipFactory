from datetime import UTC, datetime, timedelta

import httpx
import pytest

from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.ports.news import ArticleRef
from clipfactory.research.discovery import ResearchPolicy, research_articles


class FakeNewsSource:
    name = "fake_news"
    supports_search = False

    def __init__(self, references: list[ArticleRef]) -> None:
        self.references = references

    async def latest(self, query: object) -> list[ArticleRef]:
        del query
        return self.references

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]:
        del text, since, limit
        return []


def _policy() -> ResearchPolicy:
    return ResearchPolicy(
        max_candidate_articles=1,
        max_article_age_hours=24,
        max_article_bytes=100_000,
        feeds=[],
        publisher_quality={"high.example": "high", "blocked.example": "blocked"},
        blocked_publishers=[],
        preferred_topics=["science"],
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_research_filters_stale_and_blocked_and_fetches_top_ranked_only() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    fresh = ArticleRef("https://high.example/a", "Science update", "High", now - timedelta(hours=1))
    stale = ArticleRef("https://standard.example/b", "Old politics", "Standard", now - timedelta(hours=30))
    blocked = ArticleRef("https://blocked.example/c", "Other report", "Blocked", now)
    request_urls: list[str] = []

    def response(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        return httpx.Response(200, content=b"<article><title>Science update</title><p>Verified report.</p></article>")

    transport = httpx.MockTransport(response)
    safe = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    result = await research_articles([FakeNewsSource([fresh, stale, blocked])], safe, _policy(), now=now)

    assert result.references_seen == 3
    assert len(result.articles) == 1
    assert result.articles[0].quality_tier == "standard"
    assert request_urls == ["https://high.example/a"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_research_continues_when_one_news_source_fails() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    article = ArticleRef("https://high.example/a", "Science update", "High", now)

    class FailingSource(FakeNewsSource):
        name = "broken"

        async def latest(self, query: object) -> list[ArticleRef]:
            del query
            raise RuntimeError("provider outage")

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, content=b"<article><title>Science update</title><p>Evidence.</p></article>"
        )
    )
    safe = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=transport)
    result = await research_articles([FailingSource([]), FakeNewsSource([article])], safe, _policy(), now=now)

    assert len(result.articles) == 1
    assert result.provider_warnings == ("broken: RuntimeError",)
