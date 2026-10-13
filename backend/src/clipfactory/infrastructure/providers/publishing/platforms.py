"""Concrete Publisher adapters; platform API details remain infrastructure-only."""

from __future__ import annotations

import asyncio
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

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


def _resolve_env(settings: EnvironmentSettings, var_name: str, env_prefix: str | None) -> str | None:
    if not env_prefix:
        return None
    key = f"{env_prefix}_{var_name}"
    value = os.environ.get(key)
    if value is None:
        files = settings.model_config.get("env_file") or ()
        if isinstance(files, (str, Path)):
            files = (files,)
        for file in files:
            values = dotenv_values(file, interpolate=False)
            if key in values:
                value = values[key]
    return value.strip() if value else None


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
        oauth_id = str(code) if isinstance(code, str) and ("token" in code or "auth" in code) else None
        return str(error.get("message") or ""), code if isinstance(code, int) else None, oauth_id
    if isinstance(error, str):
        return str(body.get("error_description") or error), None, error
    return "", None, None


class _HTTPPublisher:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _secrets(self) -> tuple[str, ...]:
        return ()

    def _redact(self, text: str, secrets: tuple[str, ...] = ()) -> str:
        text = _SECRET_PATTERN.sub(r"\1=[redacted]", text)
        for secret in (*self._secrets(), *secrets):
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:300]

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        secrets: list[str] = []
        for section in ("data", "params", "headers"):
            values = kwargs.get(section)
            if isinstance(values, dict):
                for key, value in values.items():
                    if str(key).lower() in {"access_token", "refresh_token", "client_secret", "authorization"}:
                        secrets.append(str(value).removeprefix("Bearer "))
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=120) as client:
                response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            detail, graph_code, oauth_error = _platform_error(exc.response)
            transient = status == 429 or status >= 500
            auth = (
                status in {401, 403}
                or graph_code in _GRAPH_AUTH_ERROR_CODES
                or oauth_error in {"invalid_grant", "access_token_invalid", "token_expired", "invalid_token"}
            )
            code = "rate_limited" if status == 429 else "auth_failed" if auth else "publish_failed"
            message = f"Publisher HTTP request failed with status {status}"
            if detail:
                message += f": {self._redact(detail, tuple(secrets))}"
            raise ProviderError(code, message, transient=transient and not auth) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("publisher_unreachable", "Publisher HTTP request failed", transient=True) from exc


