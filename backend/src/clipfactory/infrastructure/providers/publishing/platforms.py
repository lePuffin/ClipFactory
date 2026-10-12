"""Concrete Publisher adapters; platform API details remain infrastructure-only."""

from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from clipfactory.domain.models import Platform
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.publishing import (
    PlatformMetrics,
    PublicationRequest,
    PublicationResult,
)

_GRAPH_AUTH_ERROR_CODES = {102, 190}
_SECRET_PATTERN = re.compile(r"(access_token|client_secret|refresh_token)=[^&\s\"']+")
_INSTAGRAM_BASE = "https://graph.instagram.com/v21.0"


def _platform_error(response: httpx.Response) -> tuple[str, int | None, str | None]:
    """Return the platform's error text, Graph error code and OAuth error id."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300], None, None
    if not isinstance(body, dict):
        return "", None, None
    error = body.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return str(error.get("message") or ""), code if isinstance(code, int) else None, None
    if isinstance(error, str):
        return str(body.get("error_description") or error), None, error
    return "", None, None


class _HTTPPublisher:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _secrets(self) -> tuple[str, ...]:
        return ()

    def _redact(self, text: str) -> str:
        text = _SECRET_PATTERN.sub(r"\1=[redacted]", text)
        for secret in self._secrets():
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:300]

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=120) as client:
                response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail, graph_code, oauth_error = _platform_error(exc.response)
            transient = status == 429 or status >= 500
            auth = status in {401, 403} or graph_code in _GRAPH_AUTH_ERROR_CODES or oauth_error == "invalid_grant"
            code = "rate_limited" if status == 429 else "auth_failed" if auth else "publish_failed"
            message = f"Publisher HTTP request failed with status {status}"
            if detail:
                message += f": {self._redact(detail)}"
            raise ProviderError(code, message, transient=transient and not auth) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("publisher_unreachable", "Publisher HTTP request failed", transient=True) from exc


class YouTubePublisher(_HTTPPublisher):
    platform = Platform.YOUTUBE
    name = "youtube"

    def __init__(self, settings: EnvironmentSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport)
        self._client_secrets_file = settings.youtube_client_secrets_file
        beside_client = self._client_secrets_file.with_name("youtube_token.json") if self._client_secrets_file else None
        self._token_file = (
            beside_client
            if beside_client is not None and beside_client.is_file()
            else settings.data_dir / "secrets" / "youtube_token.json"
        )
        self._cached_token: str | None = None

    def is_configured(self) -> bool:
        return self._token_file.is_file()

    def _stored_token(self) -> dict[str, Any]:
        try:
            value = json.loads(self._token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError("not_configured", "YouTube OAuth token is unavailable", transient=False) from exc
        if not isinstance(value, dict) or not (value.get("access_token") or value.get("refresh_token")):
            raise ProviderError("not_configured", "YouTube OAuth token is unavailable", transient=False)
        return value

    def _client(self) -> dict[str, Any] | None:
        if self._client_secrets_file is None:
            return None
        try:
            info = json.loads(self._client_secrets_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        client = info.get("installed") or info.get("web") if isinstance(info, dict) else None
        return client if isinstance(client, dict) and client.get("client_id") and client.get("client_secret") else None

    async def _token(self) -> str:
        stored = self._stored_token()
        client = self._client()
        refresh_token = stored.get("refresh_token")
        if refresh_token and client:
            try:
                response = await self._request(
                    "POST",
                    str(client.get("token_uri") or "https://oauth2.googleapis.com/token"),
                    data={
                        "client_id": client["client_id"],
                        "client_secret": client["client_secret"],
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            except ProviderError as exc:
                if exc.code == "auth_failed":
                    raise ProviderError(
                        "auth_failed",
                        f"{exc}. Re-authorise with scripts/check_credentials.py --youtube-auth",
                        transient=False,
                    ) from exc
                raise
            self._cached_token = str(response.json()["access_token"])
            return self._cached_token
        if stored.get("access_token"):
            self._cached_token = str(stored["access_token"])
            return self._cached_token
        raise ProviderError("not_configured", "YouTube OAuth client secrets are unavailable", transient=False)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        authorization = "Bearer " + await self._token()
        title = request.title[:100]
        description = _description(request)[:5000]
        initiation = await self._request(
            "POST",
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"Authorization": authorization, "X-Upload-Content-Type": "video/mp4"},
            json={
                "snippet": {"title": title, "description": description},
                "status": {
                    "privacyStatus": "public",
                    "containsSyntheticMedia": request.contains_synthetic_media or request.synthetic_voice,
                },
            },
        )
        upload_url = initiation.headers.get("location")
        if not upload_url:
            raise ProviderError(
                "invalid_response",
                "YouTube did not return a resumable upload URL",
                transient=False,
            )
        response = await self._request(
            "PUT",
            upload_url,
            headers={"Authorization": authorization},
            content=await asyncio.to_thread(clip_file.read_bytes),
        )
        post_id = str(response.json()["id"])
        return PublicationResult(post_id, f"https://www.youtube.com/watch?v={post_id}")

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        response = await self._request(
            "GET",
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": platform_post_id},
            headers={"Authorization": "Bearer " + await self._token()},
        )
        statistics = response.json()["items"][0]["statistics"]
        return PlatformMetrics(
            views=_integer(statistics.get("viewCount")),
            likes=_integer(statistics.get("likeCount")),
            comments=_integer(statistics.get("commentCount")),
        )


class InstagramPublisher(_HTTPPublisher):
    """Instagram API with Instagram Login (graph.instagram.com user tokens)."""

    platform = Platform.INSTAGRAM
    name = "instagram"

    def __init__(
        self,
        settings: EnvironmentSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        poll_interval_seconds: float = 5.0,
        max_wait_seconds: float = 600.0,
    ) -> None:
        super().__init__(transport)
        self._token = settings.instagram_access_token.get_secret_value() if settings.instagram_access_token else None
        self._user_id = settings.instagram_user_id
        self._poll_interval = poll_interval_seconds
        self._max_wait = max_wait_seconds

    def _secrets(self) -> tuple[str, ...]:
        return (self._token or "",)

    def is_configured(self) -> bool:
        return bool(self._token and self._user_id)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        if not request.public_media_url:
            raise ProviderError("not_configured", "Instagram requires a public media URL", transient=False)
        base = f"{_INSTAGRAM_BASE}/{self._user_id}"
        container = await self._request(
            "POST",
            f"{base}/media",
            data={
                "media_type": "REELS",
                "video_url": request.public_media_url,
                "caption": (request.title + "\n\n" + _description(request))[:2200],
                "access_token": self._token,
            },
        )
        container_id = str(container.json()["id"])
        await self._wait_until_finished(container_id)
        published = await self._request(
            "POST",
            f"{base}/media_publish",
            data={"creation_id": container_id, "access_token": self._token},
        )
        post_id = str(published.json()["id"])
        permalink = await self._request(
            "GET",
            f"{_INSTAGRAM_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": self._token},
        )
        url = str(permalink.json().get("permalink") or f"https://www.instagram.com/reel/{post_id}/")
        note = "unsupported: synthetic media and voice disclosures included in caption"
        return PublicationResult(post_id, url, note)

    async def _wait_until_finished(self, container_id: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._max_wait
        while True:
            response = await self._request(
                "GET",
                f"{_INSTAGRAM_BASE}/{container_id}",
                params={"fields": "status_code,status", "access_token": self._token},
            )
            value = response.json()
            status = str(value.get("status_code") or "")
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status in {"ERROR", "EXPIRED"}:
                detail = self._redact(str(value.get("status") or status))
                raise ProviderError("publish_failed", f"Instagram media processing failed: {detail}", transient=False)
            if loop.time() >= deadline:
                raise ProviderError(
                    "publish_failed",
                    f"Instagram media processing did not finish within {self._max_wait:.0f} s",
                    transient=False,
                )
            await asyncio.sleep(self._poll_interval)

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        response = await self._request(
            "GET",
            f"{_INSTAGRAM_BASE}/{platform_post_id}/insights",
            params={"metric": "views,likes,comments,shares", "access_token": self._token},
        )
        values = {item["name"]: item["values"][0]["value"] for item in response.json().get("data", [])}
        return PlatformMetrics(
            views=_integer(values.get("views")),
            likes=_integer(values.get("likes")),
            comments=_integer(values.get("comments")),
            shares=_integer(values.get("shares")),
        )


class FacebookPublisher(_HTTPPublisher):
    platform = Platform.FACEBOOK
    name = "facebook"

    def __init__(self, settings: EnvironmentSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport)
        self._token = settings.facebook_access_token.get_secret_value() if settings.facebook_access_token else None
        self._page_id = settings.facebook_page_id.get_secret_value() if settings.facebook_page_id else None

    def _secrets(self) -> tuple[str, ...]:
        return (self._token or "",)

    def is_configured(self) -> bool:
        return bool(self._token and self._page_id)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        if not request.public_media_url:
            raise ProviderError("not_configured", "Facebook requires a public media URL", transient=False)
        response = await self._request(
            "POST",
            f"https://graph-video.facebook.com/v21.0/{self._page_id}/videos",
            data={
                "file_url": request.public_media_url,
                "title": request.title[:255],
                "description": _description(request),
                "access_token": self._token,
            },
        )
        post_id = str(response.json()["id"])
        note = "unsupported: synthetic media and voice disclosures included in description"
        return PublicationResult(post_id, f"https://www.facebook.com/{post_id}", note)

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        response = await self._request(
            "GET",
            f"https://graph.facebook.com/v21.0/{platform_post_id}",
            params={"fields": "views,likes.summary(true),comments.summary(true)", "access_token": self._token},
        )
        value = response.json()
        return PlatformMetrics(
            views=_integer(value.get("views")),
            likes=_integer(value.get("likes", {}).get("summary", {}).get("total_count")),
            comments=_integer(value.get("comments", {}).get("summary", {}).get("total_count")),
        )


def _description(request: PublicationRequest) -> str:
    hashtags = " ".join(f"#{tag.lstrip('#')}" for tag in request.hashtags)
    disclosure = (
        "Contains synthetic media and/or voice." if request.contains_synthetic_media or request.synthetic_voice else ""
    )
    sources = "Sources: " + "; ".join(request.source_attributions) if request.source_attributions else ""
    credits = "Credits: " + "; ".join(request.asset_attributions) if request.asset_attributions else ""
    return "\n\n".join(value for value in (request.description, hashtags, disclosure, sources, credits) if value)


def _integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def revenue(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
