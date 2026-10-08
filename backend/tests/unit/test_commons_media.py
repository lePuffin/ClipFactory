import httpx
import pytest

from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.infrastructure.providers.media_sources import WikimediaCommonsMediaSource
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.media_sources import MediaSearchRequest


@pytest.mark.unit
@pytest.mark.req("CF-REQ-203")
@pytest.mark.req("CF-REQ-207")
@pytest.mark.parametrize(("license_name", "count"), [("CC BY-SA 4.0", 1), ("CC BY-NC 4.0", 0)])
@pytest.mark.asyncio
async def test_safe_raster_thumbnail_preserves_free_license_attribution(tmp_path, license_name, count) -> None:
    body = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Yemen map.svg",
                    "imageinfo": [
                        {
                            "mime": "image/svg+xml",
                            "thumbmime": "image/png",
                            "url": "https://upload.wikimedia.org/map.svg",
                            "thumburl": "https://upload.wikimedia.org/map.svg.png",
                            "width": 2000,
                            "height": 2000,
                            "thumbwidth": 1600,
                            "thumbheight": 1600,
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Yemen_map.svg",
                            "extmetadata": {
                                "LicenseShortName": {"value": license_name},
                                "Artist": {"value": "<b>Map Author</b>"},
                            },
                        }
                    ],
                }
            }
        }
    }
    http = SafeHTTPClient(
        resolver=lambda _host, _port: ["93.184.216.34"],
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
    )
    provider = WikimediaCommonsMediaSource(http, LocalStorageProvider(tmp_path), user_agent="ClipFactory test")
    candidates = await provider.search(MediaSearchRequest("Yemen map", "image"))
    assert len(candidates) == count
    if count:
        assert candidates[0].download_url.endswith(".png")
        assert candidates[0].attribution_required
        assert candidates[0].attribution_text is not None
        assert "Map Author" in candidates[0].attribution_text
