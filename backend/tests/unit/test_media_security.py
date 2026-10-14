import httpx
import pytest

from clipfactory.infrastructure.http import SafeHTTPClient


@pytest.mark.unit
@pytest.mark.req("CF-NFR-103")
@pytest.mark.req("CF-NFR-106")
@pytest.mark.parametrize("target", ["https://other.example/media", "http://api.example/media"])
@pytest.mark.asyncio
async def test_media_auth_not_forwarded_on_origin_change(target: str) -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(200, content=b"media")

    client = SafeHTTPClient(resolver=lambda _host, _port: ["93.184.216.34"], transport=httpx.MockTransport(respond))
    await client.get_bytes("https://api.example/search", max_bytes=100, headers={"Authorization": "test-key"})
    assert requests[0].headers["Authorization"] == "test-key"
    assert "Authorization" not in requests[1].headers
