"""Render one CompositionSpec and atomically store a successfully probed Clip."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec
from clipfactory.ports.storage import MediaStorage


class MediaExecutor(Protocol):
    async def ffmpeg(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[bytes, bytes]: ...

    async def probe(self, media_path: Any) -> dict[str, Any]: ...

    async def decode(self, media_path: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class RenderedClip:
    storage_key: str
    sha256: str
    probe: dict[str, Any]
    size_bytes: int


async def freeze_end_card(source: Path, *, storage: MediaStorage, runner: MediaExecutor, key: str) -> tuple[Path, str]:
    digest = await storage.put_file(source, key)
    path = storage.local_path(key)
    probe = await runner.probe(path)
    streams = probe.get("streams", [])
    video = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio = [stream for stream in streams if stream.get("codec_type") == "audio"]
    duration = float(probe.get("format", {}).get("duration", 0))
    if len(video) != 1 or len(audio) != 1 or abs(duration - 3) > 1 / 30:
        raise ValueError("End card must contain one video and one audio stream lasting three seconds")
    await runner.decode(path)
    return path, digest


async def render_clip(
    spec: CompositionSpec,
    *,
    storage: MediaStorage,
    runner: MediaExecutor,
    final_key: str,
) -> RenderedClip:
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)
    spec.output_path.unlink(missing_ok=True)
    try:
        await runner.ffmpeg(build_ffmpeg_command(spec))
        probe = await runner.probe(spec.output_path)
        await runner.decode(spec.output_path)
        digest = await storage.put_file(spec.output_path, final_key)
        size = await asyncio.to_thread(storage.local_path(final_key).stat)
        return RenderedClip(final_key, digest, probe, size.st_size)
    finally:
        await asyncio.to_thread(spec.output_path.unlink, missing_ok=True)
