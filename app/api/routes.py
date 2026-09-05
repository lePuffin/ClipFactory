"""HTTP endpoints for job submission, status polling, preview, and downloads."""

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import InvalidInputError, JobNotFoundError
from app.models.job import JobRecord
from app.models.source import ReelSourceOrigin, ReelSourceType, Source
from app.services.article_ingestion import ArticleIngestionService, validate_article_url
from app.services.files import FileManager
from app.services.youtube import validate_youtube_url

router = APIRouter(prefix="/api", tags=["jobs"])


class YoutubeJobRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    clip_count: int = Field(default=5, ge=1, le=10)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            return validate_youtube_url(value)
        except InvalidInputError as error:
            raise ValueError(str(error)) from error


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    container = request.app.state.container
    return {
        "status": "ok",
        "ffmpeg_available": container.ffmpeg.is_available,
        "llm_configured": container.settings.llm_is_configured,
        "whisper_model": container.settings.whisper_model,
    }


@router.get("/jobs", response_model=list[JobRecord])
def list_jobs(request: Request) -> list[JobRecord]:
    return request.app.state.container.jobs.list()


@router.get("/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str, request: Request) -> JobRecord:
    return request.app.state.container.jobs.get(job_id)


@router.post("/jobs/upload", response_model=JobRecord)
async def create_upload_job(
    request: Request,
    file: Annotated[UploadFile, File(description="A local video file")],
    clip_count: Annotated[int, Form(ge=1, le=10)] = 5,
) -> JobRecord:
    container = request.app.state.container
    safe_name = container.files.validate_upload_metadata(file.filename, file.content_type)
    job_id = uuid4().hex
    destination = container.files.upload_source_path(job_id, safe_name)
    try:
        await container.files.save_upload(file, destination)
        job = container.jobs.create(
            JobRecord(
                id=job_id,
                source_type="upload",
                source_name=safe_name,
                requested_clip_count=clip_count,
            )
        )
        container.runner.submit(job.id)
        return job
    except Exception:
        container.files.cleanup_successful_job(job_id)
        raise
    finally:
        await file.close()


@router.post("/jobs/reel", response_model=JobRecord)
async def create_reel_job(
    request: Request,
    video_files: Annotated[list[UploadFile] | None, File(description="Local source videos")] = None,
    urls: Annotated[list[str] | None, Form()] = None,
    article_texts: Annotated[list[str] | None, Form()] = None,
    youtube_urls: Annotated[list[str] | None, Form()] = None,
    article_urls: Annotated[list[str] | None, Form()] = None,
) -> JobRecord:
    """Normalize mixed local/video/article sources into one managed reel job."""
    container = request.app.state.container
    uploads = video_files or []
    job_id = uuid4().hex
    try:
        sources = await _build_reel_sources(
            container.files,
            job_id,
            uploads,
            urls or [],
            article_texts or [],
            youtube_urls or [],
            article_urls or [],
        )
        if not sources:
            raise InvalidInputError("Add at least one video or article source to create a reel")
        job = container.jobs.create(
            JobRecord(
                id=job_id,
                job_type="reel",
                source_type="reel",
                source_name=(
                    f"News reel from {len(sources)} source{'s' if len(sources) != 1 else ''}"
                ),
                sources=sources,
            )
        )
        container.runner.submit(job.id)
        return job
    except Exception:
        container.files.cleanup_successful_job(job_id)
        raise
    finally:
        for upload in uploads:
            await upload.close()


@router.post("/jobs/youtube", response_model=JobRecord)
def create_youtube_job(payload: YoutubeJobRequest, request: Request) -> JobRecord:
    container = request.app.state.container
    job = container.jobs.create(
        JobRecord(
            id=uuid4().hex,
            source_type="youtube",
            source_name=payload.url,
            requested_clip_count=payload.clip_count,
        )
    )
    container.runner.submit(job.id)
    return job


async def _build_reel_sources(
    files: FileManager,
    job_id: str,
    video_files: Sequence[UploadFile],
    urls: Sequence[str],
    article_texts: Sequence[str],
    youtube_urls: Sequence[str],
    article_urls: Sequence[str],
) -> list[Source]:
    values = {
        "urls": _provided_values(urls),
        "youtube_urls": _provided_values(youtube_urls),
        "article_texts": _provided_values(article_texts),
        "article_urls": _provided_values(article_urls),
    }

    sources: list[Source] = []
    video_index = 1
    article_index = 1
    for upload in video_files:
        safe_name = files.validate_upload_metadata(upload.filename, upload.content_type)
        source_id = f"video-{video_index:02d}"
        await files.save_upload(
            upload,
            files.reel_upload_source_path(job_id, source_id, safe_name),
        )
        sources.append(
            Source(
                id=source_id,
                type=ReelSourceType.VIDEO,
                origin=ReelSourceOrigin.UPLOAD,
                name=safe_name,
                reference=safe_name,
            )
        )
        video_index += 1
    for url in values["urls"]:
        source, video_index, article_index = _source_from_url(
            url,
            video_index,
            article_index,
        )
        sources.append(source)
    for url in values["youtube_urls"]:
        source_id = f"video-{video_index:02d}"
        normalized_url = validate_youtube_url(url)
        sources.append(
            Source(
                id=source_id,
                type=ReelSourceType.VIDEO,
                origin=ReelSourceOrigin.YOUTUBE,
                name=f"YouTube video {video_index:02d}",
                reference=normalized_url,
            )
        )
        video_index += 1
    article_ingestion = ArticleIngestionService()
    for text in values["article_texts"]:
        source_id = f"article-{article_index:02d}"
        source = Source(
            id=source_id,
            type=ReelSourceType.ARTICLE,
            origin=ReelSourceOrigin.ARTICLE_TEXT,
            name=f"Pasted article {article_index:02d}",
            reference=text,
        )
        article_ingestion.ingest(source)
        sources.append(source)
        article_index += 1
    for url in values["article_urls"]:
        source_id = f"article-{article_index:02d}"
        normalized_url = validate_article_url(url)
        hostname = urlparse(normalized_url).hostname or "article"
        sources.append(
            Source(
                id=source_id,
                type=ReelSourceType.ARTICLE,
                origin=ReelSourceOrigin.ARTICLE_URL,
                name=f"Article from {hostname}"[:180],
                reference=normalized_url,
            )
        )
        article_index += 1
    return sources


def _source_from_url(
    value: str,
    video_index: int,
    article_index: int,
) -> tuple[Source, int, int]:
    try:
        normalized_url = validate_youtube_url(value)
    except InvalidInputError:
        normalized_url = validate_article_url(value)
        hostname = urlparse(normalized_url).hostname or "article"
        return (
            Source(
                id=f"article-{article_index:02d}",
                type=ReelSourceType.ARTICLE,
                origin=ReelSourceOrigin.ARTICLE_URL,
                name=f"Article from {hostname}"[:180],
                reference=normalized_url,
            ),
            video_index,
            article_index + 1,
        )
    return (
        Source(
            id=f"video-{video_index:02d}",
            type=ReelSourceType.VIDEO,
            origin=ReelSourceOrigin.YOUTUBE,
            name=f"Video from {urlparse(normalized_url).hostname}"[:180],
            reference=normalized_url,
        ),
        video_index + 1,
        article_index,
    )


def _provided_values(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(value.strip() for value in values if value.strip())


@router.get("/jobs/{job_id}/clips/{filename}")
def serve_clip(
    job_id: str,
    filename: str,
    request: Request,
    download: bool = Query(default=False),
) -> FileResponse:
    container = request.app.state.container
    container.jobs.get(job_id)
    clip_path = container.files.clip_path(job_id, filename)
    if not clip_path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        filename=Path(filename).name,
        content_disposition_type=disposition,
    )


@router.get("/jobs/{job_id}/reel")
def serve_reel(
    job_id: str,
    request: Request,
    download: bool = Query(default=False),
) -> FileResponse:
    """Serve the single managed output created by a completed reel job."""
    container = request.app.state.container
    job = container.jobs.get(job_id)
    if not job.is_reel():
        raise HTTPException(status_code=404, detail="Reel not found")
    reel_path = container.files.reel_path(job_id)
    if not reel_path.is_file():
        raise HTTPException(status_code=404, detail="Reel not found")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        reel_path,
        media_type="video/mp4",
        filename="reel.mp4",
        content_disposition_type=disposition,
    )


def register_error_handlers(app: object) -> None:
    """Kept in this module to make expected local failures consistent across endpoints."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    if not isinstance(app, FastAPI):
        return

    @app.exception_handler(InvalidInputError)
    async def invalid_input_handler(_: Request, error: InvalidInputError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(JobNotFoundError)
    async def job_not_found_handler(_: Request, error: JobNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})
