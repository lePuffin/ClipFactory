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
        media: MediaRunner | None,
        *,
        pipeline_factory: Callable[..., Any] | None = None,
        allow_download: bool = True,
    ) -> None:
        self.settings = settings
        self.media = media
        self.pipeline_factory = pipeline_factory
        self.allow_download = allow_download
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

    def generation_recipe(self, request: VideoGenerationRequest) -> dict[str, object]:
        if (
            request.width < 16
            or request.height < 16
            or not math.isfinite(request.duration_seconds)
            or request.duration_seconds <= 0
            or not request.prompt.strip()
        ):
            raise ProviderError(
                "invalid_generation_request", "Invalid video dimensions, duration or prompt", transient=False
            )
        long_side, short_side = max(request.width, request.height), min(request.width, request.height)
        scale = min(1, self.settings.wan_max_long_side / long_side, self.settings.wan_max_short_side / short_side)
        dimensions = []
        for value in (request.width, request.height):
            aligned = math.floor(value * scale / 16) if scale < 1 else math.ceil(value / 16)
            dimensions.append(max(16, aligned * 16))
        frames = max(1, round(request.duration_seconds * self.settings.wan_fps))
        return {
            "requested_width": request.width,
            "requested_height": request.height,
            "width": dimensions[0],
            "height": dimensions[1],
            "num_frames": frames,
            "inference_num_frames": math.ceil((frames - 1) / 4) * 4 + 1,
            "fps": self.settings.wan_fps,
            "num_inference_steps": self.settings.wan_inference_steps,
            "guidance_scale": self.settings.wan_guidance_scale,
            "flow_shift": self.settings.wan_flow_shift,
            "negative_prompt": ", ".join(
                part for part in (self.settings.wan_negative_prompt, request.negative_prompt.strip()) if part
            ),
            "encoding_crf": self.settings.wan_encoding_crf,
            "scheduler": "UniPCMultistepScheduler",
            "model_dtype": "bfloat16" if self.settings.wan_device == "cuda" else "float32",
            "vae_dtype": "float32",
            "offload_mode": "sequential" if self.settings.wan_device == "cuda" else "none",
            "seed": request.seed,
        }

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
        if self.media is None:
            raise ProviderError("generation_encoding_failed", "Wan requires a local media encoder", transient=False)
        if not self.is_configured():
            raise ProviderError(
                "generation_dependencies_missing",
                "Install native Wan dependencies with: uv sync --locked",
                transient=False,
            )
        parameters = self.generation_recipe(request)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fps = parameters["fps"]
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
                        "-frames:v",
                        str(parameters["num_frames"]),
                        "-c:v",
                        "libx264",
                        "-crf",
                        str(parameters["encoding_crf"]),
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
                        if not self.allow_download:
                            raise ProviderError(
                                "generation_model_cache_missing",
                                "Wan weights are missing from the shared cache; use --allow-download to fetch them.",
                                transient=False,
                            ) from exc
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
                pipeline.scheduler = pipeline.scheduler.from_config(
                    pipeline.scheduler.config, flow_shift=parameters["flow_shift"]
                )
                parameters["scheduler"] = type(pipeline.scheduler).__name__
                parameters["model_dtype"] = "bfloat16" if self.settings.wan_device == "cuda" else "float32"
                parameters["vae_dtype"] = "float32"
                parameters["offload_mode"] = "sequential" if self.settings.wan_device == "cuda" else "none"
                parameters["seed"] = request.seed
                total = int(str(parameters["num_inference_steps"]))
                report("inference", step=0, total_steps=total)

                def on_step_end(
                    pipeline: Any, step: int, timestep: Any, callback_kwargs: dict[str, Any]
                ) -> dict[str, Any]:
                    report("inference", step=step + 1, total_steps=total)
                    return callback_kwargs

                output = pipeline(
                    prompt=request.prompt,
                    negative_prompt=parameters["negative_prompt"],
                    width=parameters["width"],
                    height=parameters["height"],
                    num_frames=parameters["inference_num_frames"],
                    num_inference_steps=parameters["num_inference_steps"],
                    guidance_scale=parameters["guidance_scale"],
                    generator=generator,
                    output_type="pil",
                    callback_on_step_end=on_step_end,
                )
                frames = output.frames[0]
                if len(frames) != parameters["inference_num_frames"]:
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
