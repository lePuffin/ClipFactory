"""RSS 2.0, RSS 1.0 (RDF) and Atom implementation of the NewsSource port."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from defusedxml import ElementTree as ET

from clipfactory.infrastructure.http import HostResolutionError, SafeHTTPClient
from clipfactory.ports.news import ArticleRef, NewsQuery

_RSS1 = "{http://purl.org/rss/1.0/}"
_ATOM = "{http://www.w3.org/2005/Atom}"
_DC = "{http://purl.org/dc/elements/1.1/}"


class FeedUnavailable(RuntimeError):
    """Every configured feed failed; the message names each feed and its error."""


class RssNewsSource:
    name = "rss"
    supports_search = False

    def __init__(
        self,
        http: SafeHTTPClient,
        *,
        max_feed_bytes: int = 2_000_000,
        retry_delays_seconds: Sequence[float] = (5.0, 15.0),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.http = http
        self.max_feed_bytes = max_feed_bytes
        self.retry_delays_seconds = tuple(retry_delays_seconds)
        self.sleep = sleep

    async def latest(self, query: NewsQuery) -> list[ArticleRef]:
        """Fetch feeds concurrently; one failing feed never discards the others' references."""
        results = await asyncio.gather(
            *(self._feed(publisher, url) for publisher, url in query.feeds), return_exceptions=True
        )
        references: list[ArticleRef] = []
        failures: list[str] = []
        for (publisher, _), result in zip(query.feeds, results, strict=True):
            if isinstance(result, BaseException):
                if not isinstance(result, Exception):
                    raise result
                failures.append(f"{publisher}: {type(result).__name__}: {' '.join(str(result).split())[:160]}")
                continue
            references.extend(result)
        if failures and len(failures) == len(query.feeds):
            raise FeedUnavailable("; ".join(failures))
        return references

    async def _feed(self, publisher: str, url: str) -> list[ArticleRef]:
        attempt = 0
        while True:
            try:
                payload, _, _ = await self.http.get_bytes(url, max_bytes=self.max_feed_bytes)
                break
            except Exception as exc:
                if attempt >= len(self.retry_delays_seconds) or not _transient(exc):
                    raise
                await self.sleep(self.retry_delays_seconds[attempt])
                attempt += 1
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError(f"invalid RSS feed from {publisher}") from exc
        return parse_feed(root, publisher)

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]:
        del text, since, limit
        return []


def parse_feed(root: Any, publisher: str) -> list[ArticleRef]:
    references: list[ArticleRef] = []
    for item in [*root.iter("item"), *root.iter(f"{_RSS1}item")]:
        prefix = _RSS1 if str(item.tag).startswith(_RSS1) else ""
        title = _text(item.findtext(f"{prefix}title"))
        link = _text(item.findtext(f"{prefix}link"))
        if title and link:
            references.append(
                ArticleRef(
                    url=link,
                    title=title,
                    publisher=publisher,
                    published_at=_published_at(item.findtext("pubDate")) or _published_at(item.findtext(f"{_DC}date")),
                    summary=_text(item.findtext(f"{prefix}description")),
                )
            )
    for entry in root.iter(f"{_ATOM}entry"):
        title = _text(entry.findtext(f"{_ATOM}title"))
        links = entry.findall(f"{_ATOM}link")
        preferred = [node for node in links if node.get("rel", "alternate") == "alternate"] or links
        link = _text(preferred[0].get("href")) if preferred else ""
        if title and link:
            references.append(
                ArticleRef(
                    url=link,
                    title=title,
                    publisher=publisher,
                    published_at=_published_at(entry.findtext(f"{_ATOM}published"))
                    or _published_at(entry.findtext(f"{_ATOM}updated")),
                    summary=_text(entry.findtext(f"{_ATOM}summary")),
                )
            )
    return references


def _transient(exc: Exception) -> bool:
    if isinstance(exc, HostResolutionError | httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code == 429 or exc.response.status_code >= 500
    )


def _text(value: str | None) -> str:
    return " ".join((value or "").split())


def _published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
