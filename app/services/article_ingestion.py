"""Safe local ingestion of pasted articles and public article URLs."""

from __future__ import annotations

import re
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.core.exceptions import InvalidInputError
from app.models.article import ArticleDocument
from app.models.source import ReelSourceOrigin, ReelSourceType, Source

_WHITESPACE = re.compile(r"\s+")
_REMOVABLE_TAGS = ("script", "style", "noscript", "svg", "nav", "header", "footer", "aside")


def validate_article_url(value: str) -> str:
    """Accept only concrete public web URLs suitable for article retrieval."""
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidInputError("Enter a valid http or https article URL")
    if parsed.username or parsed.password:
        raise InvalidInputError("Article URLs cannot include credentials")
    return url


class ArticleIngestionService:
    """Extracts a bounded clean-text article without executing page content."""

    def __init__(self, maximum_characters: int = 50_000, timeout_seconds: float = 20) -> None:
        self.maximum_characters = maximum_characters
        self.timeout_seconds = timeout_seconds

    def ingest(self, source: Source) -> ArticleDocument:
        if source.type is not ReelSourceType.ARTICLE:
            raise InvalidInputError("Only article sources can be ingested as articles")
        if source.origin is ReelSourceOrigin.ARTICLE_TEXT:
            text = self._clean_text(source.reference)
            return ArticleDocument(source_id=source.id, title=source.name, text=text)
        if source.origin is ReelSourceOrigin.ARTICLE_URL:
            url = validate_article_url(source.reference)
            return self._extract_url(source.id, url)
        raise InvalidInputError("Unsupported article source")

    def _extract_url(self, source_id: str, url: str) -> ArticleDocument:
        markup, final_url = self._fetch_markup(url)
        soup = BeautifulSoup(markup, "html.parser")
        for tag in soup.find_all(_REMOVABLE_TAGS):
            tag.decompose()

        title = self._extract_title(soup, final_url)
        content = soup.find("article") or soup.find("main") or soup.body or soup
        paragraphs = [
            self._normalize_text(paragraph.get_text(" ", strip=True))
            for paragraph in content.find_all(["p", "li"])
        ]
        useful_paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) >= 40]
        if useful_paragraphs:
            text = "\n\n".join(useful_paragraphs)
        else:
            text = content.get_text(" ", strip=True)
        return ArticleDocument(
            source_id=source_id,
            title=title,
            text=self._clean_text(text),
            url=final_url,
        )

    def _fetch_markup(self, url: str) -> tuple[str, str]:
        request = Request(url, headers={"User-Agent": "ClipFactory/0.3 article reader"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and "html" not in content_type and "text/plain" not in content_type:
                    raise InvalidInputError("Article URL did not return HTML or text content")
                payload = response.read(self.maximum_characters * 4 + 1)
                if len(payload) > self.maximum_characters * 4:
                    raise InvalidInputError("Article URL returned too much content")
                final_url = validate_article_url(response.geturl())
        except InvalidInputError:
            raise
        except (OSError, URLError) as error:
            raise InvalidInputError(f"Could not retrieve article URL: {error}") from error
        return payload.decode("utf-8", errors="replace"), final_url

    def _extract_title(self, soup: BeautifulSoup, url: str) -> str:
        open_graph = soup.find("meta", attrs={"property": "og:title"})
        if open_graph and open_graph.get("content"):
            return self._normalize_text(str(open_graph["content"]))[:300]
        if soup.title:
            title = self._normalize_text(soup.title.get_text(" ", strip=True))
            if title:
                return title[:300]
        return urlparse(url).hostname or "Article"

    def _clean_text(self, value: str) -> str:
        text = self._normalize_text(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))
        if len(text) < 120:
            raise InvalidInputError("Article text must contain at least 120 characters")
        return text[: self.maximum_characters]

    def _normalize_text(self, value: str) -> str:
        return _WHITESPACE.sub(" ", value).strip()