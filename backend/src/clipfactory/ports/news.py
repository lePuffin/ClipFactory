"""News discovery port and provider-neutral article reference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ArticleRef:
    url: str
    title: str
    publisher: str
    published_at: datetime | None
    summary: str = ""


class NewsQuery(Protocol):
    feeds: list[tuple[str, str]]


class NewsSource(Protocol):
    name: str
    supports_search: bool

    async def latest(self, query: NewsQuery) -> list[ArticleRef]: ...

    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]: ...
