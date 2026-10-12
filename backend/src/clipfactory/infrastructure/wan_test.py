"""Isolated owner-triggered Wan test, using the production adapter and shared cache."""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import tempfile
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from typing import Any

from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.infrastructure.providers.wan_local import WanLocalVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import VideoGenerationRequest


async def run_wan_test(
    settings: EnvironmentSettings,
    request: VideoGenerationRequest,
    output: Path,
    *,
    dry_run: bool = False,
    allow_download: bool = False,
) -> dict[str, Any]:
    output = await asyncio.to_thread(lambda: output.expanduser().absolute())
    manifest = output.with_suffix(output.suffix + ".json")
    if output.suffix.lower() != ".mp4":
        raise ValueError("Wan test output must be an .mp4 file")
    if output.exists() or manifest.exists():
        raise FileExistsError("Wan test output or recipe manifest already exists; choose a new output path")
    # Recipe inspection needs no binaries, CUDA runtime, model load or network.
    provider = WanLocalVideoProvider(settings, media=None, allow_download=allow_download)
    recipe: dict[str, Any] = {
        "provider": provider.name,
        "model": settings.wan_model,
        "prompt": request.prompt,
        "seed": request.seed,
        "device": settings.wan_device,
        "allow_download": allow_download,
        "cache_dir": str(settings.data_dir.expanduser().resolve() / "models/wan"),
        "output": str(output),
        "parameters": provider.generation_recipe(request),
    }
    print(json.dumps(recipe, ensure_ascii=False, indent=2), flush=True)
    if dry_run:
        return recipe

    media = MediaRunner(settings.ffmpeg_path, settings.ffprobe_path)
    provider.media = media
    output.parent.mkdir(parents=True, exist_ok=True)
    owned: list[Path] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        if payload.get("generation_phase") != "heartbeat":
            print(message, flush=True)

    try:
        with ExitStack() as stack:
            video_file = stack.enter_context(output.open("xb"))
            owned.append(output)
            recipe_file = stack.enter_context(manifest.open("x", encoding="utf-8"))
            owned.append(manifest)
            directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="wan-test-", dir=output.parent))
            generated = await provider.generate(request, Path(directory) / "generated.mp4", progress=progress)
            probe = await media.probe(generated.path)
            await media.decode(generated.path)
            streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "video"]
            parameters = generated.parameters
            duration = float(probe.get("format", {}).get("duration", 0))
            if (
                len(streams) != 1
                or int(streams[0].get("width", 0)) != parameters["width"]
                or int(streams[0].get("height", 0)) != parameters["height"]
                or int(streams[0].get("nb_frames", 0)) != parameters["num_frames"]
                or float(Fraction(str(streams[0].get("r_frame_rate", "0")))) != parameters["fps"]
                or not math.isfinite(duration)
                or abs(duration - int(str(parameters["num_frames"])) / int(str(parameters["fps"]))) > 0.001
            ):
                raise ProviderError(
                    "generation_invalid_output", "Wan test output does not match recipe", transient=False
                )
            recipe.update({"parameters": parameters, "probe": probe, "validated": True})

            def save() -> None:
                with generated.path.open("rb") as source:
                    shutil.copyfileobj(source, video_file)
                json.dump(recipe, recipe_file, ensure_ascii=False, indent=2)
                recipe_file.write("\n")

            saving = asyncio.create_task(asyncio.to_thread(save))
            try:
                await asyncio.shield(saving)
            except asyncio.CancelledError:
                await saving
                raise
    except BaseException:
        for path in owned:
            path.unlink(missing_ok=True)
        raise
    print(f"Wan test validated: {output}\nRecipe: {manifest}", flush=True)
    return recipe
