"""Controlled local filesystem access for source, intermediate, and output media."""

import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.core.config import Settings
from app.core.exceptions import InvalidInputError

SUPPORTED_VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".m4v",
        ".mpeg",
        ".mpg",
    }
)
_SAFE_JOB_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SAFE_SOURCE_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_CHUNK_SIZE = 1024 * 1024


class FileManager:
    """Owns all media paths and blocks traversal outside configured directories."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def initialize(self) -> None:
        for directory in (
            self.settings.output_dir,
            self.settings.temp_dir,
            self.settings.download_dir,
            self.settings.data_dir / "jobs",
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def validate_upload_metadata(self, filename: str | None, content_type: str | None) -> str:
        safe_name = self.sanitize_filename(filename or "")
        extension = Path(safe_name).suffix.lower()
        if extension not in SUPPORTED_VIDEO_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
            raise InvalidInputError(f"Unsupported video format. Supported formats: {supported}")
        if content_type and not (
            content_type.startswith("video/") or content_type == "application/octet-stream"
        ):
            raise InvalidInputError("The uploaded file does not have a video MIME type")
        return safe_name

    def sanitize_filename(self, filename: str) -> str:
        base_name = Path(filename).name.strip()
        if not base_name or base_name in {".", ".."}:
            raise InvalidInputError("A video filename is required")
        safe_name = _UNSAFE_FILENAME.sub("_", base_name).strip("._")
        if not safe_name:
            raise InvalidInputError("The video filename contains no usable characters")
        return safe_name[:180]

    def workspace_dir(self, job_id: str) -> Path:
        return self._job_dir(self.settings.temp_dir, job_id)

    def download_dir(self, job_id: str) -> Path:
        return self._job_dir(self.settings.download_dir, job_id)

    def output_dir(self, job_id: str) -> Path:
        return self._job_dir(self.settings.output_dir, job_id)

    def job_data_dir(self, job_id: str) -> Path:
        return self._job_dir(self.settings.data_dir / "jobs", job_id)

    def upload_source_path(self, job_id: str, filename: str) -> Path:
        return self.workspace_dir(job_id) / f"source{Path(filename).suffix.lower()}"

    def reel_upload_source_path(
        self,
        job_id: str,
        source_id: str,
        filename: str,
    ) -> Path:
        self._validate_source_id(source_id)
        filename_with_extension = f"{source_id}{Path(filename).suffix.lower()}"
        return self.workspace_dir(job_id) / "sources" / filename_with_extension

    def downloaded_source_template(self, job_id: str) -> Path:
        return self.download_dir(job_id) / "source.%(ext)s"

    def reel_downloaded_source_template(self, job_id: str, source_id: str) -> Path:
        self._validate_source_id(source_id)
        return self.download_dir(job_id) / source_id / "source.%(ext)s"

    def reel_source_audio_path(self, job_id: str, source_id: str) -> Path:
        self._validate_source_id(source_id)
        return self.workspace_dir(job_id) / "audio" / f"{source_id}.wav"

    def reel_narration_path(self, job_id: str) -> Path:
        return self.workspace_dir(job_id) / "narration.wav"

    def reel_path(self, job_id: str) -> Path:
        return self.output_dir(job_id) / "reel.mp4"

    def find_upload_source(self, job_id: str) -> Path:
        sources = sorted(self.workspace_dir(job_id).glob("source.*"))
        if len(sources) != 1:
            raise InvalidInputError("The uploaded source video is unavailable")
        return sources[0]

    def find_downloaded_source(self, job_id: str) -> Path:
        sources = sorted(self.download_dir(job_id).glob("source.*"))
        if len(sources) != 1:
            raise InvalidInputError("The downloaded source video is unavailable")
        return sources[0]

    async def save_upload(self, upload: UploadFile, destination: Path) -> int:
        """Stream an upload into its managed job directory with a configurable size cap."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        bytes_written = 0
        try:
            with destination.open("wb") as output_file:
                while chunk := await upload.read(_CHUNK_SIZE):
                    bytes_written += len(chunk)
                    if bytes_written > self.settings.max_upload_size_bytes:
                        raise InvalidInputError(
                            "The uploaded video exceeds the configured size limit"
                        )
                    output_file.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise InvalidInputError("The uploaded video is empty")
        return bytes_written

    def write_transcript(self, job_id: str, transcript: list[Mapping[str, Any]]) -> Path:
        destination = self.job_data_dir(job_id) / "transcript.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
        return destination

    def write_framing_debug(self, job_id: str, framing: list[Mapping[str, Any]]) -> Path:
        destination = self.job_data_dir(job_id) / "framing.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(framing, indent=2), encoding="utf-8")
        return destination

    def write_reel_sources(self, job_id: str, sources: list[Mapping[str, Any]]) -> Path:
        return self._write_job_json(job_id, "reel_sources.json", sources)

    def write_reel_script(self, job_id: str, script: Mapping[str, Any]) -> Path:
        return self._write_job_json(job_id, "reel_script.json", script)

    def write_narration_timing(self, job_id: str, narration: Mapping[str, Any]) -> Path:
        return self._write_job_json(job_id, "narration.json", narration)

    def write_broll_timeline(self, job_id: str, timeline: list[Mapping[str, Any]]) -> Path:
        return self._write_job_json(job_id, "broll_timeline.json", timeline)

    def clip_path(self, job_id: str, filename: str) -> Path:
        if Path(filename).name != filename or Path(filename).suffix.lower() != ".mp4":
            raise InvalidInputError("Invalid clip filename")
        directory = self.output_dir(job_id)
        candidate = (directory / filename).resolve()
        if not candidate.is_relative_to(directory.resolve()):
            raise InvalidInputError("Invalid clip path")
        return candidate

    def cleanup_successful_job(self, job_id: str) -> None:
        shutil.rmtree(self.workspace_dir(job_id), ignore_errors=True)
        shutil.rmtree(self.download_dir(job_id), ignore_errors=True)

    def _job_dir(self, root: Path, job_id: str) -> Path:
        if not _SAFE_JOB_ID.fullmatch(job_id):
            raise InvalidInputError("Invalid job identifier")
        return root / job_id

    def _validate_source_id(self, source_id: str) -> None:
        if not _SAFE_SOURCE_ID.fullmatch(source_id):
            raise InvalidInputError("Invalid source identifier")

    def _write_job_json(self, job_id: str, filename: str, payload: object) -> Path:
        destination = self.job_data_dir(job_id) / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination
