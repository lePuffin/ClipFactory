"""RSS implementation of the NewsSource port."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as ET

from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.ports.news import ArticleRef, NewsQuery


class RssNewsSource:
    name = "rss"
    supports_search = False

    def __init__(self, http: SafeHTTPClient, *, max_feed_bytes: int = 2_000_000) -> None:
        self.http = http
        self.max_feed_bytes = max_feed_bytes

    async def latest(self, query: NewsQuery) -> list[ArticleRef]:
        references: list[ArticleRef] = []
        for publisher, url in query.feeds:
            payload, _, _ = await self.http.get_bytes(url, max_bytes=self.max_feed_bytes)
            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                raise ValueError(f"invalid RSS feed from {publisher}") from exc
            for item in root.findall(".//item"):
                title = _text(item.findtext("title"))
                link = _text(item.findtext("link"))
                if not title or not link:
                    continue
                references.append(
                    ArticleRef(
                        url=link,
                        title=title,
                        publisher=publisher,
                        published_at=_published_at(item.findtext("pubDate")),
                        summary=_text(item.findtext("description")),
                    )
                )
        return references

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]:
        del text, since, limit
        return []


def _text(value: str | None) -> str:
    return " ".join((value or "").split())


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
