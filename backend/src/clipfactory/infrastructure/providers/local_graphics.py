"""Real local VideoProvider adapters for typed graphics, with no fallback."""

import asyncio
import json
import shutil
from decimal import Decimal
from pathlib import Path

from clipfactory.domain.graphics import FunctionPlot, sample_function, validate_graphics_kind
from clipfactory.infrastructure.providers.graphics_process import run_graphics_process
from clipfactory.infrastructure.providers.graphics_templates import infographic_html
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GeneratedMedia, GenerationProgress, VideoGenerationRequest


class LocalGraphicsProvider:
    name: str

    def __init__(self, settings: EnvironmentSettings) -> None:
        self.settings = settings

    def estimate_cost(self, request: VideoGenerationRequest) -> Decimal:
        return Decimal("0")

    async def generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia:
        kind = "infographic" if self.name == "hyperframes" else "scientific"
        validate_graphics_kind(kind, request.graphics_spec)
        if not self.is_configured():
            raise ProviderError("graphics_render_failed", f"Install and configure local {self.name}", transient=False)
        if not (1 <= request.duration_seconds <= 120 and 16 <= request.width <= 4096 and 16 <= request.height <= 4096):
            raise ProviderError(
                "graphics_render_failed", "Graphics render dimensions/duration are out of bounds", transient=False
            )
        spec = request.graphics_spec
        assert spec is not None
        work = destination.parent / (destination.stem + "-work")
        await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
        if progress:
            await progress(
                "Rendering graphic",
                {"generation_phase": "rendering", "renderer": self.name, "template": spec.template},
            )
        try:
            await self._render(
                request, await asyncio.to_thread(destination.resolve), await asyncio.to_thread(work.resolve), progress
            )
        except TimeoutError as exc:
            raise ProviderError("graphics_render_failed", "Local renderer timed out", transient=False) from exc
        except OSError as exc:
            raise ProviderError(
                "graphics_render_failed", "Local renderer working/output files are unavailable", transient=False
            ) from exc
        if not await asyncio.to_thread(destination.is_file) or (await asyncio.to_thread(destination.stat)).st_size == 0:
            raise ProviderError("graphics_render_failed", "Renderer produced no video", transient=False)
        return GeneratedMedia(
            destination,
            self.name,
            "MIT templates; Manim MIT; HyperFrames Apache-2.0; GSAP Standard no-charge licence; DejaVu font licence",
            {
                "renderer": self.name,
                "template": spec.template,
                "template_version": "1",
                "graphics_spec": spec.model_dump(mode="json"),
                "fps": self.settings.graphics_fps,
                "resource_licences": {
                    "template": "MIT",
                    "font": "DejaVu font licence",
                    **(
                        {"manim": "MIT"}
                        if self.name == "manim"
                        else {
                            "hyperframes": "Apache-2.0",
                            "gsap": "Standard no-charge licence",
                        }
                    ),
                },
            },
        )

    def is_configured(self) -> bool:
        raise NotImplementedError

    async def _render(
        self, request: VideoGenerationRequest, destination: Path, work: Path, progress: GenerationProgress | None
    ) -> None:
        raise NotImplementedError


class HyperFramesVideoProvider(LocalGraphicsProvider):
    name = "hyperframes"

    def is_configured(self) -> bool:
        package = self.settings.hyperframes_package_dir
        launcher = self.settings.hyperframes_path
        return bool(
            launcher
            and launcher.is_file()
            and shutil.which(self.settings.node_path)
            and (package / "node_modules/hyperframes/bin/hyperframes.mjs").is_file()
            and (package / "node_modules/gsap/dist/gsap.min.js").is_file()
        )

    async def _render(
        self, request: VideoGenerationRequest, destination: Path, work: Path, progress: GenerationProgress | None
    ) -> None:
        await asyncio.to_thread((work / "index.html").write_text, infographic_html(request), encoding="utf-8")
        await asyncio.to_thread(
            shutil.copyfile,
            self.settings.hyperframes_package_dir / "node_modules/gsap/dist/gsap.min.js",
            work / "gsap.min.js",
        )
        assert self.settings.hyperframes_path is not None
        command = [self.settings.node_path, str(self.settings.hyperframes_path.resolve())]
        async with asyncio.timeout(self.settings.graphics_timeout_seconds):
            await run_graphics_process(
                [*command, "check", str(work)],
                cwd=work,
                timeout_seconds=self.settings.graphics_timeout_seconds,
                progress=progress,
            )
            await run_graphics_process(
                [*command, "render", str(work), "--output", str(destination), "--fps", str(self.settings.graphics_fps)],
                cwd=work,
                timeout_seconds=self.settings.graphics_timeout_seconds,
                progress=progress,
            )


class ManimVideoProvider(LocalGraphicsProvider):
    name = "manim"

    def is_configured(self) -> bool:
        return bool(self.settings.manim_path and shutil.which(self.settings.manim_path))

    async def _render(
        self, request: VideoGenerationRequest, destination: Path, work: Path, progress: GenerationProgress | None
    ) -> None:
        spec = request.graphics_spec
        assert spec is not None
        assert self.settings.manim_path is not None
        executable = await asyncio.to_thread(
            Path(shutil.which(self.settings.manim_path) or self.settings.manim_path).resolve
        )
        data = {
            "spec": spec.model_dump(mode="json"),
            "duration": request.duration_seconds,
            "width": request.width,
            "height": request.height,
        }
        if isinstance(spec, FunctionPlot):
            data["samples"] = sample_function(spec)
        await asyncio.to_thread((work / "input.json").write_text, json.dumps(data), encoding="utf-8")
        await asyncio.to_thread(shutil.copyfile, Path(__file__).with_name("manim_scene.txt"), work / "scene.py")
        await run_graphics_process(
            [
                str(executable),
                "render",
                "--renderer",
                "cairo",
                "--disable_caching",
                "--resolution",
                f"{request.width},{request.height}",
                "--fps",
                str(self.settings.graphics_fps),
                "--media_dir",
                str(work / "media"),
                "--output_file",
                "graphic",
                str(work / "scene.py"),
                "ClipFactoryGraphic",
            ],
            cwd=work,
            timeout_seconds=self.settings.graphics_timeout_seconds,
            progress=progress,
        )
        outputs = list((work / "media" / "videos").glob("**/graphic.mp4"))
        if len(outputs) != 1:
            raise ProviderError("graphics_render_failed", "Manim output was missing or ambiguous", transient=False)
        await asyncio.to_thread(shutil.copyfile, outputs[0], destination)
