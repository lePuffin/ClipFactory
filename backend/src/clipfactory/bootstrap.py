"""Composition root for the single-process application."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import insert, select, text
from sqlalchemy.engine import Engine
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from clipfactory.analytics.service import MetricCollector
from clipfactory.api.app import create_app, settings_snapshot
from clipfactory.domain.models import ContentProfile, Platform, Stage
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.catalogue_repository import CatalogueRepository
from clipfactory.infrastructure.db.checkpointer import open_postgres_checkpointer
from clipfactory.infrastructure.db.configuration_repository import ConfigurationRepository
from clipfactory.infrastructure.db.evaluation_repository import EvaluationRepository
from clipfactory.infrastructure.db.models import ContentProfileRow
from clipfactory.infrastructure.db.production_repository import ProductionRepository
from clipfactory.infrastructure.db.publishing_repository import PublishingRepository
from clipfactory.infrastructure.db.render_revision_repository import RenderRevisionRepository
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.research_repository import ResearchRepository
from clipfactory.infrastructure.db.scheduler_repository import DailyScheduleRepository
from clipfactory.infrastructure.db.session import create_database_engine, create_session_factory
from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.infrastructure.llm_governance import DragonflyLLMState, GovernedLLMCalls
from clipfactory.infrastructure.media.previews import CandidatePreviews
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.infrastructure.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from clipfactory.infrastructure.providers.local_graphics import HyperFramesVideoProvider, ManimVideoProvider
from clipfactory.infrastructure.providers.media_sources import (
    PexelsMediaSource,
    PixabayMediaSource,
    UnsplashMediaSource,
    WikimediaCommonsMediaSource,
)
from clipfactory.infrastructure.providers.news.rss import RssNewsSource
from clipfactory.infrastructure.providers.publishing import FacebookPublisher, InstagramPublisher, YouTubePublisher
from clipfactory.infrastructure.providers.publishing.retrying import RetryingPublisher
from clipfactory.infrastructure.providers.transcription.whisper_local import WhisperLocalTranscriptionProvider
from clipfactory.infrastructure.providers.tts.google import GoogleTTSProvider
from clipfactory.infrastructure.providers.wan_local import WanLocalVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.settings_validation import ProviderCallSettings, apply_runtime_environment
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.publishing.approval import ApprovalService
from clipfactory.publishing.media_urls import create_public_media_url
from clipfactory.publishing.service import PublicURLFactory, PublishService
from clipfactory.research.manual_url import ManualURLClaimExtractor, ManualURLIngest
from clipfactory.research.service import ResearchUseCase
from clipfactory.workflow import manual_url_stage
from clipfactory.workflow.executor import ProductionStageExecutor
from clipfactory.workflow.graph import build_workflow
from clipfactory.workflow.lifecycle_scheduler import CompositeScheduler, LifecycleScheduler
from clipfactory.workflow.llm_activity import ObservedLLMProvider
from clipfactory.workflow.manual_claim_stage import ClaimExtractionStageUseCase
from clipfactory.workflow.production_stages import (
    PersistedEvaluationStatus,
    ProductionStageService,
    production_stage_handlers,
)
from clipfactory.workflow.publishing_stage import PublishStageUseCase
from clipfactory.workflow.research_stages import research_stage_handlers
from clipfactory.workflow.runner import RunLifecycleService, WorkflowRunner
from clipfactory.workflow.saved_news_render import SavedNewsRenderer
from clipfactory.workflow.scheduler import DailyRunScheduler


def create_application(settings: EnvironmentSettings | None = None) -> FastAPI:
    configured = settings or EnvironmentSettings()
    engine = create_database_engine(configured)
    sessions = create_session_factory(engine)
    run_repository = RunRepository(sessions)
    asset_repository = AssetRepository(sessions)
    publishing_repository = PublishingRepository(sessions)
    catalogue_repository = CatalogueRepository(sessions)
    evaluation_repository = EvaluationRepository(sessions)
    production_repository = ProductionRepository(sessions)
    research_repository = ResearchRepository(sessions)
    schedule_repository = DailyScheduleRepository(sessions)
    configuration_repository = ConfigurationRepository(sessions, clock=lambda: datetime.now(UTC))
    storage_provider = LocalStorageProvider(configured.data_dir)
    http_provider = SafeHTTPClient()
    # Providers read this copy so each Run's saved settings apply without touching the .env baseline.
    run_settings = configured.model_copy()
    llm_governance = GovernedLLMCalls(
        sessions,
        run_settings,
        DragonflyLLMState(configured.dragonfly_url.get_secret_value()),
        clock=lambda: datetime.now(UTC),
    )
    llm_provider = ObservedLLMProvider(
        OpenAICompatibleLLMProvider(run_settings), run_repository, governance=llm_governance
    )
    news_provider = RssNewsSource(http_provider)
    tts_provider = GoogleTTSProvider(configured)
    transcription_provider = WhisperLocalTranscriptionProvider(run_settings)
    media_runner = MediaRunner(configured.ffmpeg_path, configured.ffprobe_path)
    video_providers = (
        (WanLocalVideoProvider(run_settings, media_runner),)
        if "wan_local" in {name.strip() for name in configured.video_providers.split(",")}
        else ()
    )
    available_media_sources = {
        "pexels": PexelsMediaSource(
            http_provider,
            storage_provider,
            api_key=configured.pexels_api_key.get_secret_value() if configured.pexels_api_key else None,
        ),
        "pixabay": PixabayMediaSource(
            http_provider,
            storage_provider,
            api_key=configured.pixabay_api_key.get_secret_value() if configured.pixabay_api_key else None,
        ),
        "unsplash": UnsplashMediaSource(
            http_provider,
            storage_provider,
            api_key=configured.unsplash_access_key.get_secret_value() if configured.unsplash_access_key else None,
        ),
        "wikimedia_commons": WikimediaCommonsMediaSource(
            http_provider,
            storage_provider,
            user_agent=configured.wikimedia_user_agent or "ClipFactory/1.0 (private news production)",
        ),
    }
    media_sources = tuple(
        available_media_sources[name.strip()]
        for name in configured.media_sources.split(",")
        if name.strip() in available_media_sources
    )
    available_publishers = {
        Platform.YOUTUBE: YouTubePublisher(configured),
        Platform.INSTAGRAM: InstagramPublisher(configured),
        Platform.FACEBOOK: FacebookPublisher(configured),
    }
    selected_publishers = {
        platform: RetryingPublisher(publisher)
        for platform, publisher in available_publishers.items()
        if platform.value in {value.strip() for value in configured.publishers.split(",") if value.strip()}
    }
    research_use_case = ResearchUseCase(
        news_sources=(news_provider,),
        fetcher=http_provider,
        llm=llm_provider,
        repository=research_repository,
        events=run_repository,
    )
    manual_ingest = ManualURLIngest(http_provider, research_repository)
    manual_claim_extractor = ManualURLClaimExtractor(llm_provider, research_repository)
    public_url_factory = _public_url_factory(configured)
    publish_service = PublishService(
        publishing_repository,
        storage_provider,
        selected_publishers,
        clock=lambda: datetime.now(UTC),
        public_url=public_url_factory,
    )
    approval_service = ApprovalService(publishing_repository, publish_service, clock=lambda: datetime.now(UTC))
    metric_collector = MetricCollector(publishing_repository, selected_publishers)
    production_service = ProductionStageService(
        production=production_repository,
        runs=run_repository,
        assets=asset_repository,
        evaluations=evaluation_repository,
        storage=storage_provider,
        llm=llm_provider,
        tts=tts_provider,
        transcription=transcription_provider,
        media=media_runner,
        clock=lambda: datetime.now(UTC),
        media_sources=media_sources,
        video_providers=video_providers,
        graphics_providers=(HyperFramesVideoProvider(run_settings), ManimVideoProvider(run_settings)),
        candidate_preview=CandidatePreviews(http_provider, asset_repository, storage_provider, media_runner),
    )
    stage_handlers = {
        **research_stage_handlers(research_use_case, research_repository, run_repository),
        **production_stage_handlers(production_service),
        Stage.INGEST_URL: manual_url_stage.ManualURLStageUseCase(manual_ingest, run_repository),
        Stage.EXTRACT_CLAIMS: ClaimExtractionStageUseCase(manual_claim_extractor, research_repository, run_repository),
        Stage.PUBLISH: PublishStageUseCase(publish_service),
    }
    stage_executor = ProductionStageExecutor(
        stage_handlers,
        evaluation_status=PersistedEvaluationStatus(evaluation_repository),
    )
    lifecycle: RunLifecycleService | None = None

    def prepare_run(snapshot: Mapping[str, Any]) -> None:
        apply_runtime_environment(run_settings, configured, snapshot.get("environment", {}))
        policy = ProviderCallSettings.model_validate(snapshot.get("providers", {}))
        llm_provider.configure_retries(
            max_call_retries=policy.max_call_retries,
            call_retry_base_delay_seconds=policy.call_retry_base_delay_seconds,
            call_retry_max_delay_seconds=policy.call_retry_max_delay_seconds,
            llm_max_schema_repairs=policy.llm_max_schema_repairs,
        )

    async def check_health() -> dict[str, bool | str | None]:
        def database_ready() -> bool:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True

        try:
            database_ok = await asyncio.to_thread(database_ready)
        except Exception:
            database_ok = False
        data_dir = configured.data_dir.expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return {
            "database": database_ok,
            "ffmpeg": shutil.which(configured.ffmpeg_path) is not None,
            "ffprobe": shutil.which(configured.ffprobe_path) is not None,
            "data_directory_writable": data_dir.is_dir() and bool(data_dir.stat().st_mode & 0o222),
            "scheduler_liveness": lifecycle.scheduler_alive if lifecycle else not configured.scheduler_enabled,
        }

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        nonlocal lifecycle
        async with open_postgres_checkpointer(configured.database_url.get_secret_value()) as checkpointer:
            application.state.checkpointer = checkpointer
            graph = build_workflow(stage_executor, checkpointer=checkpointer, stage_observer=run_repository)
            runner = WorkflowRunner(
                run_repository,
                graph,
                clock=lambda: datetime.now(UTC),
                default_stage_timeout_seconds=1800,
                prepare_run=prepare_run,
            )
            application.state.workflow_runner = runner
            daily_scheduler = DailyRunScheduler(
                schedule_repository,
                run_repository,
                clock=lambda: datetime.now(UTC),
                settings_snapshot=lambda: configuration_repository.settings(settings_snapshot(configured)),
                grace_minutes=60,
            )
            scheduler = CompositeScheduler(
                daily_scheduler,
                LifecycleScheduler(
                    publishing_repository,
                    metric_collector,
                    approval_service,
                    clock=lambda: datetime.now(UTC),
                ),
            )
            lifecycle = RunLifecycleService(
                runner,
                scheduler_enabled=configured.scheduler_enabled,
                scheduler=scheduler,
                scheduler_poll_interval_seconds=30,
            )
            application.state.run_lifecycle = lifecycle
            await lifecycle.start()
            try:
                yield
            finally:
                await lifecycle.stop()
                lifecycle = None

    render_revision_repository = RenderRevisionRepository(sessions)
    saved_news_renderer = SavedNewsRenderer(
        repository=render_revision_repository,
        assets=asset_repository,
        storage=storage_provider,
        media=media_runner,
        font_file=configured.data_dir / "fonts/NotoSans-Bold.ttf",
        clock=lambda: datetime.now(UTC),
    )

    async def continue_run(run_id: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
        return await application.state.workflow_runner.continue_run(run_id, snapshot)

    async def stop_run(run_id: UUID) -> dict[str, Any]:
        return await application.state.workflow_runner.stop_run(run_id)

    application = create_app(
        configured,
        check_health,
        run_repository,
        asset_repository,
        lifespan=lifespan,
        storage_provider=storage_provider,
        public_media_reader=publishing_repository,
        run_creator=run_repository,
        configuration=configuration_repository,
        approvals=approval_service,
        analytics=publishing_repository,
        catalogue=catalogue_repository,
        budget_reader=catalogue_repository,
        dashboard_reader=catalogue_repository,
        saved_news_renderer=saved_news_renderer,
        render_revision_reader=render_revision_repository,
        continue_run=continue_run,
        stop_run=stop_run,
    )
    application.state.engine = engine
    application.state.run_repository = run_repository
    application.state.asset_repository = asset_repository
    application.state.storage_provider = storage_provider
    application.state.publishing_repository = publishing_repository
    application.state.evaluation_repository = evaluation_repository
    application.state.production_repository = production_repository
    application.state.stage_executor = stage_executor
    application.state.prepare_run = prepare_run
    application.state.providers = {
        "llm": llm_provider,
        "news": news_provider,
        "tts": tts_provider,
        "transcription": transcription_provider,
        "media_sources": media_sources,
        "video": video_providers,
        "publishers": selected_publishers,
    }
    mount_frontend(application, Path(__file__).resolve().parents[3] / "frontend" / "dist")
    return application


def mount_frontend(application: FastAPI, distribution: Path) -> None:
    root = distribution.resolve()
    index_file = root / "index.html"
    if not index_file.is_file():
        return
    assets = root / "assets"
    if assets.is_dir():
        application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @application.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(index_file)

    @application.get("/{frontend_path:path}", include_in_schema=False, response_model=None)
    async def frontend_route(frontend_path: str) -> Response:
        if frontend_path == "api" or frontend_path.startswith("api/"):
            return JSONResponse(
                status_code=404, content={"error": {"code": "not_found", "message": "API route not found"}}
            )
        target = (root / frontend_path).resolve()
        return FileResponse(target if target.is_relative_to(root) and target.is_file() else index_file)


def upgrade_database(settings: EnvironmentSettings | None = None) -> None:
    from alembic import command
    from alembic.config import Config

    configured = settings or EnvironmentSettings()
    backend_path = Path(__file__).resolve().parents[2]
    migration_config = Config(str(backend_path / "alembic.ini"))
    migration_config.set_main_option("script_location", str(backend_path / "migrations"))
    migration_config.set_main_option("sqlalchemy.url", configured.database_url.get_secret_value().replace("%", "%%"))
    command.upgrade(migration_config, "head")


def seed_defaults(settings: EnvironmentSettings | None = None) -> None:
    configured = settings or EnvironmentSettings()
    engine = create_database_engine(configured)
    try:
        with engine.begin() as connection:
            active_profile = connection.scalar(
                select(ContentProfileRow.id).where(ContentProfileRow.is_active.is_(True)).limit(1)
            )
            if active_profile is None:
                profile = ContentProfile()
                connection.execute(
                    insert(ContentProfileRow).values(
                        id=profile.id,
                        name=profile.name,
                        is_active=True,
                        value=profile.model_dump(mode="json"),
                        updated_at=datetime.now(UTC),
                    )
                )
    finally:
        engine.dispose()


def engine_for_application(settings: EnvironmentSettings) -> Engine:
    return create_database_engine(settings)


def _public_url_factory(settings: EnvironmentSettings) -> PublicURLFactory | None:
    if settings.public_media_base_url is None or settings.media_url_signing_key is None:
        return None
    base_url = settings.public_media_base_url
    signing_key = settings.media_url_signing_key.get_secret_value().encode()

    def signed_url(clip_id: UUID, expires_at: datetime) -> str:
        now = datetime.now(UTC)
        ttl_minutes = max(5, min(1440, int((expires_at - now).total_seconds() / 60)))
        return create_public_media_url(base_url, clip_id, now=now, ttl_minutes=ttl_minutes, key=signing_key)

    return cast(PublicURLFactory, signed_url)
