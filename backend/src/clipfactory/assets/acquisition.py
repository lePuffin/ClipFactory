"""Acquire one licensed external Asset after library reuse has failed."""

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import uuid4

from clipfactory.assets.importing import AssetImportError, AssetWriter, ImportProvenance, import_asset_file
from clipfactory.assets.selection import AssetRequirement, rank_media_candidates
from clipfactory.domain.models import Asset, AssetOrigin
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.media import MediaInspector, MediaProcessError
from clipfactory.ports.media_sources import MediaCandidate, MediaSearchRequest, MediaSourceProvider
from clipfactory.ports.storage import MediaStorage

Progress = Callable[[str, dict[str, object]], Awaitable[None]]
Result = TypeVar("Result")
Pool = list[tuple[MediaCandidate, MediaSourceProvider]]


async def _with_retry[R](
    call: Callable[[], Awaitable[R]],
    *,
    max_call_retries: int,
    retry_base_delay_seconds: float,
    retry_max_delay_seconds: float,
    report: Callable[..., Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]],
) -> R:
    for attempt in range(max_call_retries):
        try:
            return await call()
        except ProviderError as exc:
            if not exc.transient:
                raise
            delay = min(
                retry_max_delay_seconds,
                max(
                    retry_base_delay_seconds * 2**attempt * (1 + random.SystemRandom().random()),
                    exc.retry_after_seconds or 0,
                ),
            )
            await report(f"Media call retry in {delay:.1f}s: {exc.code}", error_code=exc.code)
            await sleep(delay)
    return await call()


async def search_media_candidates(
    requirement: AssetRequirement,
    *,
    providers: Sequence[MediaSourceProvider],
    excluded_urls: frozenset[str] = frozenset(),
    candidates_per_search: int = 10,
    max_call_retries: int = 3,
    retry_base_delay_seconds: float = 2,
    retry_max_delay_seconds: float = 60,
    progress: Progress | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Pool:
    """Search every provider and return candidates in deterministic preliminary rank order."""

    async def report(message: str, **payload: object) -> None:
        if progress is not None:
            await progress(message, payload)

    request = MediaSearchRequest(
        requirement.description, requirement.media_type, requirement.subjects, requirement.tags, candidates_per_search
    )
    pool: Pool = []
    for provider in providers:
        try:
            await report(f"Searching {provider.name} for {requirement.description}", provider=provider.name)
            found = await _with_retry(
                lambda source=provider: source.search(request),
                max_call_retries=max_call_retries,
                retry_base_delay_seconds=retry_base_delay_seconds,
                retry_max_delay_seconds=retry_max_delay_seconds,
                report=report,
                sleep=sleep,
            )
            pool.extend((candidate, provider) for candidate in found if candidate.url not in excluded_urls)
        except ProviderError as exc:
            await report(f"{provider.name} search failed: {exc}", provider=provider.name, error_code=exc.code)
    ranked = rank_media_candidates(requirement, [candidate for candidate, _ in pool])
    return [(chosen, next(source for candidate, source in pool if candidate is chosen)) for chosen in ranked]


async def acquire_asset(
    requirement: AssetRequirement,
    *,
    providers: Sequence[MediaSourceProvider],
    storage: MediaStorage,
    assets: AssetWriter,
    media: MediaInspector,
    now: datetime,
    excluded_urls: frozenset[str] = frozenset(),
    candidates_per_search: int = 10,
    max_image_bytes: int = 20000000,
    max_video_bytes: int = 300000000,
    max_call_retries: int = 3,
    retry_base_delay_seconds: float = 2,
    retry_max_delay_seconds: float = 60,
    progress: Progress | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    excluded_asset_ids: frozenset[str] = frozenset(),
    candidates: Pool | None = None,
) -> Asset | None:
    """Import the first usable candidate; reviewed `candidates` keep their order and skip search."""

    async def report(message: str, **payload: object) -> None:
        if progress is not None:
            await progress(message, payload)

    async def retry(call: Callable[[], Awaitable[Result]]) -> Result:
        return await _with_retry(
            call,
            max_call_retries=max_call_retries,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            report=report,
            sleep=sleep,
        )

    if candidates is None:
        candidates = await search_media_candidates(
            requirement,
            providers=providers,
            excluded_urls=excluded_urls,
            candidates_per_search=candidates_per_search,
            max_call_retries=max_call_retries,
            retry_base_delay_seconds=retry_base_delay_seconds,
            retry_max_delay_seconds=retry_max_delay_seconds,
            progress=progress,
            sleep=sleep,
        )
    for chosen, provider in candidates:
        if chosen.url in excluded_urls:
            continue
        temporary_key = f"work/media-downloads/{uuid4()}.media"
        try:
            await report(
                f"Downloading {provider.name} {chosen.media_type}: {chosen.description}", source_url=chosen.url
            )
            limit = max_video_bytes if chosen.media_type == "video" else max_image_bytes
            downloaded = await retry(
                lambda source=provider, candidate=chosen, destination=temporary_key, size_limit=limit: source.download(
                    candidate, destination, size_limit
                )
            )
            result = await import_asset_file(
                storage.local_path(downloaded.storage_key),
                category=requirement.category,
                provenance=ImportProvenance(
                    license=chosen.license,
                    author=chosen.author,
                    source_url=chosen.url,
                    license_url=chosen.license_url,
                    attribution_required=chosen.attribution_required,
                    attribution_text=chosen.attribution_text,
                    origin=AssetOrigin.EXTERNAL,
                    provider=chosen.source,
                    download_url=chosen.download_url,
                ),
                storage=storage,
                assets=assets,
                now=now,
                description=chosen.description or requirement.description,
                tags=requirement.tags,
                subjects=requirement.subjects,
                max_image_bytes=max_image_bytes,
                max_video_bytes=max_video_bytes,
                min_image_short_side_px=requirement.min_width,
                min_video_height_px=requirement.min_height,
                media_inspector=media,
                expected_media_type=chosen.media_type,
            )
            if str(result.asset.id) in excluded_asset_ids:
                await report("Downloaded content is already used in this Clip", asset_id=str(result.asset.id))
                continue
            await report(
                f"Acquired {chosen.media_type} from {provider.name}",
                asset_id=str(result.asset.id),
                source_url=chosen.url,
            )
            return result.asset
        except (ProviderError, AssetImportError, MediaProcessError) as exc:
            await report(f"{provider.name} acquisition failed: {exc}", provider=provider.name, error_code=exc.code)
        finally:
            await asyncio.to_thread(storage.local_path(temporary_key).unlink, missing_ok=True)
    return None
