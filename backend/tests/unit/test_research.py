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
@pytest.mark.req("CF-REQ-101")
@pytest.mark.req("CF-REQ-104")
@pytest.mark.parametrize(
    "html",
    [
        "<body><nav>Scores Transfers Tickets</nav><article class='ad-300'></article>"
        "<header>Shared football site links</header><article>"
        "<header>Related headline</header><p>Distinct verified event.</p>"
        "<aside>Unrelated results.</aside><footer>Legal terms.</footer></article>"
        "<p>Recommended unrelated story.</p></body>",
        "<body>Shared site links<main><p>Distinct verified event.</p>"
        "<nav>Related stories</nav></main><footer>Legal terms.</footer></body>",
        "<body><nav>Scores Transfers Tickets</nav><p>Distinct verified event.</p><footer>Legal terms.</footer></body>",
    ],
)
def test_article_extraction_keeps_main_news_not_shared_site_chrome(html: str) -> None:
    article = extract_article(html, "https://news.example/story")
    assert article["text"] == "Distinct verified event."


@pytest.mark.unit
@pytest.mark.req("CF-REQ-101")
def test_article_extraction_does_not_treat_navigation_only_page_as_news() -> None:
    article = extract_article(
        "<body><nav>Shared site links</nav><article></article><footer>Legal terms.</footer></body>",
        "https://news.example/story",
    )
    assert article["text"] is None
    assert article["text_hash"] is None


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


class _Feeds:
    def __init__(self, *feeds: tuple[str, str]) -> None:
        self.feeds = list(feeds)


def _any_public(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_one_failing_feed_never_discards_other_feeds_references() -> None:
    rss = b"<rss><channel><item><title>Kept</title><link>https://ok.example/a</link></item></channel></rss>"

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if request.url.host == "broken.example" else 200, content=rss)

    http = SafeHTTPClient(resolver=_any_public, transport=httpx.MockTransport(respond))
    source = RssNewsSource(http, sleep=_no_sleep)
    refs = await source.latest(_Feeds(("Broken", "https://broken.example/f"), ("Ok", "https://ok.example/f")))
    assert [(ref.title, ref.publisher) for ref in refs] == [("Kept", "Ok")]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_rss_provider_parses_rdf_and_atom_feeds() -> None:
    rdf = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"
      xmlns:dc="http://purl.org/dc/elements/1.1/"><item rdf:about="https://dw.example/a">
      <title>RDF story</title><link>https://dw.example/a</link><description>Lead</description>
      <dc:date>2026-10-08T07:30:00Z</dc:date></item></rdf:RDF>"""
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom story</title>
      <link rel="alternate" href="https://atom.example/b"/><updated>2026-10-08T08:00:00+00:00</updated>
      <summary>Atom lead</summary></entry></feed>"""

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=rdf if request.url.host == "dw.example" else atom)

    http = SafeHTTPClient(resolver=_any_public, transport=httpx.MockTransport(respond))
    refs = await RssNewsSource(http).latest(_Feeds(("DW", "https://dw.example/f"), ("Atom", "https://atom.example/f")))
    assert [(ref.title, ref.url, ref.summary) for ref in refs] == [
        ("RDF story", "https://dw.example/a", "Lead"),
        ("Atom story", "https://atom.example/b", "Atom lead"),
    ]
    assert refs[0].published_at == datetime(2026, 10, 8, 7, 30, tzinfo=UTC)
    assert refs[1].published_at == datetime(2026, 10, 8, 8, 0, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_transient_dns_failure_is_retried_with_bounded_backoff() -> None:
    rss = b"<rss><channel><item><title>Back</title><link>https://news.example/a</link></item></channel></rss>"
    lookups: list[str] = []
    waits: list[float] = []

    def flaky_resolver(host: str, _port: int) -> list[str]:
        lookups.append(host)
        if len(lookups) < 3:
            raise OSError("Temporary failure in name resolution")
        return ["93.184.216.34"]

    async def record(seconds: float) -> None:
        waits.append(seconds)

    http = SafeHTTPClient(
        resolver=flaky_resolver, transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=rss))
    )
    refs = await RssNewsSource(http, retry_delays_seconds=(1, 2), sleep=record).latest(
        _Feeds(("News", "https://news.example/f"))
    )
    assert [ref.title for ref in refs] == ["Back"]
    assert waits == [1, 2]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-100")
@pytest.mark.asyncio
async def test_permanent_feed_errors_are_not_retried_and_all_failures_are_named() -> None:
    from clipfactory.infrastructure.providers.news.rss import FeedUnavailable

    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    http = SafeHTTPClient(resolver=_any_public, transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
    with pytest.raises(FeedUnavailable, match=r"One: HTTPStatusError.*Two: HTTPStatusError"):
        await RssNewsSource(http, sleep=record).latest(
            _Feeds(("One", "https://one.example/f"), ("Two", "https://two.example/f"))
        )
    assert waits == []
