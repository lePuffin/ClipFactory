"""Deterministic HTML article text extraction and canonical URL handling."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.canonical_url: str | None = None
        self.author: str | None = None
        self.published_at: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._article_depth = 0
        self._has_article = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "article":
            self._article_depth += 1
            self._has_article = True
        if tag == "title":
            self._in_title = True
        if tag == "link" and str(values.get("rel") or "").casefold() == "canonical":
            self.canonical_url = values.get("href")
        if tag == "meta":
            key = (values.get("name") or values.get("property") or "").lower()
            if key in {"author", "article:author"}:
                self.author = values.get("content")
            elif key in {"article:published_time", "datepublished"}:
                self.published_at = values.get("content")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "article" and self._article_depth:
            self._article_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(value)
        elif not self._has_article or self._article_depth:
            self.text_parts.append(value)


def normalize_article_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = "".join(char for char in value if char in "\n\t" or unicodedata.category(char)[0] != "C")
    return re.sub(r"\s+", " ", value).strip()


def extract_article(html: str, page_url: str) -> dict[str, str | None]:
    parser = _ArticleParser()
    parser.feed(html)
    title = normalize_article_text(" ".join(parser.title_parts))
    text = normalize_article_text(" ".join(parser.text_parts))
    canonical = parser.canonical_url or page_url
    return {
        "title": title or None,
        "text": text or None,
        "canonical_url": canonicalize_url(canonical),
        "author": normalize_article_text(parser.author or "") or None,
        "published_at": parser.published_at,
        "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
    }


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("article URL must be HTTP(S)")
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in {"fbclid", "gclid"} and not key.lower().startswith("utm_")
    ]
    host = parts.hostname.lower()
    netloc = host if parts.port is None or (parts.scheme == "https" and parts.port == 443) else f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(kept_query), ""))
