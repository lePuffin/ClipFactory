"""Provider-neutral publishing contracts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

from clipfactory.domain.models import Platform


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    clip_id: UUID
    title: str
    description: str
    hashtags: tuple[str, ...]
    source_attributions: tuple[str, ...]
    asset_attributions: tuple[str, ...]
    contains_synthetic_media: bool
    synthetic_voice: bool
    public_media_url: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationResult:
    platform_post_id: str
    platform_url: str
    disclosure_note: str | None = None


@dataclass(frozen=True, slots=True)
class PlatformMetrics:
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    watch_time_seconds: float | None = None
    average_retention_ratio: float | None = None
    followers_delta: int | None = None
    estimated_revenue: Decimal | None = None


class Publisher(Protocol):
    platform: Platform
    name: str

    def is_configured(self) -> bool: ...

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult: ...

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics: ...


class PublicMediaReader(Protocol):
    def publishing_clip_storage_key(self, clip_id: UUID) -> str | None: ...
