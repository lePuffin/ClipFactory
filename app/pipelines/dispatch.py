"""Routes persisted job variants to the appropriate local processing pipeline."""

from typing import Protocol

from app.models.job import JobRecord
from app.services.jobs import JobStore


class JobProcessor(Protocol):
    """Common execution contract consumed by the single local worker."""

    def run(self, job_id: str) -> JobRecord: ...


class JobDispatcher:
    """Preserves clip processing while selecting the reel pipeline for reel jobs."""

    def __init__(
        self,
        jobs: JobStore,
        clip_processor: JobProcessor,
        reel_processor: JobProcessor,
    ) -> None:
        self.jobs = jobs
        self.clip_processor = clip_processor
        self.reel_processor = reel_processor

    def run(self, job_id: str) -> JobRecord:
        if self.jobs.get(job_id).is_reel():
            return self.reel_processor.run(job_id)
        return self.clip_processor.run(job_id)