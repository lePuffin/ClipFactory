from contextlib import contextmanager

import pytest

from app.core.exceptions import InvalidInputError
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.article_ingestion import ArticleIngestionService, validate_article_url


def _article_source(origin: ClipSourceOrigin, reference: str) -> Source:
    return Source(
        id="article-01",
        type=ClipSourceType.ARTICLE,
        origin=origin,
        name="Article source",
        reference=reference,
    )


def test_pasted_article_is_cleaned_and_validated() -> None:
    document = ArticleIngestionService().ingest(
        _article_source(
            ClipSourceOrigin.ARTICLE_TEXT,
            "<h1>News</h1><p>" + "Important reporting " * 12 + "</p>",
        )
    )

    assert document.title == "Article source"
    assert document.url is None
    assert "<p>" not in document.text
    assert document.text.startswith("News Important reporting")
    assert document.paragraphs[0].id == "article-01-p-001"


def test_pasted_article_splits_long_text_into_bounded_provenance_paragraphs() -> None:
    text = "Reported source material " * 500

    document = ArticleIngestionService().ingest(
        _article_source(ClipSourceOrigin.ARTICLE_TEXT, text)
    )

    assert len(document.paragraphs) == 2
    assert [paragraph.id for paragraph in document.paragraphs] == [
        "article-01-p-001",
        "article-01-p-002",
    ]
    assert all(len(paragraph.text) <= 8_000 for paragraph in document.paragraphs)
    assert " ".join(paragraph.text for paragraph in document.paragraphs) == document.text


def test_article_url_extracts_main_paragraphs(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, _: int) -> bytes:
            return (
                b"<html><head><title>Market update</title></head><body>"
                b"<nav>Ignore this navigation</nav><main>"
                b"<p>" + b"First useful reporting sentence. " * 5 + b"</p>"
                b"<p>" + b"Second useful reporting sentence. " * 5 + b"</p>"
                b"<img src='/market.jpg' alt='Market chart'>"
                b"</main></body></html>"
            )

        def geturl(self) -> str:
            return "https://example.com/article"

    @contextmanager
    def fake_urlopen(*_: object, **__: object):
        yield FakeResponse()

    monkeypatch.setattr("app.services.article_ingestion.urlopen", fake_urlopen)
    document = ArticleIngestionService().ingest(
        _article_source(ClipSourceOrigin.ARTICLE_URL, "https://example.com/article")
    )

    assert document.title == "Market update"
    assert "Ignore this navigation" not in document.text
    assert "First useful reporting" in document.text
    assert document.url == "https://example.com/article"
    assert [paragraph.id for paragraph in document.paragraphs] == [
        "article-01-p-001",
        "article-01-p-002",
    ]
    assert document.images[0].url == "https://example.com/market.jpg"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/news",
        "not a URL",
        "http://localhost/news",
        "http://127.0.0.1/news",
        "http://192.168.1.10/news",
        "http://[::1]/news",
    ],
)
def test_article_url_validation_rejects_unsupported_schemes(url: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_article_url(url)


def test_article_image_download_rejects_private_url_before_fetch(tmp_path, monkeypatch) -> None:
    def unexpected_urlopen(*_: object, **__: object) -> object:
        raise AssertionError("private URL should be rejected before fetching")

    monkeypatch.setattr("app.services.article_ingestion.urlopen", unexpected_urlopen)

    with pytest.raises(InvalidInputError):
        ArticleIngestionService().download_image(
            "http://127.0.0.1/chart.png",
            tmp_path / "chart.png",
        )