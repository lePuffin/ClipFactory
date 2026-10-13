import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from clipfactory.infrastructure.providers.publishing.platforms import (
    FacebookPublisher,
    InstagramPublisher,
    TikTokPublisher,
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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-453")
@pytest.mark.asyncio
async def test_tiktok_adapter_truncates_title_and_maps_aigc_disclosure(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(200, json={"data": {"publish_id": "tt_pub_12345"}})

    publisher = TikTokPublisher(
        settings(tmp_path, TIKTOK_ACCESS_TOKEN="test-tiktok-token"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    assert publisher.is_configured()

    (tmp_path / "clip.mp4").write_bytes(b"video-bytes")
    result = await publisher.publish(request(), tmp_path / "clip.mp4")

    assert calls[0].url.host == "open.tiktokapis.com"
    payload = json.loads(calls[0].content)
    assert len(payload["post_info"]["title"]) <= 2200
    assert payload["post_info"]["is_aigc"] is True
    assert payload["source_info"]["source"] == "PULL_FROM_URL"
    assert payload["source_info"]["video_url"] == "https://media.example/clip"
    assert result.platform_post_id == "tt_pub_12345"
    assert result.platform_url == "https://www.tiktok.com/@clipfactory/video/tt_pub_12345"
    assert result.disclosure_note is not None
    assert "is_aigc" in result.disclosure_note


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.asyncio
async def test_tiktok_adapter_direct_file_upload(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if http_request.method == "POST":
            return httpx.Response(
                200,
                json={"data": {"publish_id": "tt_pub_67890", "upload_url": "https://upload.tiktok.example/chunk"}},
            )
        return httpx.Response(200, json={})

    publisher = TikTokPublisher(
        settings(tmp_path, TIKTOK_ACCESS_TOKEN="test-tiktok-token"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"mp4-binary-data")

    req = PublicationRequest(
        clip_id=uuid4(),
        title="Direct Upload Clip",
        description="Description",
        hashtags=("viral",),
        source_attributions=(),
        asset_attributions=(),
        contains_synthetic_media=False,
        synthetic_voice=False,
        public_media_url=None,
    )
    result = await publisher.publish(req, clip_path)

    assert len(calls) == 2
    init_payload = json.loads(calls[0].content)
    assert init_payload["source_info"]["source"] == "FILE_UPLOAD"
    assert init_payload["source_info"]["video_size"] == len(b"mp4-binary-data")
    assert calls[1].method == "PUT"
    assert calls[1].content == b"mp4-binary-data"
    assert calls[1].headers["Content-Type"] == "video/mp4"
    assert result.platform_post_id == "tt_pub_67890"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.asyncio
async def test_tiktok_adapter_fetches_metrics(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "videos": [
                        {
                            "id": "tt_pub_12345",
                            "view_count": 5400,
                            "like_count": 320,
                            "comment_count": 45,
                            "share_count": 18,
                        }
                    ]
                }
            },
        )

    publisher = TikTokPublisher(
        settings(tmp_path, TIKTOK_ACCESS_TOKEN="test-tiktok-token"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    metrics = await publisher.fetch_metrics("tt_pub_12345")

    assert calls[0].url.path == "/v2/video/query/"
    assert metrics.views == 5400
    assert metrics.likes == 320
    assert metrics.comments == 45
    assert metrics.shares == 18


@pytest.mark.unit
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_tiktok_adapter_handles_auth_failure(tmp_path: Path) -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "access_token_invalid", "message": "The access token is invalid."}},
        )

    publisher = TikTokPublisher(
        settings(tmp_path, TIKTOK_ACCESS_TOKEN="invalid-token"),  # noqa: S106
        httpx.MockTransport(handler),
    )
    (tmp_path / "clip.mp4").write_bytes(b"clip")
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(request(), tmp_path / "clip.mp4")

    assert caught.value.code == "auth_failed"
    assert caught.value.transient is False
    assert "access token is invalid" in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-457")
@pytest.mark.asyncio
async def test_tiktok_adapter_unconfigured_fails_with_not_configured(tmp_path: Path) -> None:
    publisher = TikTokPublisher(settings(tmp_path))
    assert not publisher.is_configured()

    (tmp_path / "clip.mp4").write_bytes(b"clip")
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(request(), tmp_path / "clip.mp4")

    assert caught.value.code == "not_configured"
    assert caught.value.transient is False


@pytest.mark.unit
@pytest.mark.req("CF-REQ-451")
@pytest.mark.asyncio
async def test_scoped_env_prefix_publishing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify that publishers prefer prefix-scoped credentials over defaults when env_prefix is passed."""
    # Set both default and scoped credentials in environment
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "default-ig-token")
    monkeypatch.setenv("INSTAGRAM_USER_ID", "default-ig-user")
    monkeypatch.setenv("FOOTBALL_INSTAGRAM_ACCESS_TOKEN", "football-ig-token")
    monkeypatch.setenv("FOOTBALL_INSTAGRAM_USER_ID", "football-ig-user")

    scoped_calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        scoped_calls.append(http_request)
        if http_request.method == "POST":
            return httpx.Response(200, json={"id": "container_123"})
        return httpx.Response(200, json={"status_code": "FINISHED", "id": "post_123"})

    publisher = InstagramPublisher(settings(tmp_path), httpx.MockTransport(handler))

    # Request with env_prefix="FOOTBALL"
    req_scoped = PublicationRequest(
        clip_id=uuid4(),
        title="Football Clip",
        description="Description",
        hashtags=("football",),
        source_attributions=(),
        asset_attributions=(),
        contains_synthetic_media=False,
        synthetic_voice=False,
        public_media_url="https://media.example/football",
        env_prefix="FOOTBALL",
    )
    (tmp_path / "clip.mp4").write_bytes(b"football-clip")
    res = await publisher.publish(req_scoped, tmp_path / "clip.mp4")

    # The request should have targeted the football user ID container URL
    assert "football-ig-user" in str(scoped_calls[0].url)
    assert httpx.QueryParams(scoped_calls[0].content.decode())["access_token"] == "football-ig-token"  # noqa: S105
    assert res.platform_post_id == "container_123"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-451")
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [YouTubePublisher, InstagramPublisher, FacebookPublisher, TikTokPublisher])
async def test_scoped_accounts_never_fall_back_to_global_credentials(tmp_path, monkeypatch, adapter) -> None:
    defaults = settings(
        tmp_path,
        INSTAGRAM_ACCESS_TOKEN="global-instagram",  # noqa: S106
        INSTAGRAM_USER_ID="global-user",
        FACEBOOK_ACCESS_TOKEN="global-facebook",  # noqa: S106
        FACEBOOK_PAGE_ID="global-page",
        TIKTOK_ACCESS_TOKEN="global-tiktok",  # noqa: S106
    )
    token = tmp_path / "secrets" / "youtube_token.json"
    token.parent.mkdir()
    token.write_text(json.dumps({"access_token": "global-youtube"}))
    monkeypatch.setitem(EnvironmentSettings.model_config, "env_file", ())
    publisher = adapter(defaults, httpx.MockTransport(lambda _: pytest.fail("Must not contact another account")))
    assert publisher.is_configured()
    assert not publisher.is_configured("TESTSCOPE")
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(replace(request(), env_prefix="TESTSCOPE"), tmp_path / "clip.mp4")
    assert caught.value.code == "not_configured"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-451")
@pytest.mark.req("CF-REQ-500")
@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", [YouTubePublisher, FacebookPublisher, TikTokPublisher])
async def test_scoped_publishing_and_metrics_use_same_credentials_without_globals(
    tmp_path, monkeypatch, adapter
) -> None:
    calls: list[httpx.Request] = []
    scoped_token = "scoped-test-token"  # noqa: S105
    monkeypatch.setitem(EnvironmentSettings.model_config, "env_file", ())
    monkeypatch.setenv("TESTSCOPE_FACEBOOK_ACCESS_TOKEN", scoped_token)
    monkeypatch.setenv("TESTSCOPE_FACEBOOK_PAGE_ID", "scoped-page")
    monkeypatch.setenv("TESTSCOPE_TIKTOK_ACCESS_TOKEN", scoped_token)
    token = tmp_path / "scoped-youtube.json"
    token.write_text(json.dumps({"access_token": scoped_token}))
    monkeypatch.setenv("TESTSCOPE_YOUTUBE_TOKEN_FILE", str(token))

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if adapter is YouTubePublisher:
            if http_request.method == "POST":
                return httpx.Response(200, headers={"location": "https://upload.example/video"})
            if http_request.method == "PUT":
                return httpx.Response(200, json={"id": "post-1"})
            return httpx.Response(200, json={"items": [{"statistics": {"viewCount": "25"}}]})
        if adapter is FacebookPublisher:
            return httpx.Response(200, json={"id": "post-1", "views": 25})
        if http_request.method == "POST" and http_request.url.path == "/v2/video/query/":
            return httpx.Response(200, json={"data": {"videos": [{"id": "post-1", "view_count": 25}]}})
        return httpx.Response(200, json={"data": {"publish_id": "post-1"}})

    publisher = adapter(settings(tmp_path), httpx.MockTransport(handler))
    assert publisher.is_configured("TESTSCOPE")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test-video")
    await publisher.publish(replace(request(), env_prefix="TESTSCOPE"), clip)
    metrics = await publisher.fetch_metrics("post-1", "TESTSCOPE")
    assert metrics.views == 25
    if adapter is FacebookPublisher:
        assert "scoped-page" in str(calls[0].url)
        assert httpx.QueryParams(calls[0].content.decode())["access_token"] == scoped_token
        assert calls[-1].url.params["access_token"] == scoped_token
    else:
        assert all(call.headers["Authorization"] == f"Bearer {scoped_token}" for call in calls)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-NFR-106")
@pytest.mark.asyncio
async def test_scoped_env_file_credentials_are_loaded_and_redacted(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TESTSCOPE_FACEBOOK_ACCESS_TOKEN=file-token\nTESTSCOPE_FACEBOOK_PAGE_ID=file-page\n")
    monkeypatch.setitem(EnvironmentSettings.model_config, "env_file", (env_file,))
    monkeypatch.setenv("TESTSCOPE_FACEBOOK_ACCESS_TOKEN", "override-test-token")

    def handler(http_request: httpx.Request) -> httpx.Response:
        values = httpx.QueryParams(http_request.content.decode())
        assert values["access_token"] == "override-test-token"  # noqa: S105
        assert "file-page" in str(http_request.url)
        return httpx.Response(400, json={"error": {"code": 190, "message": "Invalid override-test-token"}})

    publisher = FacebookPublisher(settings(tmp_path), httpx.MockTransport(handler))
    assert publisher.is_configured("TESTSCOPE")
    with pytest.raises(ProviderError) as caught:
        await publisher.publish(replace(request(), env_prefix="TESTSCOPE"), tmp_path / "clip.mp4")
    assert caught.value.code == "auth_failed"
    assert "override-test-token" not in str(caught.value)
    assert "[redacted]" in str(caught.value)
