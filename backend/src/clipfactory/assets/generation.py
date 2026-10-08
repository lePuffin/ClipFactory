"""Generate, validate and import video only after media selection has failed."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from datetime import datetime
from uuid import uuid4

from clipfactory.assets.acquisition import Progress
from clipfactory.assets.importing import AssetImportError, AssetWriter, ImportProvenance, import_asset_file
from clipfactory.domain.models import Asset, AssetOrigin
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, VideoGenerationRequest, VideoProvider
from clipfactory.ports.media import MediaInspector, MediaProcessError
from clipfactory.ports.storage import MediaStorage


async def generate_video_asset(
    request: VideoGenerationRequest,
    *,
    providers: Sequence[VideoProvider],
    storage: MediaStorage,
    assets: AssetWriter,
    media: MediaInspector,
    now: datetime,
    progress: Progress,
    max_video_bytes: int,
    min_video_height_px: int,
    subjects: Sequence[str] = (),
    tags: Sequence[str] = (),
    excluded_asset_ids: frozenset[str] = frozenset(),
    start_permit: Callable[[str], Awaitable[bool]] | None = None,
) -> Asset | None:
    task = asyncio.create_task(
        _generate_video_asset(
            request,
            providers=providers,
            storage=storage,
            assets=assets,
            media=media,
            now=now,
            progress=progress,
            max_video_bytes=max_video_bytes,
            min_video_height_px=min_video_height_px,
            subjects=subjects,
            tags=tags,
            excluded_asset_ids=excluded_asset_ids,
            start_permit=start_permit,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        abort = GENERATION_ABORT.get()
        if abort is not None and abort.is_set():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        # Keep expensive output safe even if shutdown cancels the caller again.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise


async def _generate_video_asset(
    request: VideoGenerationRequest,
    *,
    providers: Sequence[VideoProvider],
    storage: MediaStorage,
    assets: AssetWriter,
    media: MediaInspector,
    now: datetime,
    progress: Progress,
    max_video_bytes: int,
    min_video_height_px: int,
    subjects: Sequence[str],
    tags: Sequence[str],
    excluded_asset_ids: frozenset[str],
    start_permit: Callable[[str], Awaitable[bool]] | None,
) -> Asset | None:
    for provider in providers:
        if not provider.is_configured():
            if request.graphics_spec is not None:
                raise ProviderError(
                    "graphics_render_failed",
                    f"{provider.name} is not configured; install its local dependencies and set its executable path.",
                    transient=False,
                )
            await progress(
                f"{provider.name} is not configured; check optional generation dependencies and environment.",
                {"provider": provider.name, "generation_phase": "skipped", "error_code": "generation_not_configured"},
            )
            continue
        # This fallback currently wires local, zero-cost adapters only.
        if provider.estimate_cost(request) != 0:
            raise ProviderError(
                "generation_budget_required", "Paid generation requires budget governance", transient=False
            )
        key = f"generated-media/pending/{uuid4()}.mp4"
        metadata_key = key + ".json"
        destination = storage.local_path(key)
        imported_successfully = False
        metadata: dict[str, object] = {
            "provider": provider.name,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "seed": request.seed,
            "width": request.width,
            "height": request.height,
            "duration_seconds": request.duration_seconds,
            "subjects": list(subjects),
            "tags": list(tags),
            "graphics_spec": request.graphics_spec.model_dump(mode="json") if request.graphics_spec else None,
        }
        await storage.put_bytes(metadata_key, json.dumps(metadata).encode())
        try:
            if start_permit is not None and not await start_permit(provider.name):
                await asyncio.to_thread(storage.local_path(metadata_key).unlink, missing_ok=True)
                continue
            await progress(
                "Rendering graphic"
                if request.graphics_spec
                else f"Generating illustrative video with {provider.name}; checking shared local model cache.",
                {
                    "provider": provider.name,
                    "seed": request.seed,
                    "generation_phase": "starting" if start_permit is not None else "started",
                },
            )
            generated = await provider.generate(request, destination, progress=progress)
            if generated.path != destination or generated.cost != 0:
                raise ProviderError(
                    "invalid_generation_output", "Generator returned unexpected output or cost", transient=False
                )
            metadata.update(
                {"model": generated.model, "license": generated.license, "parameters": generated.parameters}
            )
            await storage.put_bytes(metadata_key, json.dumps(metadata).encode())
            await progress(
                "Validating rendered graphic" if request.graphics_spec else "Validating generated video",
                {"provider": provider.name, "model": generated.model, "generation_phase": "validating"},
            )
            if request.graphics_spec is not None:
                probe = await media.probe(destination)
                streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
                fps = generated.parameters.get("fps")
                if not isinstance(fps, int) or fps < 1 or len(streams) != 1:
                    raise ProviderError("graphics_render_failed", "Invalid rendered video stream", transient=False)
                stream = streams[0]
                try:
                    rate = str(stream.get("r_frame_rate", "0/1")).split("/")
                    actual_fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 0
                    duration = float(probe.get("format", {}).get("duration", 0))
                    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
                except (ValueError, TypeError, OverflowError) as exc:
                    raise ProviderError(
                        "graphics_render_failed", "Invalid rendered stream measurements", transient=False
                    ) from exc
                if (
                    width != request.width
                    or height != request.height
                    or not math.isfinite(actual_fps)
                    or not math.isfinite(duration)
                    or abs(actual_fps - fps) > 0.001
                    or abs(duration - request.duration_seconds) > 1 / fps + 0.001
                ):
                    raise ProviderError(
                        "graphics_render_failed",
                        "Rendered dimensions, FPS or duration did not match request",
                        transient=False,
                    )
            imported = await import_asset_file(
                destination,
                category=(
                    "chart"
                    if request.graphics_spec and request.graphics_spec.template in {"comparison", "function_plot"}
                    else "graphic"
                    if request.graphics_spec
                    else "broll"
                ),
                provenance=ImportProvenance(
                    license=generated.license,
                    origin=AssetOrigin.RENDERED if request.graphics_spec else AssetOrigin.GENERATED,
                    provider=provider.name,
                    generation={
                        "provider": provider.name,
                        "model": generated.model,
                        "prompt": request.prompt,
                        "negative_prompt": request.negative_prompt,
                        "seed": request.seed,
                        "parameters": generated.parameters,
                    },
                ),
                storage=storage,
                assets=assets,
                now=now,
                description=request.prompt,
                subjects=subjects,
                tags=[*tags, "rendered" if request.graphics_spec else "generated"],
                max_video_bytes=max_video_bytes,
                min_video_height_px=min_video_height_px,
                media_inspector=media,
                expected_media_type="video",
            )
            imported_successfully = True
            if str(imported.asset.id) in excluded_asset_ids:
                await progress(
                    "Generated media duplicates a shot already used in this Clip",
                    {"provider": provider.name, "generation_phase": "failed", "error_code": "generation_duplicate"},
                )
                continue
            await progress(
                (
                    "Rendered graphic validated and imported"
                    if request.graphics_spec
                    else "Generated video validated and imported"
                ),
                {
                    "provider": provider.name,
                    "model": generated.model,
                    "generation_phase": "completed",
                    "asset_id": str(imported.asset.id),
                },
            )
            return imported.asset
        except (ProviderError, AssetImportError, MediaProcessError) as exc:
            await progress(
                f"{provider.name} generation failed: {exc}; staging retained for recovery at {key}",
                {
                    "provider": provider.name,
                    "generation_phase": "failed",
                    "error_code": exc.code,
                    "recovery_storage_key": key,
                    "metadata_storage_key": metadata_key,
                },
            )
            if request.graphics_spec is not None:
                raise ProviderError("graphics_render_failed", str(exc), transient=False) from exc
        finally:
            if imported_successfully:
                await asyncio.to_thread(destination.unlink, missing_ok=True)
                await asyncio.to_thread(storage.local_path(metadata_key).unlink, missing_ok=True)
    return None
