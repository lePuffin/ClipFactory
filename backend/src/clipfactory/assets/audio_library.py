"""Owner-supplied licensed music and SFX manifest import."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from clipfactory.assets.importing import AssetWriter
from clipfactory.domain.models import Asset, AssetOrigin, MusicInfo, Platform, Provenance
from clipfactory.ports.media import MediaInspector
from clipfactory.ports.storage import MediaStorage


class AudioLibraryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = Field(min_length=1)
    category: Literal["music", "sfx"]
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_url: str | None = None
    license: str = Field(min_length=1)
    license_url: str | None = None
    attribution_required: bool = False
    attribution_text: str | None = None
    tags: list[str] = Field(default_factory=list)
    genre: str = "news"
    mood: list[str] = Field(default_factory=lambda: ["news", "neutral"])
    energy: Literal["low", "medium", "high"] = "low"
    loopable: bool = False
    allowed_platforms: list[Platform] | None = None


class AudioLibraryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[AudioLibraryEntry] = Field(min_length=1)


async def import_audio_entry(
    entry: AudioLibraryEntry,
    *,
    base_directory: Path,
    assets: AssetWriter,
    storage: MediaStorage,
    media: MediaInspector,
    now: datetime,
    max_bytes: int = 50_000_000,
) -> Asset:
    base = await asyncio.to_thread(base_directory.resolve)
    path = await asyncio.to_thread((base / entry.file).resolve)
    if not path.is_relative_to(base) or not await asyncio.to_thread(path.is_file):
        raise ValueError("Audio manifest path is missing or escapes the manifest directory")
    size = await asyncio.to_thread(lambda: path.stat().st_size)
    if not 0 < size <= max_bytes or not entry.license.strip():
        raise ValueError("Audio file size or licence is invalid")
    provenance = Provenance(
        origin=AssetOrigin.IMPORTED,
        provider=entry.source,
        license=entry.license.strip(),
        author=entry.artist,
        source_url=entry.source_url,
        license_url=entry.license_url,
        attribution_required=entry.attribution_required,
        attribution_text=entry.attribution_text,
        acquired_at=now,
        allowed_platforms=entry.allowed_platforms,
    )
    probe = await media.probe(path)
    streams = probe.get("streams", [])
    if len([stream for stream in streams if stream.get("codec_type") == "audio"]) != 1 or any(
        stream.get("codec_type") == "video" for stream in streams
    ):
        raise ValueError("Audio library requires one audio stream and no video")
    duration = float(probe.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("Audio library file has invalid duration")
    await media.decode(path)
    body = await asyncio.to_thread(path.read_bytes)
    digest = hashlib.sha256(body).hexdigest()
    existing = await asyncio.to_thread(assets.by_hash, digest)
    if existing is not None:
        if existing.category != entry.category:
            raise ValueError("Existing audio content has an incompatible library category")
        return existing
    extension = path.suffix.lower().lstrip(".")
    if extension not in {"wav", "mp3", "ogg", "flac", "m4a"}:
        raise ValueError("Unsupported audio library file format")
    key = f"assets/{digest[:2]}/{digest}.{extension}"
    await storage.put_bytes(key, body)
    music = (
        MusicInfo(
            title=entry.title,
            artist=entry.artist,
            genre=entry.genre,
            mood=entry.mood,
            energy=entry.energy,
            loopable=entry.loopable,
            allowed_platforms=entry.allowed_platforms,
        )
        if entry.category == "music"
        else None
    )
    asset = Asset(
        media_type="audio",
        category=entry.category,
        storage_key=key,
        sha256=digest,
        mime_type={
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
        }[extension],
        size_bytes=size,
        duration_seconds=duration,
        description=entry.title,
        tags=entry.tags,
        provenance=provenance,
        music=music,
        reusable=True,
        created_at=now,
    )
    return await asyncio.to_thread(assets.save, asset)
