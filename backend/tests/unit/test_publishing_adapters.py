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
from clipfactory.ports.errors import ProviderError
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

    statuses = iter(["IN_PROGRESS", "FINISHED"])

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        path = http_request.url.path
        if http_request.method == "GET" and path.endswith("/container-1"):
            return httpx.Response(200, json={"status_code": next(statuses)})
        if http_request.method == "GET":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/abc/"})
        identifier = "container-1" if path.endswith("/media") else "post-1"
        return httpx.Response(200, json={"id": identifier})

    publisher = InstagramPublisher(
        settings(tmp_path, INSTAGRAM_ACCESS_TOKEN="token", INSTAGRAM_USER_ID="user"),  # noqa: S106
        httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )
    result = await publisher.publish(request(), tmp_path / "clip.mp4")

    assert all(call.url.host == "graph.instagram.com" for call in calls)
    form = httpx.QueryParams(calls[0].content.decode())
    assert len(form["caption"]) == 2200
    assert form["caption"].startswith("T" * 100)
    assert [call.method for call in calls] == ["POST", "GET", "GET", "POST", "GET"]
    assert result.platform_post_id == "post-1"
    assert result.platform_url == "https://www.instagram.com/reel/abc/"
    assert result.disclosure_note is not None
    assert "unsupported" in result.disclosure_note


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_instagram_container_error_fails_without_publishing(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if http_request.method == "GET":
            return httpx.Response(200, json={"status_code": "ERROR", "status": "Error: unsupported video"})
        return httpx.Response(200, json={"id": "container-1"})

    publisher = InstagramPublisher(
        settings(tmp_path, INSTAGRAM_ACCESS_TOKEN="token", INSTAGRAM_USER_ID="user"),  # noqa: S106
        httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(request(), tmp_path / "clip.mp4")

    assert caught.value.code == "publish_failed"
    assert "unsupported video" in str(caught.value)
    assert not any(call.url.path.endswith("/media_publish") for call in calls)


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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_graph_oauth_error_is_auth_failed_with_redacted_platform_message(tmp_path: Path) -> None:
    secret = "EAAsecret-page-token"  # noqa: S105

    def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": f"Error validating access token: Session has expired ({secret})",
                    "type": "OAuthException",
                    "code": 190,
                }
            },
        )

    publisher = FacebookPublisher(
        settings(tmp_path, FACEBOOK_ACCESS_TOKEN=secret, FACEBOOK_PAGE_ID="page"),
        httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(request(), tmp_path / "clip.mp4")

    assert caught.value.code == "auth_failed"
    assert caught.value.transient is False
    assert "Session has expired" in str(caught.value)
    assert secret not in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.asyncio
async def test_youtube_refreshes_token_stored_beside_client_secrets(tmp_path: Path) -> None:
    secrets = tmp_path / "repo-secrets"
    secrets.mkdir()
    client_file = secrets / "youtube_oauth.json"
    client_file.write_text(
        json.dumps({"web": {"client_id": "id", "client_secret": "cs", "token_uri": "https://oauth.example/token"}})
    )
    (secrets / "youtube_token.json").write_text(json.dumps({"access_token": "stale", "refresh_token": "rt"}))
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if http_request.url.host == "oauth.example":
            return httpx.Response(200, json={"access_token": "fresh"})
        if http_request.method == "POST":
            return httpx.Response(200, headers={"location": "https://upload.example/video"})
        return httpx.Response(200, json={"id": "video-2"})

    (tmp_path / "clip.mp4").write_bytes(b"video")
    publisher = YouTubePublisher(
        settings(tmp_path / "data", YOUTUBE_CLIENT_SECRETS_FILE=client_file), httpx.MockTransport(handler)
    )
    assert publisher.is_configured()
    result = await publisher.publish(request(), tmp_path / "clip.mp4")

    refresh = httpx.QueryParams(calls[0].content.decode())
    assert refresh["grant_type"] == "refresh_token"
    assert refresh["refresh_token"] == "rt"  # noqa: S105
    assert calls[1].headers["Authorization"].endswith("fresh")
    assert result.platform_post_id == "video-2"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_youtube_revoked_refresh_token_is_actionable_auth_failure(tmp_path: Path) -> None:
    client_file = tmp_path / "youtube_oauth.json"
    client_file.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "cs"}}))
    (tmp_path / "youtube_token.json").write_text(json.dumps({"refresh_token": "rt"}))

    def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Token has been expired"})

    publisher = YouTubePublisher(
        settings(tmp_path, YOUTUBE_CLIENT_SECRETS_FILE=client_file), httpx.MockTransport(handler)
    )
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(request(), tmp_path / "clip.mp4")

    assert caught.value.code == "auth_failed"
    assert "--youtube-auth" in str(caught.value)
