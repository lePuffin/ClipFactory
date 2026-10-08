"""Use case for importing owner-supplied local media files as Assets (CF-REQ-216)."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from clipfactory.domain.models import Asset, AssetOrigin, Provenance
from clipfactory.ports.media import MediaInspector
from clipfactory.ports.storage import MediaStorage

# `music` is excluded until `MusicInfo` (required iff category = music) exists in the domain model.
IMPORTABLE_CATEGORIES = frozenset({"photo", "broll", "illustration", "graphic", "chart", "map", "other"})


class AssetImportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AssetWriter(Protocol):
    def by_hash(self, sha256: str) -> Asset | None: ...

    def save(self, asset: Asset) -> Asset: ...


@dataclass(frozen=True, slots=True)
class ImportProvenance:
    license: str
    author: str | None = None
    source_url: str | None = None
    license_url: str | None = None
    attribution_required: bool = False
    attribution_text: str | None = None
    origin: AssetOrigin = AssetOrigin.IMPORTED
    provider: str = "manual_import"
    download_url: str | None = None
    generation: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AssetImportResult:
    asset: Asset
    reused: bool


@dataclass(frozen=True, slots=True)
class _DetectedMedia:
    media_type: str
    mime_type: str
    extension: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None


async def import_asset_file(
    source: Path,
    *,
    category: str,
    provenance: ImportProvenance,
    storage: MediaStorage,
    assets: AssetWriter,
    now: datetime,
    description: str = "",
    tags: Sequence[str] = (),
    subjects: Sequence[str] = (),
    max_image_bytes: int = 20_000_000,
    max_video_bytes: int = 300_000_000,
    max_audio_bytes: int = 50_000_000,
    min_image_short_side_px: int = 0,
    min_video_height_px: int = 0,
    media_inspector: MediaInspector | None = None,
    expected_media_type: str | None = None,
) -> AssetImportResult:
    if not provenance.license.strip():
        raise AssetImportError("missing_license", "Imported Assets require a licence")
    if not category.strip() or (provenance.origin == AssetOrigin.IMPORTED and category not in IMPORTABLE_CATEGORIES):
        raise AssetImportError("unsupported_category", f"Category {category!r} cannot be imported")
    try:
        asset_provenance = Provenance(
            origin=provenance.origin,
            provider=provenance.provider,
            license=provenance.license.strip(),
            author=provenance.author,
            source_url=provenance.source_url,
            download_url=provenance.download_url,
            license_url=provenance.license_url,
            attribution_required=provenance.attribution_required,
            attribution_text=provenance.attribution_text,
            acquired_at=now,
            generation=provenance.generation,
        )
    except ValidationError as exc:
        raise AssetImportError("invalid_provenance", "Imported Asset provenance is invalid") from exc

    limits = {"image": max_image_bytes, "video": max_video_bytes, "audio": max_audio_bytes}
    detected = await asyncio.to_thread(_inspect, source, limits)
    if expected_media_type is not None and detected.media_type != expected_media_type:
        raise AssetImportError("invalid_media", "Downloaded media type does not match the selected candidate")
    if detected.media_type == "image" and min(detected.width or 0, detected.height or 0) < min_image_short_side_px:
        raise AssetImportError("resolution_too_low", "Image short side is below the configured minimum")
    if detected.media_type == "video" and media_inspector is not None:
        try:
            probe = await media_inspector.probe(source)
            video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
            duration = float(probe["format"]["duration"])
            if duration <= 0 or int(video["height"]) < min_video_height_px:
                raise AssetImportError("resolution_too_low", "Video height or duration is below the configured minimum")
            await media_inspector.decode(source)
            detected = replace(
                detected, width=int(video["width"]), height=int(video["height"]), duration_seconds=duration
            )
        except (KeyError, StopIteration, ValueError) as exc:
            if isinstance(exc, AssetImportError):
                raise
            raise AssetImportError("invalid_media", "Downloaded video cannot be decoded") from exc

    existing = await asyncio.to_thread(assets.by_hash, detected.sha256)
    if existing is not None and await storage.exists(existing.storage_key):
        return AssetImportResult(existing, True)

    key = f"assets/{detected.sha256[:2]}/{detected.sha256}.{detected.extension}"
    stored_hash = await storage.put_file(source, key)
    if stored_hash != detected.sha256:
        raise AssetImportError("file_changed", "File content changed during import")
    asset = Asset(
        media_type=detected.media_type,
        category=category,
        storage_key=key,
        sha256=detected.sha256,
        mime_type=detected.mime_type,
        size_bytes=detected.size_bytes,
        width=detected.width,
        height=detected.height,
        duration_seconds=detected.duration_seconds,
        description=description.strip(),
        tags=sorted({tag.strip().casefold() for tag in tags if tag.strip()}),
        subjects=[subject.strip() for subject in subjects if subject.strip()],
        provenance=asset_provenance,
        reusable=True,
        created_at=now,
    )
    saved = await asyncio.to_thread(assets.save, asset)
    return AssetImportResult(saved, saved.id != asset.id)


def _inspect(source: Path, limits: dict[str, int]) -> _DetectedMedia:
    size = source.stat().st_size
    if size <= 0:
        raise AssetImportError("invalid_media", "Imported file is empty")
    if size > max(limits.values()):
        raise AssetImportError("file_too_large", "Imported file exceeds the size limit")
    with source.open("rb") as media_file:
        header = media_file.read(16)
    media_type, mime_type, extension = _sniff(header)
    if size > limits[media_type]:
        raise AssetImportError("file_too_large", "Imported file exceeds the size limit")
    width = height = None
    if media_type == "image":
        try:
            with Image.open(source) as image:
                image.verify()
                width, height = image.size
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise AssetImportError("invalid_media", "Imported image cannot be decoded") from exc
    digest = hashlib.sha256()
    with source.open("rb") as media_file:
        while chunk := media_file.read(1024 * 1024):
            digest.update(chunk)
    return _DetectedMedia(media_type, mime_type, extension, size, digest.hexdigest(), width, height)


def _sniff(header: bytes) -> tuple[str, str, str]:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png", "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg", "jpg"
    if header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE6 == 0xE2):
        return "audio", "audio/mpeg", "mp3"
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio", "audio/wav", "wav"
    if header[4:8] == b"ftyp":
        return "video", "video/mp4", "mp4"
    raise AssetImportError("invalid_media", "Imported file type is not supported")