class YouTubePublisher(_HTTPPublisher):
    platform = Platform.YOUTUBE
    name = "youtube"

    def __init__(self, settings: EnvironmentSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(transport)
        self._settings = settings
        self._client_secrets_file = settings.youtube_client_secrets_file
        beside_client = self._client_secrets_file.with_name("youtube_token.json") if self._client_secrets_file else None
        self._token_file = (
            beside_client
            if beside_client is not None and beside_client.is_file()
            else settings.data_dir / "secrets" / "youtube_token.json"
        )
        self._cached_token: str | None = None

    def is_configured(self, env_prefix: str | None = None) -> bool:
        return self._get_token_file(env_prefix).is_file()

    def _get_token_file(self, env_prefix: str | None = None) -> Path:
        scoped_path = _resolve_env(self._settings, "YOUTUBE_TOKEN_FILE", env_prefix)
        if scoped_path:
            return Path(scoped_path)
        if env_prefix:
            prefix = env_prefix.lower()
            scoped_file = self._settings.data_dir / "secrets" / f"{prefix}_youtube_token.json"
            return scoped_file
        return self._token_file

    def _get_client_secrets_file(self, env_prefix: str | None = None) -> Path | None:
        scoped_path = _resolve_env(self._settings, "YOUTUBE_CLIENT_SECRETS_FILE", env_prefix)
        if scoped_path:
            return Path(scoped_path)
        if env_prefix:
            prefix = env_prefix.lower()
            scoped_file = self._settings.data_dir / "secrets" / f"{prefix}_client_secrets.json"
            return scoped_file
        return self._client_secrets_file

    def _stored_token(self, env_prefix: str | None = None) -> dict[str, Any]:
        token_file = self._get_token_file(env_prefix)
        try:
            value = json.loads(token_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderError("not_configured", "YouTube OAuth token is unavailable", transient=False) from exc
        if not isinstance(value, dict) or not (value.get("access_token") or value.get("refresh_token")):
            raise ProviderError("not_configured", "YouTube OAuth token is unavailable", transient=False)
        return value

    def _client(self, env_prefix: str | None = None) -> dict[str, Any] | None:
        client_secrets_file = self._get_client_secrets_file(env_prefix)
        if client_secrets_file is None:
            return None
        try:
            info = json.loads(client_secrets_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        client = info.get("installed") or info.get("web") if isinstance(info, dict) else None
        return client if isinstance(client, dict) and client.get("client_id") and client.get("client_secret") else None

    async def _token(self, env_prefix: str | None = None) -> str:
        stored = self._stored_token(env_prefix)
        client = self._client(env_prefix)
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
        authorization = "Bearer " + await self._token(request.env_prefix)
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

    async def fetch_metrics(self, platform_post_id: str, env_prefix: str | None = None) -> PlatformMetrics:
        response = await self._request(
            "GET",
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "statistics", "id": platform_post_id},
            headers={"Authorization": "Bearer " + await self._token(env_prefix)},
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
        self._settings = settings
        self._token = settings.instagram_access_token.get_secret_value() if settings.instagram_access_token else None
        self._user_id = settings.instagram_user_id
        self._poll_interval = poll_interval_seconds
        self._max_wait = max_wait_seconds

    def _secrets(self) -> tuple[str, ...]:
        return (self._token or "",)

    def _resolve_credentials(self, env_prefix: str | None = None) -> tuple[str | None, str | None]:
        if not env_prefix:
            return self._token, self._user_id
        token = _resolve_env(self._settings, "INSTAGRAM_ACCESS_TOKEN", env_prefix)
        user_id = _resolve_env(self._settings, "INSTAGRAM_USER_ID", env_prefix)
        return token, user_id

    def is_configured(self, env_prefix: str | None = None) -> bool:
        token, user_id = self._resolve_credentials(env_prefix)
        return bool(token and user_id)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        token, user_id = self._resolve_credentials(request.env_prefix)
        if not (token and user_id):
            raise ProviderError("not_configured", "Instagram credentials are not configured", transient=False)
        if not request.public_media_url:
            raise ProviderError("not_configured", "Instagram requires a public media URL", transient=False)
        base = f"{_INSTAGRAM_BASE}/{user_id}"
        container = await self._request(
            "POST",
            f"{base}/media",
            data={
                "media_type": "REELS",
                "video_url": request.public_media_url,
                "caption": (request.title + "\n\n" + _description(request))[:2200],
                "access_token": token,
            },
        )
        container_id = str(container.json()["id"])
        await self._wait_until_finished(container_id, token)
        published = await self._request(
            "POST",
            f"{base}/media_publish",
            data={"creation_id": container_id, "access_token": token},
        )
        post_id = str(published.json()["id"])
        permalink = await self._request(
            "GET",
            f"{_INSTAGRAM_BASE}/{post_id}",
            params={"fields": "permalink", "access_token": token},
        )
        url = str(permalink.json().get("permalink") or f"https://www.instagram.com/reel/{post_id}/")
        note = "unsupported: synthetic media and voice disclosures included in caption"
        return PublicationResult(post_id, url, note)

    async def _wait_until_finished(self, container_id: str, token: str | None = None) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._max_wait
        auth_token = token or self._token
        while True:
            response = await self._request(
                "GET",
                f"{_INSTAGRAM_BASE}/{container_id}",
                params={"fields": "status_code,status", "access_token": auth_token},
            )
            value = response.json()
            status = str(value.get("status_code") or "")
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status in {"ERROR", "EXPIRED"}:
                detail = self._redact(str(value.get("status") or status), (auth_token or "",))
                raise ProviderError("publish_failed", f"Instagram media processing failed: {detail}", transient=False)
            if loop.time() >= deadline:
                raise ProviderError(
                    "publish_failed",
                    f"Instagram media processing did not finish within {self._max_wait:.0f} s",
                    transient=False,
                )
            await asyncio.sleep(self._poll_interval)

    async def fetch_metrics(self, platform_post_id: str, env_prefix: str | None = None) -> PlatformMetrics:
        token, user_id = self._resolve_credentials(env_prefix)
        if not (token and user_id):
            raise ProviderError("not_configured", "Instagram credentials are not configured", transient=False)
        response = await self._request(
            "GET",
            f"{_INSTAGRAM_BASE}/{platform_post_id}/insights",
            params={"metric": "views,likes,comments,shares", "access_token": token},
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
        self._settings = settings
        self._token = settings.facebook_access_token.get_secret_value() if settings.facebook_access_token else None
        self._page_id = settings.facebook_page_id.get_secret_value() if settings.facebook_page_id else None

    def _secrets(self) -> tuple[str, ...]:
        return (self._token or "",)

    def _resolve_credentials(self, env_prefix: str | None = None) -> tuple[str | None, str | None]:
        if not env_prefix:
            return self._token, self._page_id
        token = _resolve_env(self._settings, "FACEBOOK_ACCESS_TOKEN", env_prefix)
        page_id = _resolve_env(self._settings, "FACEBOOK_PAGE_ID", env_prefix)
        return token, page_id

    def is_configured(self, env_prefix: str | None = None) -> bool:
        token, page_id = self._resolve_credentials(env_prefix)
        return bool(token and page_id)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        token, page_id = self._resolve_credentials(request.env_prefix)
        if not (token and page_id):
            raise ProviderError("not_configured", "Facebook credentials are not configured", transient=False)
        if not request.public_media_url:
            raise ProviderError("not_configured", "Facebook requires a public media URL", transient=False)
        response = await self._request(
            "POST",
            f"https://graph-video.facebook.com/v21.0/{page_id}/videos",
            data={
                "file_url": request.public_media_url,
                "title": request.title[:255],
                "description": _description(request),
                "access_token": token,
            },
        )
        post_id = str(response.json()["id"])
        note = "unsupported: synthetic media and voice disclosures included in description"
        return PublicationResult(post_id, f"https://www.facebook.com/{post_id}", note)

    async def fetch_metrics(self, platform_post_id: str, env_prefix: str | None = None) -> PlatformMetrics:
        token, page_id = self._resolve_credentials(env_prefix)
        if not (token and page_id):
            raise ProviderError("not_configured", "Facebook credentials are not configured", transient=False)
        response = await self._request(
            "GET",
            f"https://graph.facebook.com/v21.0/{platform_post_id}",
            params={"fields": "views,likes.summary(true),comments.summary(true)", "access_token": token},
        )
        value = response.json()
        return PlatformMetrics(
            views=_integer(value.get("views")),
            likes=_integer(value.get("likes", {}).get("summary", {}).get("total_count")),
            comments=_integer(value.get("comments", {}).get("summary", {}).get("total_count")),
        )


class TikTokPublisher(_HTTPPublisher):
    platform = Platform.TIKTOK
    name = "tiktok"

    def __init__(
        self,
        settings: EnvironmentSettings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 120.0,
    ) -> None:
        super().__init__(transport)
        self._client_key = settings.tiktok_client_key.get_secret_value() if settings.tiktok_client_key else None
        self._client_secret = (
            settings.tiktok_client_secret.get_secret_value() if settings.tiktok_client_secret else None
        )
        self._token = (
            settings.tiktok_access_token.get_secret_value()
            if hasattr(settings, "tiktok_access_token") and settings.tiktok_access_token
            else None
        )
        self._settings = settings
        self._token_file = settings.data_dir / "secrets" / "tiktok_token.json"
        self._poll_interval = poll_interval_seconds
        self._max_wait = max_wait_seconds

    def _secrets(self) -> tuple[str, ...]:
        return tuple(secret for secret in (self._token, self._client_secret) if secret)

    def is_configured(self, env_prefix: str | None = None) -> bool:
        if env_prefix:
            token_file = self._get_token_file(env_prefix)
            return bool(
                _resolve_env(self._settings, "TIKTOK_ACCESS_TOKEN", env_prefix) or (token_file and token_file.is_file())
            )
        if self._token:
            return True
        if self._token_file and self._token_file.is_file():
            return True
        return bool(self._client_key and self._client_secret)

    def _get_token_file(self, env_prefix: str | None = None) -> Path | None:
        scoped_path = _resolve_env(self._settings, "TIKTOK_TOKEN_FILE", env_prefix)
        if scoped_path:
            return Path(scoped_path)
        if env_prefix:
            return self._token_file.parent / f"{env_prefix.lower()}_tiktok_token.json"
        return self._token_file

    async def _resolve_token(self, env_prefix: str | None = None) -> str:
        scoped_token = _resolve_env(self._settings, "TIKTOK_ACCESS_TOKEN", env_prefix) if env_prefix else self._token
        if scoped_token:
            return scoped_token
        token_file = self._get_token_file(env_prefix)
        if token_file and token_file.is_file():
            try:
                data = json.loads(token_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    tok = data.get("access_token")
                    if tok:
                        return str(tok)
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderError("not_configured", "TikTok OAuth token is unavailable", transient=False) from exc
        if env_prefix:
            raise ProviderError("not_configured", "TikTok scoped OAuth credentials are not configured", transient=False)
        client_key = self._client_key
        client_secret = self._client_secret
        if client_key and client_secret:
            response = await self._request(
                "POST",
                "https://open.tiktokapis.com/v2/oauth/token/",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
            )
            data = response.json()
            tok = data.get("access_token") or data.get("data", {}).get("access_token")
            if tok:
                return str(tok)
            raise ProviderError(
                "auth_failed", "Failed to obtain TikTok access token from client credentials", transient=False
            )
        raise ProviderError("not_configured", "TikTok OAuth credentials are not configured", transient=False)

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        token = await self._resolve_token(request.env_prefix)
        title = _description(request)[:2200]
        is_synthetic = bool(request.contains_synthetic_media or request.synthetic_voice)
        post_info = {
            "title": title,
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
            "video_cover_timestamp_ms": 1000,
            "is_aigc": is_synthetic,
        }

        if request.public_media_url:
            source_info = {
                "source": "PULL_FROM_URL",
                "video_url": request.public_media_url,
            }
            init_payload = {
                "post_info": post_info,
                "source_info": source_info,
            }
            response = await self._request(
                "POST",
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=init_payload,
            )
            resp_data = response.json()
            err = resp_data.get("error")
            if isinstance(err, dict) and err.get("code") not in (None, "ok", 0, ""):
                err_code = str(err.get("code"))
                auth = err_code in {"access_token_invalid", "token_expired", "invalid_token", "scope_not_authorized"}
                raise ProviderError(
                    "auth_failed" if auth else "publish_failed",
                    f"TikTok API error: {err.get('message') or err_code}",
                    transient=False,
                )

            data = resp_data.get("data", {})
            publish_id = str(
                data.get("publish_id") or resp_data.get("publish_id") or f"tt_pub_{request.clip_id.hex[:8]}"
            )
            post_id = publish_id
        else:
            file_bytes = await asyncio.to_thread(clip_file.read_bytes)
            file_size = len(file_bytes)
            source_info = {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": file_size,
                "total_chunk_count": 1,
            }
            init_payload = {
                "post_info": post_info,
                "source_info": source_info,
            }
            response = await self._request(
                "POST",
                "https://open.tiktokapis.com/v2/post/publish/video/init/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=init_payload,
            )
            resp_data = response.json()
            err = resp_data.get("error")
            if isinstance(err, dict) and err.get("code") not in (None, "ok", 0, ""):
                err_code = str(err.get("code"))
                auth = err_code in {"access_token_invalid", "token_expired", "invalid_token", "scope_not_authorized"}
                raise ProviderError(
                    "auth_failed" if auth else "publish_failed",
                    f"TikTok API error: {err.get('message') or err_code}",
                    transient=False,
                )

            data = resp_data.get("data", {})
            publish_id = str(
                data.get("publish_id") or resp_data.get("publish_id") or f"tt_pub_{request.clip_id.hex[:8]}"
            )
            upload_url = data.get("upload_url")
            if upload_url:
                await self._request(
                    "PUT",
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
                    },
                    content=file_bytes,
                )
            post_id = publish_id

        note = "synthetic media and voice disclosures mapped to TikTok is_aigc parameter"
        return PublicationResult(post_id, f"https://www.tiktok.com/@clipfactory/video/{post_id}", note)

    async def fetch_metrics(self, platform_post_id: str, env_prefix: str | None = None) -> PlatformMetrics:
        token = await self._resolve_token(env_prefix)
        response = await self._request(
            "POST",
            "https://open.tiktokapis.com/v2/video/query/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "filters": {"video_ids": [platform_post_id]},
                "fields": ["like_count", "comment_count", "share_count", "view_count"],
            },
        )
        data = response.json().get("data", {})
        videos = data.get("videos", [])
        if videos and isinstance(videos, list):
            item = videos[0]
            return PlatformMetrics(
                views=_integer(item.get("view_count")),
                likes=_integer(item.get("like_count")),
                comments=_integer(item.get("comment_count")),
                shares=_integer(item.get("share_count")),
            )
        return PlatformMetrics()


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
