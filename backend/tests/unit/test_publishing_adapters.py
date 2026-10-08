import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from clipfactory.infrastructure.providers.publishing.platforms import (
    FacebookPublisher,
    InstagramPublisher,
    YouTubePublisher,
)
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.publishing import PublicationRequest


def settings(tmp_path: Path, **overrides: Any) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "development",
        "DATABASE_URL": "sqlite://",
        "DATA_DIR": tmp_path,
    }
    values.update(overrides)
    return EnvironmentSettings(**values)


def request() -> PublicationRequest:
    return PublicationRequest(
        clip_id=uuid4(),
        title="T" * 2400,
        description="Description",
        hashtags=("news",),
        source_attributions=(),
        asset_attributions=(),
        contains_synthetic_media=True,
        synthetic_voice=True,
        public_media_url="https://media.example/clip",
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-453")
@pytest.mark.asyncio
async def test_youtube_adapter_truncates_title_and_maps_disclosure(tmp_path: Path) -> None:
    token = tmp_path / "secrets" / "youtube_token.json"
    token.parent.mkdir()
    token.write_text(json.dumps({"access_token": "test-token"}))
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if http_request.method == "POST":
            return httpx.Response(200, headers={"location": "https://upload.example/video"})
        return httpx.Response(200, json={"id": "video-1"})

    (tmp_path / "clip.mp4").write_bytes(b"video")
    result = await YouTubePublisher(settings(tmp_path), httpx.MockTransport(handler)).publish(
        request(), tmp_path / "clip.mp4"
    )

    payload = json.loads(calls[0].content)
    assert len(payload["snippet"]["title"]) == 100
    assert payload["status"]["containsSyntheticMedia"] is True
    assert result.platform_post_id == "video-1"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-453")
@pytest.mark.asyncio
async def test_instagram_adapter_truncates_caption_and_records_disclosure(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        identifier = "container-1" if http_request.url.path.endswith("/media") else "post-1"
        return httpx.Response(200, json={"id": identifier})

    publisher = InstagramPublisher(
        settings(tmp_path, INSTAGRAM_ACCESS_TOKEN="token", INSTAGRAM_USER_ID="user"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    result = await publisher.publish(request(), tmp_path / "clip.mp4")

    form = httpx.QueryParams(calls[0].content.decode())
    assert len(form["caption"]) == 2200
    assert form["caption"].startswith("T" * 100)
    assert result.disclosure_note is not None
    assert "unsupported" in result.disclosure_note


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-453")
@pytest.mark.asyncio
async def test_facebook_adapter_truncates_title_and_records_disclosure(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(200, json={"id": "post-1"})

    publisher = FacebookPublisher(
        settings(tmp_path, FACEBOOK_ACCESS_TOKEN="token", FACEBOOK_PAGE_ID="page"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    result = await publisher.publish(request(), tmp_path / "clip.mp4")

    form = httpx.QueryParams(calls[0].content.decode())
    assert len(form["title"]) == 255
    assert "Contains synthetic media" in form["description"]
    assert result.disclosure_note is not None
