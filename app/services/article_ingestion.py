"""Safe local ingestion of pasted articles and public article URLs."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from app.core.exceptions import InvalidInputError
from app.models.article import ArticleDocument, ArticleImage, ArticleParagraph
from app.models.source import ClipSourceOrigin, ClipSourceType, Source

_WHITESPACE = re.compile(r"\s+")
_REMOVABLE_TAGS = ("script", "style", "noscript", "svg", "nav", "header", "footer", "aside")
_MAXIMUM_PARAGRAPH_CHARACTERS = 8_000


def validate_article_url(value: str) -> str:
    """Accept only concrete public web URLs suitable for article retrieval."""
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidInputError("Enter a valid http or https article URL")
    if parsed.username or parsed.password:
        raise InvalidInputError("Article URLs cannot include credentials")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.casefold() == "localhost":
            raise InvalidInputError("Article URLs must use a public host") from None
    else:
        if not address.is_global:
            raise InvalidInputError("Article URLs must use a public host")
    return url


class ArticleIngestionService:
    """Extracts a bounded clean-text article without executing page content."""

    def __init__(self, maximum_characters: int = 50_000, timeout_seconds: float = 20) -> None:
        self.maximum_characters = maximum_characters
        self.timeout_seconds = timeout_seconds

    def ingest(self, source: Source) -> ArticleDocument:
        if source.type is not ClipSourceType.ARTICLE:
            raise InvalidInputError("Only article sources can be ingested as articles")
        if source.origin is ClipSourceOrigin.ARTICLE_TEXT:
            text = self._clean_text(source.reference)
            return ArticleDocument(
                source_id=source.id,
                title=source.name,
                text=text,
                paragraphs=self._paragraphs_from_text(source.id, text),
            )
        if source.origin is ClipSourceOrigin.ARTICLE_URL:
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
            useful_paragraphs = [self._normalize_text(text)]
        return ArticleDocument(
            source_id=source_id,
            title=title,
            text=self._clean_text(text),
            url=final_url,
            paragraphs=self._paragraph_records(source_id, useful_paragraphs),
            images=self._extract_images(source_id, content, final_url),
        )

    def download_image(self, url: str, destination: Path, maximum_bytes: int = 12_000_000) -> str:
        """Download a selected article image into a managed local path."""
        if maximum_bytes <= 0:
            raise ValueError("maximum image size must be positive")
        image_url = validate_article_url(url)
        request = Request(image_url, headers={"User-Agent": "ClipFactory/0.3 article reader"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "").lower().split(";", 1)[0]
                if not content_type.startswith("image/"):
                    raise InvalidInputError("Article image URL did not return an image")
                payload = response.read(maximum_bytes + 1)
                if len(payload) > maximum_bytes:
                    raise InvalidInputError("Article image is too large")
        except InvalidInputError:
            raise
        except (OSError, URLError) as error:
            raise InvalidInputError(f"Could not retrieve article image: {error}") from error
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return content_type

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

    def _paragraphs_from_text(self, source_id: str, text: str) -> list[ArticleParagraph]:
        return self._paragraph_records(source_id, [text])

    def _paragraph_records(
        self,
        source_id: str,
        paragraphs: list[str],
    ) -> list[ArticleParagraph]:
        records: list[ArticleParagraph] = []
        for paragraph in paragraphs:
            for chunk in self._split_paragraph(paragraph):
                records.append(
                    ArticleParagraph(
                        id=f"{source_id}-p-{len(records) + 1:03d}",
                        text=chunk,
                    )
                )
        if records:
            return records
        raise InvalidInputError("Article did not contain readable paragraphs")

    def _split_paragraph(self, paragraph: str) -> list[str]:
        normalized = self._normalize_text(paragraph)
        chunks: list[str] = []
        while len(normalized) > _MAXIMUM_PARAGRAPH_CHARACTERS:
            split_at = normalized.rfind(" ", 0, _MAXIMUM_PARAGRAPH_CHARACTERS + 1)
            if split_at <= 0:
                split_at = _MAXIMUM_PARAGRAPH_CHARACTERS
            chunks.append(normalized[:split_at].strip())
            normalized = normalized[split_at:].strip()
        if normalized:
            chunks.append(normalized)
        return chunks

    def _extract_images(self, source_id: str, content: object, base_url: str) -> list[ArticleImage]:
        if not isinstance(content, BeautifulSoup) and not hasattr(content, "find_all"):
            return []
        images: list[ArticleImage] = []
        for index, image in enumerate(content.find_all("img"), start=1):
            source_url = str(image.get("src") or "").strip()
            if not source_url:
                continue
            resolved_url = urljoin(base_url, source_url)
            try:
                resolved_url = validate_article_url(resolved_url)
            except InvalidInputError:
                continue
            images.append(
                ArticleImage(
                    id=f"{source_id}-image-{index:02d}",
                    url=resolved_url,
                    alt_text=self._normalize_text(str(image.get("alt") or "")),
                )
            )
            if len(images) >= 12:
                break
        return images