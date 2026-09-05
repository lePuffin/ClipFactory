from contextlib import contextmanager

import pytest

from app.core.exceptions import InvalidInputError
from app.models.source import ReelSourceOrigin, ReelSourceType, Source
from app.services.article_ingestion import ArticleIngestionService, validate_article_url


def _article_source(origin: ReelSourceOrigin, reference: str) -> Source:
    return Source(
        id="article-01",
        type=ReelSourceType.ARTICLE,
        origin=origin,
        name="Article source",
        reference=reference,
    )


def test_pasted_article_is_cleaned_and_validated() -> None:
    document = ArticleIngestionService().ingest(
        _article_source(
            ReelSourceOrigin.ARTICLE_TEXT,
            "<h1>News</h1><p>" + "Important reporting " * 12 + "</p>",
        )
    )

    assert document.title == "Article source"
    assert document.url is None
    assert "<p>" not in document.text
    assert document.text.startswith("News Important reporting")


def test_article_url_extracts_main_paragraphs(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, _: int) -> bytes:
            return (
                b"<html><head><title>Market update</title></head><body>"
                b"<nav>Ignore this navigation</nav><main>"
                b"<p>" + b"First useful reporting sentence. " * 5 + b"</p>"
                b"<p>" + b"Second useful reporting sentence. " * 5 + b"</p>"
                b"</main></body></html>"
            )

        def geturl(self) -> str:
            return "https://example.com/article"

    @contextmanager
    def fake_urlopen(*_: object, **__: object):
        yield FakeResponse()

    monkeypatch.setattr("app.services.article_ingestion.urlopen", fake_urlopen)
    document = ArticleIngestionService().ingest(
        _article_source(ReelSourceOrigin.ARTICLE_URL, "https://example.com/article")
    )

    assert document.title == "Market update"
    assert "Ignore this navigation" not in document.text
    assert "First useful reporting" in document.text
    assert document.url == "https://example.com/article"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/news", "not a URL"])
def test_article_url_validation_rejects_unsupported_schemes(url: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_article_url(url)