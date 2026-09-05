"""Small filesystem-backed persistence for local processing jobs."""

import logging
import threading
from pathlib import Path

from app.core.exceptions import JobNotFoundError
from app.models.job import JobRecord

logger = logging.getLogger(__name__)


class JobStore:
    """Persists JSON job records atomically without adding a database dependency."""

    def __init__(self, data_dir: Path) -> None:
        self._directory = data_dir / "jobs"
        self._directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, job: JobRecord) -> JobRecord:
        with self._lock:
            path = self._path(job.id)
            if path.exists():
                raise ValueError(f"Job already exists: {job.id}")
            self._write(job)
        return job

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            path = self._path(job_id)
            if not path.is_file():
                raise JobNotFoundError(f"Job not found: {job_id}")
            return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def update(self, job_id: str, **changes: object) -> JobRecord:
        with self._lock:
            current = self.get(job_id)
            updated = current.model_copy(update=changes)
            self._write(updated)
            return updated

    def list(self, limit: int = 50) -> list[JobRecord]:
        with self._lock:
            jobs: list[JobRecord] = []
            for path in self._directory.glob("*.json"):
                try:
                    jobs.append(JobRecord.model_validate_json(path.read_text(encoding="utf-8")))
                except Exception:
                    logger.warning("Skipping unreadable job record: %s", path)
            jobs.sort(key=lambda job: job.created_at, reverse=True)
            return jobs[:limit]

    def _path(self, job_id: str) -> Path:
        if not job_id or Path(job_id).name != job_id:
            raise JobNotFoundError("Invalid job identifier")
        return self._directory / f"{job_id}.json"

    def _write(self, job: JobRecord) -> None:
        destination = self._path(job.id)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(destination)
