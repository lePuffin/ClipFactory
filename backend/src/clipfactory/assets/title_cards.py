"""Use case for creating and reusing deterministic rendered title-card Assets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from clipfactory.assets.title_card import render_title_card
from clipfactory.domain.models import Asset, AssetOrigin, Provenance
from clipfactory.ports.storage import MediaStorage


class AssetWriter(Protocol):
    def by_hash(self, sha256: str) -> Asset | None: ...

    def save(self, asset: Asset) -> Asset: ...


@dataclass(frozen=True, slots=True)
class TitleCardResult:
    asset: Asset
    reused: bool


async def create_title_card_asset(
    text: str,
    *,
    storage: MediaStorage,
    assets: AssetWriter,
    now: datetime,
    width: int = 720,
    height: int = 1280,
    font_file: Path | None = None,
) -> TitleCardResult:
    rendered = render_title_card(text, width=width, height=height, font_file=font_file)
    existing = await asyncio.to_thread(assets.by_hash, rendered.sha256)
    if existing is not None and await storage.exists(existing.storage_key):
        return TitleCardResult(existing, True)
    key = f"assets/{rendered.sha256[:2]}/{rendered.sha256}.png"
    await storage.put_bytes(key, rendered.png_bytes)
    asset = Asset(
        media_type="image",
        category="title_card",
        storage_key=key,
        sha256=rendered.sha256,
        mime_type="image/png",
        size_bytes=len(rendered.png_bytes),
        width=width,
        height=height,
        description=rendered.text,
        tags=["title_card", "fallback"],
        subjects=[],
        provenance=Provenance(
            origin=AssetOrigin.RENDERED,
            provider="clipfactory_title_card",
            license="CC0",
            acquired_at=now,
        ),
        reusable=True,
    )
    stored = await asyncio.to_thread(assets.save, asset)
    return TitleCardResult(stored, stored.id != asset.id)
