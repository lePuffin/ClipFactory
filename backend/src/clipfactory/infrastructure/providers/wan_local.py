"""Lazy native Wan inference; model weights live in DATA_DIR, not the repository."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import math
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, GeneratedMedia, GenerationProgress, VideoGenerationRequest
from clipfactory.ports.media import MediaProcessError

logger = logging.getLogger(__name__)


def _missing_cached_files(error: OSError) -> bool:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, FileNotFoundError):
            return True
        # Diffusers wraps missing component weights/configs in a plain OSError.
        if isinstance(current, OSError) and (
            str(current).startswith("Error no file named ") or "does not appear to have a file named " in str(current)
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


class WanLocalVideoProvider:
    name = "wan_local"

    def __init__(
        self,
        settings: EnvironmentSettings,
        media: MediaRunner,
        *,
        pipeline_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self.media = media
        self.pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._pipeline_key: tuple[str, str] | None = None
        self._lock = threading.Lock()

    def is_configured(self) -> bool:
        return self.pipeline_factory is not None or all(
            importlib.util.find_spec(module) is not None
            for module in ("torch", "diffusers", "transformers", "accelerate", "ftfy", "sentencepiece")
        )

    def estimate_cost(self, request: VideoGenerationRequest) -> Decimal:
        return Decimal("0")

    async def generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia:
        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(10)
                if progress is not None:
                    await progress(
                        "Wan generation worker is active",
                        {"provider": self.name, "model": self.settings.wan_model, "generation_phase": "heartbeat"},
                    )

        heartbeat_task = asyncio.create_task(heartbeat())
        generation_task = asyncio.create_task(self._generate(request, destination, progress=progress))
        try:
            done, _ = await asyncio.wait({heartbeat_task, generation_task}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat_task in done:
                await heartbeat_task
            return await generation_task
        finally:
            heartbeat_task.cancel()
            generation_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            with suppress(asyncio.CancelledError):
                await generation_task

    async def _generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia:
        if not self.is_configured():
            raise ProviderError(
                "generation_dependencies_missing",
                "Install native Wan dependencies with: cd backend && uv sync --group local-gen",
                transient=False,
            )
        if request.width <= 0 or request.height <= 0 or request.duration_seconds <= 0 or not request.prompt.strip():
            raise ProviderError(
                "invalid_generation_request", "Video dimensions, duration and prompt must be valid", transient=False
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        fps = self.settings.wan_fps
        parameters: dict[str, object] = {
            "width": math.ceil(request.width / 16) * 16,
            "height": math.ceil(request.height / 16) * 16,
            "num_frames": math.ceil(max(0, request.duration_seconds * fps - 1) / 4) * 4 + 1,
            "fps": fps,
            "num_inference_steps": self.settings.wan_inference_steps,
        }
        loop = asyncio.get_running_loop()
        abort = GENERATION_ABORT.get()

        async def report(phase: str, **counts: object) -> None:
            if progress is not None:
                steps = f" · step {counts['step']}/{counts['total_steps']}" if "step" in counts else ""
                await progress(
                    f"Wan: {phase.replace('_', ' ')}{steps}",
                    {"provider": self.name, "model": self.settings.wan_model, "generation_phase": phase, **counts},
                )

        def worker_report(phase: str, **counts: object) -> None:
            if abort is not None and abort.is_set():
                raise ProviderError("generation_stopped", "Wan generation stopped by owner", transient=False)
            asyncio.run_coroutine_threadsafe(report(phase, **counts), loop).result()

        await report("waiting")
        with tempfile.TemporaryDirectory(prefix="wan-frames-", dir=destination.parent) as directory:
            frames_dir = Path(directory)
            task = asyncio.create_task(
                asyncio.to_thread(self._generate_frames, request, parameters, frames_dir, worker_report)
            )
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Threads cannot be killed; wait before deleting their output directory.
                try:
                    await task
                except ProviderError as exc:
                    logger.warning("Cancelled Wan worker finished with %s", exc.code)
                raise
            await report("encoding")
            encoding = asyncio.create_task(
                self.media.ffmpeg(
                    [
                        "-y",
                        "-framerate",
                        str(fps),
                        "-i",
                        str(frames_dir / "%06d.png"),
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-an",
                        str(destination),
                    ]
                )
            )
            try:
                await asyncio.shield(encoding)
            except asyncio.CancelledError:
                if abort is not None and abort.is_set():
                    encoding.cancel()
                try:
                    await encoding
                except asyncio.CancelledError:
                    pass
                except MediaProcessError as exc:
                    logger.warning("Cancelled Wan encoding finished with %s", exc.code)
                await asyncio.to_thread(destination.unlink, missing_ok=True)
                raise
            except MediaProcessError as exc:
                await asyncio.to_thread(destination.unlink, missing_ok=True)
                raise ProviderError(
                    "generation_encoding_failed", "Could not encode Wan frames as video", transient=False
                ) from exc
        return GeneratedMedia(destination, self.settings.wan_model, self.settings.wan_model_license, parameters)

    def _generate_frames(
        self,
        request: VideoGenerationRequest,
        parameters: dict[str, object],
        directory: Path,
        report: Callable[..., None],
    ) -> None:
        with self._lock:
            try:
                torch = importlib.import_module("torch")
                key = (self.settings.wan_model, self.settings.wan_device)
                if self._pipeline_key != key:
                    report("loading_model")
                    if key[1] == "cuda" and not torch.cuda.is_available():
                        raise ProviderError(
                            "generation_device_unavailable",
                            "WAN_DEVICE=cuda requires working CUDA; configure WAN_DEVICE=cpu or a CUDA runtime.",
                            transient=False,
                        )
                    factory = self.pipeline_factory
                    if factory is None:
                        factory = importlib.import_module("diffusers").WanPipeline.from_pretrained
                    assert factory is not None
                    loading_options = {
                        "cache_dir": str(self.settings.data_dir.expanduser().resolve() / "models/wan"),
                        "torch_dtype": torch.bfloat16 if key[1] == "cuda" else torch.float32,
                    }
                    try:
                        pipeline = factory(key[0], **loading_options, local_files_only=True)
                    except OSError as exc:
                        if Path(key[0]).is_dir() or not _missing_cached_files(exc):
                            raise
                        report("downloading_model")
                        pipeline = factory(key[0], **loading_options, local_files_only=False)
                    else:
                        report("cached_model_loaded")
                    pipeline.vae.to(dtype=torch.float32)
                    pipeline.vae.enable_tiling()
                    if key[1] == "cuda":
                        pipeline.enable_sequential_cpu_offload()
                    else:
                        pipeline.to("cpu")
                    self._pipeline, self._pipeline_key = pipeline, key
            except ProviderError:
                raise
            except (ImportError, OSError, RuntimeError, ValueError) as exc:
                raise ProviderError(
                    "generation_model_load_failed",
                    "Wan loading/download failed; check WAN_MODEL, network, disk space and local-gen installation.",
                    transient=False,
                ) from exc
            try:
                generator = torch.Generator(device="cpu").manual_seed(request.seed)
                pipeline = self._pipeline
                assert pipeline is not None
                total = int(str(parameters["num_inference_steps"]))
                report("inference", step=0, total_steps=total)

                def on_step_end(
                    pipeline: Any, step: int, timestep: Any, callback_kwargs: dict[str, Any]
                ) -> dict[str, Any]:
                    report("inference", step=step + 1, total_steps=total)
                    return callback_kwargs

                output = pipeline(
                    prompt=request.prompt,
                    negative_prompt=request.negative_prompt,
                    width=parameters["width"],
                    height=parameters["height"],
                    num_frames=parameters["num_frames"],
                    num_inference_steps=parameters["num_inference_steps"],
                    generator=generator,
                    output_type="pil",
                    callback_on_step_end=on_step_end,
                )
                frames = output.frames[0]
                if len(frames) != parameters["num_frames"]:
                    raise ProviderError(
                        "generation_invalid_output", "Wan returned an incomplete video", transient=False
                    )
                report("saving_frames")
                for index, frame in enumerate(frames):
                    frame.save(directory / f"{index:06d}.png")
            except ProviderError:
                raise
            except (OSError, RuntimeError, ValueError, IndexError) as exc:
                raise ProviderError(
                    "generation_failed",
                    "Wan inference failed; check available RAM/VRAM and generation settings.",
                    transient=False,
                ) from exc
