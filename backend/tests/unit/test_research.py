from datetime import UTC, datetime

import httpx
import pytest

from clipfactory.infrastructure.http import ResponseTooLarge, SafeHTTPClient, UnsafeURL
from clipfactory.infrastructure.providers.news.rss import RssNewsSource
from clipfactory.research.articles import canonicalize_url, extract_article


def public_resolver(host: str, port: int) -> list[str]:
    assert host == "news.example"
    assert port == 443
    return ["93.184.216.34"]


@pytest.mark.unit
@pytest.mark.req("CF-NFR-103")
@pytest.mark.asyncio
async def test_safe_http_client_rejects_private_hosts_before_request() -> None:
    client = SafeHTTPClient(resolver=lambda _host, _port: ["127.0.0.1"])
    with pytest.raises(UnsafeURL, match="non-public"):
        await client.get_bytes("http://news.example/article", max_bytes=100)


@pytest.mark.unit
@pytest.mark.req("CF-NFR-104")
@pytest.mark.asyncio
async def test_safe_http_client_enforces_stream_size_limit() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"12345"))
    client = SafeHTTPClient(resolver=public_resolver, transport=transport)
    with pytest.raises(ResponseTooLarge, match="size limit"):
        await client.get_bytes("https://news.example/article", max_bytes=4)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-101")
def test_article_extraction_strips_scripts_and_canonicalizes_tracking_url() -> None:
    html = (
        '<html><head><title>Report</title><link rel="canonical" href="https://news.example/story?utm_source=rss">'
        "</head><body><script>secret()</script><article><p>First verified paragraph.</p>"
        "<p>Second paragraph.</p></article></body></html>"
    )
    article = extract_article(html, "https://news.example/other")
    assert article["title"] == "Report"
    assert article["canonical_url"] == "https://news.example/story"
    assert article["text"] == "First verified paragraph. Second paragraph."


@pytest.mark.unit
@pytest.mark.req("CF-REQ-102")
def test_canonical_url_removes_tracking_and_fragment() -> None:
    assert canonicalize_url("https://Example.org/news?a=1&utm_medium=x#part") == "https://example.org/news?a=1"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_rss_provider_parses_article_references() -> None:
    xml = b"""<rss><channel><item>
    <title>Update</title><link>https://news.example/a</link>
    <pubDate>Wed, 30 Sep 2026 09:00:00 GMT</pubDate>
    <description>Lead text</description>
    </item></channel></rss>"""
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=xml))
    http = SafeHTTPClient(resolver=public_resolver, transport=transport)
    source = RssNewsSource(http)

    class Query:
        def __init__(self) -> None:
            self.feeds = [("Example News", "https://news.example/feed.xml")]

    refs = await source.latest(Query())
    assert refs[0].title == "Update"
    assert refs[0].publisher == "Example News"
    assert refs[0].published_at == datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
