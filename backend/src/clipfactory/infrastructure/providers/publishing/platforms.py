"""Concrete Publisher adapters; platform API details remain infrastructure-only."""

from __future__ import annotations

import asyncio
import json
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


class _HTTPPublisher:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=120) as client:
                response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            transient = status == 429 or status >= 500
            code = "rate_limited" if status == 429 else "auth_failed" if status in {401, 403} else "publish_failed"
            raise ProviderError(
                code,
                f"Publisher HTTP request failed with status {status}",
                transient=transient,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("publisher_unreachable", "Publisher HTTP request failed", transient=True) from exc


class YouTubePublisher(_HTTPPublisher):
    platform = Platform.YOUTUBE
    name = "youtube"

    def __init__(self, settings: EnvironmentSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport)
        self._token_file = settings.data_dir / "secrets" / "youtube_token.json"

    def is_configured(self) -> bool:
        return self._token_file.is_file()

    def _token(self) -> str:
        try:
            value = json.loads(self._token_file.read_text(encoding="utf-8"))["access_token"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("not_configured", "YouTube OAuth token is unavailable", transient=False) from exc
        return str(value)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        token = self._token()
        title = request.title[:100]
        description = _description(request)[:5000]
        initiation = await self._request(
            "POST",
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4"},
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
            headers={"Authorization": f"Bearer {token}"},
            content=await asyncio.to_thread(clip_file.read_bytes),
        )
        post_id = str(response.json()["id"])
        return PublicationResult(post_id, f"https://www.youtube.com/watch?v={post_id}")

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        response = await self._request(
            "GET",
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": platform_post_id},
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        statistics = response.json()["items"][0]["statistics"]
        return PlatformMetrics(
            views=_integer(statistics.get("viewCount")),
            likes=_integer(statistics.get("likeCount")),
            comments=_integer(statistics.get("commentCount")),
        )


class InstagramPublisher(_HTTPPublisher):
    platform = Platform.INSTAGRAM
    name = "instagram"

    def __init__(self, settings: EnvironmentSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport)
        self._token = settings.instagram_access_token.get_secret_value() if settings.instagram_access_token else None
        self._user_id = settings.instagram_user_id

    def is_configured(self) -> bool:
        return bool(self._token and self._user_id)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        if not request.public_media_url:
            raise ProviderError("not_configured", "Instagram requires a public media URL", transient=False)
        base = f"https://graph.facebook.com/v21.0/{self._user_id}"
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
        published = await self._request(
            "POST",
            f"{base}/media_publish",
            data={"creation_id": container.json()["id"], "access_token": self._token},
        )
        post_id = str(published.json()["id"])
        note = "unsupported: synthetic media and voice disclosures included in caption"
        return PublicationResult(post_id, f"https://www.instagram.com/p/{post_id}/", note)

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        response = await self._request(
            "GET",
            f"https://graph.facebook.com/v21.0/{platform_post_id}/insights",
            params={"metric": "plays,likes,comments,shares", "access_token": self._token},
        )
        values = {item["name"]: item["values"][0]["value"] for item in response.json().get("data", [])}
        return PlatformMetrics(
            views=_integer(values.get("plays")),
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
    return "\n\n".join(value for value in (request.description, hashtags, disclosure) if value)


def _integer(value: Any) -> int | None:
    return int(value) if value is not None else None


def revenue(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
