import httpx
import pytest

from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.infrastructure.providers.media_sources import PexelsMediaSource
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.media_sources import MediaSearchRequest


@pytest.mark.unit
@pytest.mark.req("CF-NFR-103")
@pytest.mark.req("CF-NFR-106")
@pytest.mark.asyncio
async def test_authenticated_search_redirect_does_not_forward_credentials_to_another_host() -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"Location": "https://other.example/media"})
        return httpx.Response(200, content=b"media")

    client = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=httpx.MockTransport(respond))
    body, _, _ = await client.get_bytes(
        "https://api.example/search", max_bytes=100, headers={"Authorization": "secret"}
    )
    assert body == b"media"
    assert seen[0].headers["Authorization"] == "secret"
    assert "Authorization" not in seen[1].headers


@pytest.mark.unit
@pytest.mark.req("CF-REQ-207")
@pytest.mark.asyncio
async def test_pexels_video_search_maps_license_author_and_download_dimensions(tmp_path) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "test-key"
        return httpx.Response(
            200,
            json={
                "videos": [
                    {
                        "url": "https://pexels.com/video/city-1/",
                        "duration": 12,
                        "user": {"name": "Creator"},
                        "video_files": [
                            {
                                "file_type": "video/mp4",
                                "width": 1920,
                                "height": 1080,
                                "link": "https://cdn.example/city.mp4",
                            }
                        ],
                    }
                ]
            },
        )

    http = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=httpx.MockTransport(respond))
    provider = PexelsMediaSource(http, LocalStorageProvider(tmp_path), api_key="test-key")
    result = await provider.search(MediaSearchRequest("city", "video"))
    assert len(result) == 1
    assert result[0].license == "Pexels License"
    assert result[0].author == "Creator"
    assert result[0].duration_seconds == 12
    assert result[0].height == 1080
