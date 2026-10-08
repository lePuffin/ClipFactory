"""FastAPI application and security boundary."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from clipfactory.assets.importing import AssetImportError, ImportProvenance, import_asset_file
from clipfactory.domain.models import Asset, AssetStatus, ContentProfile, RunTrigger
from clipfactory.infrastructure.http import SafeHTTPClient, UnsafeURL
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.settings_validation import (
    ProviderCallSettings,
    runtime_environment_defaults,
    validate_settings_section,
)
from clipfactory.ports.assets import AssetRepository as AssetRepositoryPort
from clipfactory.ports.publishing import PublicMediaReader
from clipfactory.ports.runs import (
    ActiveRunConflict,
    LLMBudgetExhausted,
    RunContinuationConflict,
    RunCreator,
    RunNotFound,
    RunReader,
)
from clipfactory.ports.storage import MediaStorage
from clipfactory.publishing.media_urls import verify_media_token
from clipfactory.workflow.saved_news_render import RenderRevisionResponse, SavedNewsRenderRequest

HealthCheck = Callable[[], Awaitable[dict[str, bool | str | None]]]
URLValidator = Callable[[str], Awaitable[None]]
Clock = Callable[[], datetime]
logger = logging.getLogger(__name__)


class RunSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    run_id: UUID
    trigger: str
    status: str
    outcome: str | None = None
    current_stage: str | None = None
    attempt: int
    revision_retries_used: int
    failure_stage: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    cost_total: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class RunEventResponse(BaseModel):
    sequence: int
    type: str
    stage: str | None = None
    attempt: int
    level: str
    message: str
    payload: dict[str, Any]
    created_at: str


class EvaluationResponse(BaseModel):
    id: UUID
    clip_id: UUID | None = None
    attempt: int
    layer: str
    passed: bool
    issues: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    metrics: dict[str, Any]
    evaluator: str
    created_at: str


class RunDetailResponse(RunSummaryResponse):
    profile_snapshot: dict[str, Any]
    settings_snapshot: dict[str, Any]
    events: list[RunEventResponse]
    evaluations: list[EvaluationResponse]


class RunListResponse(BaseModel):
    items: list[RunSummaryResponse]


class RunCreatedResponse(BaseModel):
    run_id: UUID


class ManualURLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str


class RunEventListResponse(BaseModel):
    items: list[RunEventResponse]


class HealthResponse(BaseModel):
    status: str
    version: str
    checks: dict[str, bool | str | None]


class AssetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    media_type: str
    category: str
    storage_key: str
    storage_path: str | None = None
    sha256: str
    mime_type: str
    size_bytes: int
    description: str
    tags: list[str]
    subjects: list[str]
    provenance: dict[str, Any]
    reusable: bool
    status: AssetStatus
    usage_count: int


class AssetListResponse(BaseModel):
    items: list[AssetResponse]


class AssetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = None
    tags: list[str] | None = None
    status: AssetStatus | None = None


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str


class MetricSnapshotResponse(BaseModel):
    offset_label: str
    scheduled_for: datetime
    captured_at: datetime
    platform: str
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    watch_time_seconds: float | None = None
    average_retention_ratio: float | None = None
    followers_delta: int | None = None
    estimated_revenue: str | None = None
    revenue_currency: str | None = None
    revenue_basis: str | None = None


class PublicationResponse(BaseModel):
    id: UUID
    platform: str
    status: str
    mode: str
    platform_post_id: str | None = None
    platform_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    approved_by: str | None = None
    published_at: datetime | None = None
    latest_metrics: MetricSnapshotResponse | None = None


class ClipPreviewResponse(BaseModel):
    media_url: str
    mime_type: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    size_bytes: int


class ClipResponse(BaseModel):
    id: UUID
    run_id: UUID
    status: str
    story_title: str | None = None
    created_at: datetime
    cost_total: str
    social_metadata: dict[str, Any] | None = None
    preview: ClipPreviewResponse
    auto_publish_due_at: datetime | None = None
    publications: list[PublicationResponse]


class ClipListResponse(BaseModel):
    items: list[ClipResponse]


class DashboardSummaryResponse(BaseModel):
    period: str
    clips_approved: int
    publications: int
    views: int
    estimated_revenue: str
    estimated_revenue_currency: str | None = None
    next_scheduled_run_at: datetime | None = None


class BudgetSummaryResponse(BaseModel):
    currency: str
    month_to_date_spend: str
    monthly_limit: str
    monthly_remaining: str
    per_clip_limit: str


class CostEntryResponse(BaseModel):
    id: UUID
    clip_id: UUID | None = None
    provider: str
    operation: str
    quantity: str
    amount: str
    currency: str
    basis: str
    created_at: datetime


class RunCostsResponse(BaseModel):
    run_id: UUID
    currency: str | None = None
    total: str
    entries: list[CostEntryResponse]


def _default_health(settings: EnvironmentSettings) -> dict[str, bool | str | None]:
    data_dir = settings.data_dir.expanduser().resolve()
    writable = data_dir.exists() and data_dir.is_dir()
    if writable:
        try:
            probe = data_dir / ".health-check"
            probe.touch(exist_ok=True)
            probe.unlink(missing_ok=True)
        except OSError:
            writable = False
    return {
        "database": False,
        "ffmpeg": shutil.which(settings.ffmpeg_path) is not None,
        "ffprobe": shutil.which(settings.ffprobe_path) is not None,
        "data_directory_writable": writable,
        "scheduler_liveness": False,
    }


_UPLOAD_FIELD = File(...)


def create_app(
    settings: EnvironmentSettings,
    health_check: HealthCheck | None = None,
    run_reader: RunReader | None = None,
    asset_repository: AssetRepositoryPort | None = None,
    lifespan: Any = None,
    storage_provider: MediaStorage | None = None,
    public_media_reader: PublicMediaReader | None = None,
    run_creator: RunCreator | None = None,
    url_validator: URLValidator | None = None,
    configuration: Any = None,
    approvals: Any = None,
    analytics: Any = None,
    catalogue: Any = None,
    budget_reader: Any = None,
    dashboard_reader: Any = None,
    clock: Clock | None = None,
    saved_news_renderer: Any = None,
    render_revision_reader: Any = None,
    continue_run: Callable[[UUID, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    stop_run: Callable[[UUID], Awaitable[dict[str, Any]]] | None = None,
) -> FastAPI:
    app = FastAPI(
        title="ClipFactory API",
        version="1.0.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    app.state.settings = settings
    current_time = clock or (lambda: datetime.now(UTC))

    async def effective_settings() -> dict[str, Any]:
        defaults = settings_snapshot(settings)
        return await _in_thread(configuration.settings, defaults) if configuration else defaults

    @app.middleware("http")
    async def require_api_token(request: Request, call_next: Callable[..., Any]) -> Any:
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            secret = settings.api_token
            is_loopback = settings.host in {"127.0.0.1", "::1", "localhost"}
            if not is_loopback:
                auth_header = request.headers.get("authorization", "")
                supplied = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                if secret is None or not hmac.compare_digest(supplied, secret.get_secret_value()):
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"code": "unauthorized", "message": "Valid API token required"}},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return await call_next(request)

    @app.middleware("http")
    async def redact_public_media_token(request: Request, call_next: Callable[..., Any]) -> Any:
        response = await call_next(request)
        if re.fullmatch("/public/media/[^/]+", request.scope.get("path", "")):
            request.scope["path"] = "/public/media/[redacted]"
        return response

    @app.head("/public/media/{token}", response_model=None, include_in_schema=False)
    async def head_public_media(token: str, request: Request) -> Response:
        return await _serve_public_media(token, request)

    @app.get("/public/media/{token}", response_model=None, operation_id="getPublicMedia")
    async def get_public_media(token: str, request: Request) -> Response:
        return await _serve_public_media(token, request)

    async def _serve_public_media(token: str, request: Request) -> Response:
        key = settings.media_url_signing_key
        if key is None or storage_provider is None or public_media_reader is None:
            return Response(status_code=404)
        clip_id = verify_media_token(token, now=datetime.now(UTC), key=key.get_secret_value().encode())
        if clip_id is None:
            return Response(status_code=404)
        storage_key = await _in_thread(public_media_reader.publishing_clip_storage_key, clip_id)
        if storage_key is None:
            return Response(status_code=404)
        try:
            path = storage_provider.local_path(storage_key)
            file_stat = await asyncio.to_thread(path.stat)
        except (OSError, ValueError):
            return Response(status_code=404)
        if not await asyncio.to_thread(path.is_file):
            return Response(status_code=404)
        return await _stream_media_file(path, file_stat.st_size, "video/mp4", request)

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    async def health() -> JSONResponse:
        checks = await health_check() if health_check else _default_health(settings)
        healthy = all(value is True for value in checks.values())
        payload = {"status": "healthy" if healthy else "degraded", "version": app.version, "checks": checks}
        return JSONResponse(status_code=200 if healthy else 503, content=payload)

    @app.get("/api/provider-status", tags=["settings"])
    async def provider_status() -> dict[str, Any]:
        return {"credentials_configured": settings.credential_status()}

    @app.get("/api/settings", tags=["settings"])
    async def get_settings() -> dict[str, Any]:
        return {
            "settings": await effective_settings(),
            "providers": [
                {"provider": provider, "credentials_configured": configured}
                for provider, configured in settings.credential_status().items()
            ],
        }

    @app.put("/api/settings/{section}", tags=["settings"])
    async def update_settings(section: str, request: dict[str, Any]) -> Any:
        if configuration is None:
            raise RuntimeError("Settings persistence is not configured")
        defaults = settings_snapshot(settings)
        try:
            validated = validate_settings_section(section, request, defaults)
        except (ValueError, ValidationError) as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "settings_validation_failed",
                        "message": "Settings validation failed",
                        "details": {
                            "errors": exc.errors(include_url=False, include_context=False)
                            if isinstance(exc, ValidationError)
                            else [str(exc)]
                        },
                    }
                },
            )
        stored = validated
        if section == "environment":
            stored = {key: value for key, value in validated.items() if value != defaults[section].get(key)}
        await _in_thread(configuration.update_settings, section, stored)
        logger.info("Settings section %s saved; stored keys: %s", section, ", ".join(sorted(stored)) or "none")
        return {"section": section, "value": validated}

    @app.get("/api/content-profile", tags=["settings"])
    async def get_content_profile() -> dict[str, Any]:
        if configuration is None:
            raise RuntimeError("Content Profile persistence is not configured")
        profile = await _in_thread(configuration.active_profile)
        return profile.model_dump(mode="json")

    @app.put("/api/content-profile", tags=["settings"])
    async def put_content_profile(request: dict[str, Any]) -> Any:
        if configuration is None:
            raise RuntimeError("Content Profile persistence is not configured")
        try:
            profile = ContentProfile.model_validate(request)
        except ValidationError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "profile_validation_failed",
                        "message": "Content Profile validation failed",
                        "details": {"errors": exc.errors(include_url=False, include_context=False)},
                    }
                },
            )
        saved = await _in_thread(configuration.replace_active_profile, profile)
        return saved.model_dump(mode="json")

    @app.post("/api/clips/{clip_id}/approval", tags=["publishing"])
    async def decide_approval(clip_id: UUID, request: ApprovalRequest) -> Any:
        if approvals is None:
            raise RuntimeError("Approval service is not configured")
        if request.decision not in {"approve", "reject"}:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_approval", "message": "decision must be approve or reject"}},
            )
        try:
            return await approvals.decide(clip_id, request.decision)
        except LookupError:
            return JSONResponse(
                status_code=404, content={"error": {"code": "clip_not_found", "message": "Clip was not found"}}
            )

    def require_catalogue() -> Any:
        if catalogue is None:
            raise RuntimeError("Clip catalogue is not configured")
        return catalogue

    @app.get("/api/clips", response_model=ClipListResponse, tags=["publishing"])
    async def list_clips(limit: int = Query(default=100, ge=1, le=100)) -> dict[str, Any]:
        return {"items": await _in_thread(require_catalogue().clips, limit=limit)}

    @app.get("/api/clips/pending-approval", response_model=ClipListResponse, tags=["publishing"])
    async def pending_approval_clips(limit: int = Query(default=100, ge=1, le=100)) -> dict[str, Any]:
        return {"items": await _in_thread(require_catalogue().clips, pending_approval=True, limit=limit)}

    @app.get("/api/clips/{clip_id}", response_model=ClipResponse, tags=["publishing"])
    async def get_clip(clip_id: UUID) -> Any:
        clip = await _in_thread(require_catalogue().clip, clip_id)
        if clip is None:
            return JSONResponse(
                status_code=404, content={"error": {"code": "clip_not_found", "message": "Clip was not found"}}
            )
        return clip

    @app.get("/api/clips/{clip_id}/media", response_model=None, tags=["publishing"])
    async def get_clip_media(clip_id: UUID, request: Request) -> Response:
        not_found = {"error": {"code": "clip_not_found", "message": "Clip media was not found"}}
        if storage_provider is None:
            return JSONResponse(status_code=404, content=not_found)
        storage_key = await _in_thread(require_catalogue().clip_storage_key, clip_id)
        if storage_key is None:
            return JSONResponse(status_code=404, content=not_found)
        try:
            path = storage_provider.local_path(storage_key)
            file_stat = await asyncio.to_thread(path.stat)
        except (OSError, ValueError):
            return JSONResponse(status_code=404, content=not_found)
        if not await asyncio.to_thread(path.is_file):
            return JSONResponse(status_code=404, content=not_found)
        return await _stream_media_file(path, file_stat.st_size, "video/mp4", request)

    @app.post("/api/render-revisions", status_code=201, tags=["quality"], response_model=RenderRevisionResponse)
    async def render_revision(request: SavedNewsRenderRequest) -> Any:
        if saved_news_renderer is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "render_unavailable", "message": "Saved rendering is not configured"}},
            )
        try:
            return await saved_news_renderer.execute(request)
        except (ValueError, LookupError) as exc:
            return JSONResponse(
                status_code=422, content={"error": {"code": "invalid_render_recipe", "message": str(exc)}}
            )

    @app.get("/api/render-revisions/{revision_id}", tags=["quality"], response_model=RenderRevisionResponse)
    async def get_render_revision(revision_id: UUID) -> Any:
        value = await _in_thread(render_revision_reader.get_revision, revision_id) if render_revision_reader else None
        if value is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "revision_not_found", "message": "Render revision was not found"}},
            )
        return value

    @app.get("/api/render-revisions/{revision_id}/media", response_model=None, tags=["quality"])
    async def get_render_revision_media(revision_id: UUID, request: Request) -> Response:
        value = await _in_thread(render_revision_reader.get_revision, revision_id) if render_revision_reader else None
        if value is None or storage_provider is None:
            return Response(status_code=404)
        try:
            path = storage_provider.local_path(value["storage_key"])
            file_stat = await asyncio.to_thread(path.stat)
        except (KeyError, ValueError, OSError):
            return Response(status_code=404)
        return await _stream_media_file(path, file_stat.st_size, "video/mp4", request)

    @app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse, tags=["dashboard"])
    async def dashboard_summary() -> dict[str, Any]:
        if dashboard_reader is None:
            raise RuntimeError("Dashboard persistence is not configured")
        summary = await _in_thread(dashboard_reader.dashboard_summary, current_time() - timedelta(days=7))
        return {"period": "7d", **summary}

    @app.get("/api/budget", response_model=BudgetSummaryResponse, tags=["budget"])
    async def budget_summary() -> Any:
        if budget_reader is None:
            raise RuntimeError("Budget persistence is not configured")
        defaults = settings_snapshot(settings)
        effective = await _in_thread(configuration.settings, defaults) if configuration else defaults
        return await _in_thread(budget_reader.budget_summary, current_time(), effective["budget"])

    @app.get("/api/runs/{run_id}/costs", response_model=RunCostsResponse, tags=["budget"])
    async def run_costs(run_id: UUID) -> Any:
        if budget_reader is None:
            raise RuntimeError("Budget persistence is not configured")
        result = await _in_thread(budget_reader.run_costs, run_id)
        if result is None:
            return JSONResponse(
                status_code=404, content={"error": {"code": "run_not_found", "message": "Run was not found"}}
            )
        return result

    @app.get("/api/analytics/summary", tags=["analytics"])
    async def analytics_summary(period: str = "7d") -> Any:
        if analytics is None:
            raise RuntimeError("Analytics persistence is not configured")
        if period not in {"7d", "30d", "all"}:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_period", "message": "period must be 7d, 30d or all"}},
            )
        days = None if period == "all" else int(period[:-1])
        since = None if days is None else datetime.now(UTC) - timedelta(days=days)
        return {"period": period, "items": await _in_thread(analytics.analytics_summary, since)}

    @app.get("/api/analytics/publications/{publication_id}/snapshots", tags=["analytics"])
    async def publication_snapshots(publication_id: UUID) -> dict[str, Any]:
        if analytics is None:
            raise RuntimeError("Analytics persistence is not configured")
        return {"items": await _in_thread(analytics.snapshots, publication_id)}

    def require_run_reader() -> RunReader:
        if run_reader is None:
            raise RuntimeError("Run persistence is not configured")
        return run_reader

    def require_run_creator() -> RunCreator:
        if run_creator is None:
            raise RuntimeError("Run creation is not configured")
        return run_creator

    async def create_run(trigger: RunTrigger, manual_url: str | None = None) -> Response | dict[str, str]:
        try:
            created = await _in_thread(
                require_run_creator().create,
                trigger,
                manual_url=manual_url,
                settings_snapshot=await effective_settings(),
            )
        except ActiveRunConflict as exc:
            active_run_id = str(exc.active_run_id) if exc.active_run_id else None
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "active_run_conflict",
                        "message": "A Run is already queued or running",
                        "details": {"active_run_id": active_run_id},
                    }
                },
            )
        except LLMBudgetExhausted as exc:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "llm_budget_exhausted", "message": str(exc)}},
            )
        return {"run_id": created["run_id"]}

    @app.post("/api/runs", response_model=RunCreatedResponse, status_code=202, tags=["runs"])
    async def start_run_now() -> Response | dict[str, str]:
        return await create_run(RunTrigger.RUN_NOW)

    @app.post("/api/runs/manual-url", response_model=RunCreatedResponse, status_code=202, tags=["runs"])
    async def start_manual_url(request: ManualURLRequest) -> Response | dict[str, str]:
        validate = url_validator or SafeHTTPClient().validate_url
        try:
            await validate(request.url)
        except (UnsafeURL, ValueError) as exc:
            return JSONResponse(status_code=422, content={"error": {"code": "invalid_manual_url", "message": str(exc)}})
        return await create_run(RunTrigger.MANUAL_URL, request.url)

    @app.post("/api/runs/{run_id}/continue", response_model=RunCreatedResponse, status_code=202, tags=["runs"])
    async def continue_failed_run(run_id: UUID) -> Any:
        if continue_run is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "continuation_unavailable",
                        "message": "Run continuation is not configured",
                    }
                },
            )
        try:
            result = await continue_run(run_id, await effective_settings())
            return {"run_id": result["run_id"]}
        except RunNotFound:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "run_not_found",
                        "message": "Run was not found",
                    }
                },
            )
        except ActiveRunConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "active_run_conflict",
                        "message": str(exc),
                        "details": {"active_run_id": str(exc.active_run_id) if exc.active_run_id else None},
                    }
                },
            )
        except RunContinuationConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "run_continuation_conflict",
                        "message": str(exc),
                    }
                },
            )

    @app.post("/api/runs/{run_id}/stop", response_model=RunCreatedResponse, status_code=202, tags=["runs"])
    async def stop_active_run(run_id: UUID) -> Any:
        if stop_run is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "stop_unavailable",
                        "message": "Run stopping is not configured",
                    }
                },
            )
        try:
            result = await stop_run(run_id)
            return {"run_id": result["run_id"]}
        except RunNotFound:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "run_not_found",
                        "message": "Run was not found",
                    }
                },
            )
        except RunContinuationConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "run_stop_conflict",
                        "message": str(exc),
                    }
                },
            )

    @app.get("/api/runs", response_model=RunListResponse, tags=["runs"])
    async def list_runs(
        limit: int = Query(default=50, ge=1, le=100), status: str | None = None, trigger: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        rows = await _in_thread(require_run_reader().list, limit=limit, status=status, trigger=trigger)
        return {"items": rows}

    @app.get("/api/runs/active", response_model=RunSummaryResponse | None, tags=["runs"])
    async def get_active_run() -> Response | dict[str, Any]:
        run = await _in_thread(require_run_reader().active)
        return Response(status_code=204) if run is None else run

    @app.get("/api/runs/{run_id}", response_model=RunDetailResponse, tags=["runs"])
    async def get_run(run_id: UUID) -> Any:
        try:
            return await _in_thread(require_run_reader().get, run_id)
        except RunNotFound:
            return JSONResponse(
                status_code=404, content={"error": {"code": "run_not_found", "message": "Run was not found"}}
            )

    @app.get("/api/runs/{run_id}/events", response_model=RunEventListResponse, tags=["runs"])
    async def get_run_events(run_id: UUID, after_sequence: int = Query(default=0, ge=0)) -> Any:
        try:
            events = await _in_thread(require_run_reader().events, run_id, after_sequence=after_sequence)
        except RunNotFound:
            return JSONResponse(
                status_code=404, content={"error": {"code": "run_not_found", "message": "Run was not found"}}
            )
        return {"items": events}

    @app.get("/api/runs/{run_id}/events/stream", response_model=None, tags=["runs"])
    async def stream_run_events(run_id: UUID, request: Request) -> Any:
        reader = require_run_reader()
        try:
            await _in_thread(reader.get, run_id)
        except RunNotFound:
            return JSONResponse(
                status_code=404, content={"error": {"code": "run_not_found", "message": "Run was not found"}}
            )
        last_event_id = request.headers.get("last-event-id", "0")
        try:
            after_sequence = max(0, int(last_event_id))
        except ValueError:
            after_sequence = 0

        async def event_stream() -> AsyncIterator[str]:
            nonlocal after_sequence
            keep_alive_at = time.monotonic() + 15
            while not await request.is_disconnected():
                events = await _in_thread(reader.events, run_id, after_sequence=after_sequence)
                for event in events:
                    after_sequence = event["sequence"]
                    yield "".join(
                        [
                            "id: ",
                            f"{event['sequence']}",
                            "\nevent: ",
                            f"{event['type']}",
                            "\ndata: ",
                            f"{json.dumps(event, separators=(',', ':'))}",
                            "\n\n",
                        ]
                    )
                    if event["type"] in {"run_completed", "run_failed"} and not any(
                        item["type"] == "run_resumed" and item["sequence"] > event["sequence"] for item in events
                    ):
                        return
                if time.monotonic() >= keep_alive_at:
                    yield ": keep-alive\n\n"
                    keep_alive_at = time.monotonic() + 15
                await asyncio.sleep(0.25)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/assets", response_model=AssetListResponse, tags=["assets"])
    async def list_assets(
        status: AssetStatus | None = AssetStatus.ACTIVE, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict[str, list[dict[str, Any]]]:
        if asset_repository is None:
            raise RuntimeError("Asset repository is not configured")
        assets = await _in_thread(asset_repository.list, status=status, limit=limit)
        return {"items": [asset_response(asset) for asset in assets]}

    def asset_response(asset: Asset) -> dict[str, Any]:
        return {
            **asset.model_dump(mode="json"),
            "storage_path": str(storage_provider.local_path(asset.storage_key)) if storage_provider else None,
        }

    @app.post("/api/assets/import", response_model=AssetResponse, status_code=201, tags=["assets"])
    async def import_asset(
        file: UploadFile = _UPLOAD_FIELD,
        category: str = Form(...),
        license: str = Form(...),
        description: str = Form(""),
        tags: str = Form(""),
        subjects: str = Form(""),
        author: str | None = Form(None),
        source_url: str | None = Form(None),
        license_url: str | None = Form(None),
        attribution_required: bool = Form(False),
        attribution_text: str | None = Form(None),
    ) -> Any:
        if asset_repository is None or storage_provider is None:
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "asset_import_unavailable", "message": "Asset storage is not configured"}},
            )
        temporary_path: Path | None = None
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(dir=settings.data_dir, prefix="asset-import-", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := (await file.read(1024 * 1024)):
                    temporary.write(chunk)
            result = await import_asset_file(
                temporary_path,
                category=category,
                provenance=ImportProvenance(
                    license=license,
                    author=author,
                    source_url=source_url,
                    license_url=license_url,
                    attribution_required=attribution_required,
                    attribution_text=attribution_text,
                ),
                storage=storage_provider,
                assets=asset_repository,
                now=datetime.now(UTC),
                description=description,
                tags=tuple(value for value in tags.split(",")),
                subjects=tuple(value for value in subjects.split(",")),
            )
        except AssetImportError as exc:
            return JSONResponse(status_code=422, content={"error": {"code": exc.code, "message": str(exc)}})
        finally:
            await file.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return asset_response(result.asset)

    @app.get("/api/assets/{asset_id}", response_model=AssetResponse, tags=["assets"])
    async def get_asset(asset_id: UUID) -> Any:
        if asset_repository is None:
            raise RuntimeError("Asset repository is not configured")
        asset = await _in_thread(asset_repository.get, asset_id)
        if asset is None:
            return JSONResponse(
                status_code=404, content={"error": {"code": "asset_not_found", "message": "Asset was not found"}}
            )
        return asset_response(asset)

    @app.patch("/api/assets/{asset_id}", response_model=AssetResponse, tags=["assets"])
    async def update_asset(asset_id: UUID, changes: AssetPatchRequest) -> Any:
        if asset_repository is None:
            raise RuntimeError("Asset repository is not configured")
        asset = await _in_thread(asset_repository.update, asset_id, **changes.model_dump(exclude_unset=True))
        if asset is None:
            return JSONResponse(
                status_code=404, content={"error": {"code": "asset_not_found", "message": "Asset was not found"}}
            )
        return asset_response(asset)

    @app.get("/api/assets/{asset_id}/file", response_model=None, tags=["assets"])
    async def get_asset_file(asset_id: UUID, request: Request) -> Response:
        not_found = {"error": {"code": "asset_not_found", "message": "Asset file was not found"}}
        if asset_repository is None or storage_provider is None:
            return JSONResponse(status_code=404, content=not_found)
        asset = await _in_thread(asset_repository.get, asset_id)
        if asset is None:
            return JSONResponse(status_code=404, content=not_found)
        try:
            path = storage_provider.local_path(asset.storage_key)
            file_stat = await asyncio.to_thread(path.stat)
        except (OSError, ValueError):
            return JSONResponse(status_code=404, content=not_found)
        if not await asyncio.to_thread(path.is_file):
            return JSONResponse(status_code=404, content=not_found)
        return await _stream_media_file(path, file_stat.st_size, asset.mime_type, request)

    return app


async def _in_thread(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(function, *args, **kwargs)


async def _stream_media_file(path: Path, file_size: int, media_type: str, request: Request) -> Response:
    byte_range = request.headers.get("range")
    start, end = (0, file_size - 1)
    status_code = 200
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    if byte_range is not None:
        match = re.fullmatch("bytes=(\\d*)-(\\d*)", byte_range.strip())
        if match is None or file_size == 0:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        first, last = match.groups()
        if not first:
            suffix_length = int(last) if last else 0
            if suffix_length <= 0:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
            start = max(0, file_size - suffix_length)
        else:
            start = int(first)
            end = int(last) if last else file_size - 1
        if start >= file_size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
        end = min(end, file_size - 1)
        status_code = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(end - start + 1)
    if request.method == "HEAD":
        return Response(status_code=status_code, media_type=media_type, headers=headers)
    return StreamingResponse(
        _read_file_range(path, start, end - start + 1), status_code=status_code, media_type=media_type, headers=headers
    )


def _read_file_range(path: Path, start: int, length: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as media_file:
        media_file.seek(start)
        while remaining:
            chunk = media_file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def settings_snapshot(settings: EnvironmentSettings) -> dict[str, Any]:
    return {
        "app_env": settings.app_env,
        "scheduler_enabled": settings.scheduler_enabled,
        "llm_provider": settings.llm_provider,
        "news_sources": settings.news_sources,
        "media_sources": settings.media_sources,
        "image_providers": settings.image_providers,
        "video_providers": settings.video_providers,
        "tts_provider": settings.tts_provider,
        "transcription_provider": settings.transcription_provider,
        "publishers": settings.publishers,
        "environment": runtime_environment_defaults(settings),
        "providers": ProviderCallSettings().model_dump(mode="json"),
        "workflow": {"max_revision_retries": 3, "resume_interrupted_runs": True, "stage_timeout_seconds": 1800},
        "scheduler": {"poll_interval_seconds": 30, "missed_run_grace_minutes": 60},
        "llm": {
            "max_input_chars": 60000,
            "requests_per_minute": 20,
            "requests_per_day": 50,
            "daily_reset_timezone": "UTC",
            "target_requests_per_clip": 5,
            "max_requests_per_run": 8,
            "min_daily_requests_to_start_run": 5,
            "min_daily_requests_to_start_manual_run": 4,
            "circuit_failure_threshold": 3,
            "circuit_open_seconds": 300,
        },
        "research": {
            "max_article_bytes": 5000000,
            "feeds": [
                ["BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml"],
                ["The Guardian - World", "https://www.theguardian.com/world/rss"],
                ["Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"],
                ["NPR - World", "https://feeds.npr.org/1004/rss.xml"],
                ["Deutsche Welle - World", "https://rss.dw.com/rdf/rss-en-world"],
                ["France 24", "https://www.france24.com/en/rss"],
                ["The New York Times - World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"],
                ["CNN - World", "http://rss.cnn.com/rss/edition_world.rss"],
            ],
            "publisher_quality": {},
        },
        "script": {"min_segments": 4, "max_segments": 8, "hook_max_seconds": 5.0},
        "visual": {"min_segment_seconds": 1.5, "max_segment_seconds": 8.0},
        "assets": {
            "reuse_min_match_score": 0.6,
            "reuse_cooldown_days": 3,
            "min_image_short_side_px": 720,
            "min_video_height_px": 720,
            "max_image_bytes": 20000000,
            "max_video_bytes": 300000000,
            "max_audio_bytes": 50000000,
            "candidates_per_search": 10,
        },
        "captions": {
            "font_file": "NotoSans-Bold.ttf",
            "font_size_px": 56,
            "max_lines": 2,
            "max_cue_seconds": 3.0,
            "horizontal_margin_pct": 6,
            "max_text_width_pct": 88,
            "bottom_margin_pct": 10,
        },
        "composition": {
            "video_codec": "libx264",
            "crf": 23,
            "preset": "medium",
            "pixel_format": "yuv420p",
            "audio_codec": "aac",
            "audio_bitrate": "128k",
            "audio_sample_rate": 48000,
            "lead_in_seconds": 0.3,
            "tail_seconds": 1.0,
            "narration_loudness_lufs": -14,
            "transition_seconds": 0.4,
        },
        "evaluation": {
            "semantic_enabled": True,
            "visual_enabled": True,
            "visual_frame_count": 5,
            "visual_frame_width_px": 360,
            "max_narration_wer": 0.15,
            "max_segment_duration_drift_seconds": 2.0,
        },
        "publishing": {
            "mode": "dry_run",
            "approval_required": True,
            "auto_publish_enabled": False,
            "auto_publish_after_minutes": 10,
            "public_media_url_ttl_minutes": 60,
        },
        "budget": {
            "currency": "EUR",
            "max_cost_per_clip": 1.0,
            "max_cost_per_month": 30.0,
            "usd_to_currency_rate": 0.92,
            "price_table": {
                "llm_usd_per_1k_tokens": 0.002,
                "google_tts": 30.0,
                "higgsfield_image": 0.05,
                "higgsfield_video": 0.1,
                "comfyui": 0,
                "wan_local": 0,
                "whisper_local": 0,
                "pexels": 0,
                "pixabay": 0,
                "unsplash": 0,
                "wikimedia_commons": 0,
            },
        },
        "analytics": {
            "snapshot_offsets": ["1h", "6h", "24h", "48h", "7d", "30d"],
            "rpm_by_platform": {"youtube": 0.05, "instagram": 0.01, "tiktok": 0.4, "facebook": 0.02},
            "currency": "USD",
        },
    }
