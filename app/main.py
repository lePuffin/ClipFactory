"""Application composition and local development entry point."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import register_error_handlers, router
from app.core.config import Settings, get_settings
from app.pipelines.dispatch import JobDispatcher, JobProcessor
from app.pipelines.generate_reel import ReelGenerationPipeline
from app.pipelines.process import ProcessingPipeline
from app.services.article_ingestion import ArticleIngestionService
from app.services.broll_selection import BRollSelector
from app.services.composition import ReelCompositionService
from app.services.crop import SmartCropper
from app.services.ffmpeg import FFmpegService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.llm import OpenRouterClipSelector
from app.services.runner import JobRunner
from app.services.script_generation import OpenRouterScriptGenerator
from app.services.transcription import FasterWhisperTranscriber
from app.services.tts import resolve_tts_service
from app.services.youtube import YoutubeDownloader

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    files: FileManager
    jobs: JobStore
    ffmpeg: FFmpegService
    runner: JobRunner


def build_container(
    settings: Settings,
    runner_factory: Callable[[JobProcessor], JobRunner] = JobRunner,
) -> ApplicationContainer:
    """Create the one local application graph without global mutable service singletons."""
    files = FileManager(settings)
    files.initialize()
    jobs = JobStore(settings.data_dir)
    ffmpeg = FFmpegService(output_width=settings.output_width, output_height=settings.output_height)
    cropper = SmartCropper.from_settings(settings)
    transcriber = FasterWhisperTranscriber(settings)
    youtube = YoutubeDownloader()
    clip_pipeline = ProcessingPipeline(
        settings=settings,
        files=files,
        jobs=jobs,
        ffmpeg=ffmpeg,
        transcriber=transcriber,
        selector=OpenRouterClipSelector(settings),
        cropper=cropper,
        youtube=youtube,
    )
    reel_pipeline = ReelGenerationPipeline(
        settings=settings,
        files=files,
        jobs=jobs,
        ffmpeg=ffmpeg,
        article_ingestion=ArticleIngestionService(),
        transcriber=transcriber,
        script_generator=OpenRouterScriptGenerator(settings),
        tts=resolve_tts_service(settings),
        broll_selector=BRollSelector(),
        composer=ReelCompositionService(ffmpeg, cropper),
        youtube=youtube,
    )
    dispatcher = JobDispatcher(jobs, clip_pipeline, reel_pipeline)
    return ApplicationContainer(
        settings=settings,
        files=files,
        jobs=jobs,
        ffmpeg=ffmpeg,
        runner=runner_factory(dispatcher),
    )


def create_app(
    settings: Settings | None = None,
    runner_factory: Callable[[JobProcessor], JobRunner] = JobRunner,
) -> FastAPI:
    """Create a self-contained local application instance."""
    application_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = build_container(application_settings, runner_factory)
        app.state.container = container
        logger.info("ClipFactory started with output directory %s", application_settings.output_dir)
        try:
            yield
        finally:
            container.runner.shutdown()

    app = FastAPI(title="ClipFactory", version="0.2.0", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    """Run the local web application with the packaged development defaults."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
