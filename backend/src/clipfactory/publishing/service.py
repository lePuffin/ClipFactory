"""Provider-independent publication orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import Platform
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.publishing import PublicationRequest, Publisher


class PublicationStore(Protocol):
    def context(self, run_id: UUID, clip_id: UUID) -> dict[str, Any]: ...

    def prepare(
        self, clip_id: UUID, platform: str, mode: str, request: dict[str, Any], status: str
    ) -> dict[str, Any]: ...

    def mark_publishing(self, publication_id: UUID) -> None: ...
    def mark_published(self, publication_id: UUID, result: dict[str, Any], published_at: datetime) -> None: ...
    def mark_failed(self, publication_id: UUID, code: str, message: str) -> None: ...

    def schedule_metrics(
        self, publication_id: UUID, published_at: datetime, offsets: list[str], now: datetime
    ) -> None: ...

    def schedule_auto_publish(self, run_id: UUID, clip_id: UUID, due_at: datetime, now: datetime) -> None: ...


class ClipStorage(Protocol):
    def local_path(self, key: str) -> Path: ...


class PublicURLFactory(Protocol):
    def __call__(self, clip_id: UUID, expires_at: datetime) -> str: ...


class MediaStaging(Protocol):
    def stage(self, clip_file: Path, signed_url: str) -> str: ...
    def release(self, staged_url: str) -> None: ...


class PublishService:
    def __init__(
        self,
        store: PublicationStore,
        storage: ClipStorage,
        publishers: Mapping[Platform, Publisher],
        *,
        clock: Any,
        public_url: PublicURLFactory | None = None,
        staging: MediaStaging | None = None,
    ) -> None:
        self._store = store
        self._storage = storage
        self._publishers = dict(publishers)
        self._clock = clock
        self._public_url = public_url
        self._staging = staging

    async def execute(self, run_id: UUID, clip_id: UUID, *, approval_resolved: bool = False) -> dict[str, Any]:
        context = await asyncio.to_thread(self._store.context, run_id, clip_id)
        if context["clip_status"] != "approved":
            raise RuntimeError("Only approved Clips may be published")
        settings = context["settings"].get("publishing", {})
        analytics = context["settings"].get("analytics", {})
        mode = str(settings.get("mode", "dry_run"))
        platforms = [Platform(value) for value in context["platforms"]]
        profile_snapshot = context.get("profile_snapshot") or {}
        env_prefix = profile_snapshot.get("env_prefix")
        request = _request(
            clip_id,
            context["social_metadata"],
            settings.get("discovery_hashtags", ["News", "BreakingNews", "WorldNews"]),
            env_prefix=env_prefix,
        )
        if mode == "disabled" or not platforms:
            return {"outcome": "not_published", "clip_id": str(clip_id)}

        if mode == "live" and bool(settings.get("approval_required", True)) and not approval_resolved:
            for platform in platforms:
                await asyncio.to_thread(
                    self._store.prepare, clip_id, platform.value, mode, _as_dict(request), "awaiting_approval"
                )
            eligibility = getattr(self._store, "auto_publish_eligible", None)
            if (
                settings.get("auto_publish_enabled", False)
                and callable(eligibility)
                and await asyncio.to_thread(eligibility, clip_id)
            ):
                now = self._clock()
                due = now + timedelta(minutes=int(settings.get("auto_publish_after_minutes", 10)))
                await asyncio.to_thread(self._store.schedule_auto_publish, run_id, clip_id, due, now)
            return {"outcome": "awaiting_approval", "clip_id": str(clip_id)}

        successes = 0
        for platform in platforms:
            existing = await asyncio.to_thread(
                self._store.prepare,
                clip_id,
                platform.value,
                mode,
                _as_dict(request),
                "dry_run" if mode == "dry_run" else "pending",
            )
            if existing["status"] in {"published", "dry_run", "failed", "rejected"}:
                successes += existing["status"] == "published"
                continue
            if existing["status"] == "publishing":
                await asyncio.to_thread(
                    self._store.mark_failed,
                    UUID(existing["id"]),
                    "unknown_outcome",
                    "Interrupted publication outcome is unknown; automatic retry is disabled",
                )
                continue
            if mode == "dry_run":
                continue
            publisher = self._publishers.get(platform)
            if publisher is None or not publisher.is_configured(request.env_prefix):
                await asyncio.to_thread(
                    self._store.mark_failed,
                    UUID(existing["id"]),
                    "not_configured",
                    f"{platform.value} publisher is not configured",
                )
                continue
            publication_id = UUID(existing["id"])
            await asyncio.to_thread(self._store.mark_publishing, publication_id)
            platform_request = request
            clip_file = self._storage.local_path(context["storage_key"])
            staged_url: str | None = None
            if platform in {Platform.INSTAGRAM, Platform.FACEBOOK}:
                if self._public_url is None:
                    await asyncio.to_thread(
                        self._store.mark_failed,
                        publication_id,
                        "not_configured",
                        "Public media URL is not configured",
                    )
                    continue
                ttl = int(settings.get("public_media_url_ttl_minutes", 60))
                public_media_url = self._public_url(clip_id, self._clock() + timedelta(minutes=ttl))
                if self._staging is not None:
                    public_media_url = await asyncio.to_thread(self._staging.stage, clip_file, public_media_url)
                    staged_url = public_media_url
                platform_request = PublicationRequest(**{**_as_dict(request), "public_media_url": public_media_url})
            try:
                result = await publisher.publish(platform_request, clip_file)
            except ProviderError as exc:
                await asyncio.to_thread(self._store.mark_failed, publication_id, exc.code, str(exc))
                continue
            finally:
                if self._staging is not None and staged_url is not None:
                    await asyncio.to_thread(self._staging.release, staged_url)
            published_at = self._clock()
            await asyncio.to_thread(
                self._store.mark_published,
                publication_id,
                {
                    "platform_post_id": result.platform_post_id,
                    "platform_url": result.platform_url,
                    "disclosure_note": result.disclosure_note,
                },
                published_at,
            )
            await asyncio.to_thread(
                self._store.schedule_metrics,
                publication_id,
                published_at,
                list(analytics.get("snapshot_offsets", ["1h", "6h", "24h", "48h", "7d", "30d"])),
                published_at,
            )
            successes += 1
        outcome = (
            "published"
            if successes == len(platforms) and platforms
            else ("partially_published" if successes else "not_published")
        )
        return {"outcome": outcome, "clip_id": str(clip_id)}


def _hashtags(generated: Sequence[str], discovery: Sequence[str], limit: int = 8) -> tuple[str, ...]:
    tags: dict[str, str] = {}
    for tag in (*generated, *discovery):
        cleaned = "".join(str(tag).lstrip("#").split())
        if cleaned and cleaned.casefold() not in tags and len(tags) < limit:
            tags[cleaned.casefold()] = cleaned
    return tuple(tags.values())


def _request(
    clip_id: UUID,
    value: dict[str, Any],
    discovery_hashtags: Sequence[str] = (),
    env_prefix: str | None = None,
) -> PublicationRequest:
    return PublicationRequest(
        clip_id=clip_id,
        title=value["title"],
        description=value["description"],
        hashtags=_hashtags(value.get("hashtags", []), discovery_hashtags),
        source_attributions=tuple(value.get("source_attributions", [])),
        asset_attributions=tuple(value.get("asset_attributions", [])),
        contains_synthetic_media=bool(value.get("contains_synthetic_media", False)),
        synthetic_voice=bool(value.get("synthetic_voice", False)),
        env_prefix=env_prefix,
    )


def _as_dict(request: PublicationRequest) -> dict[str, Any]:
    return {
        "clip_id": request.clip_id,
        "title": request.title,
        "description": request.description,
        "hashtags": request.hashtags,
        "source_attributions": request.source_attributions,
        "asset_attributions": request.asset_attributions,
        "contains_synthetic_media": request.contains_synthetic_media,
        "synthetic_voice": request.synthetic_voice,
        "public_media_url": request.public_media_url,
        "env_prefix": request.env_prefix,
    }
