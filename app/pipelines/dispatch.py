"""Routes persisted job variants to the appropriate local processing pipeline."""

from typing import Protocol

from app.models.job import JobRecord
from app.services.jobs import JobStore


class JobProcessor(Protocol):
    """Common execution contract consumed by the single local worker."""

    def run(self, job_id: str) -> JobRecord: ...


class JobDispatcher:
    """Routes legacy clip extraction and composed clip jobs to the correct processor."""

    def __init__(
        self,
        jobs: JobStore,
        standard_processor: JobProcessor,
        clip_processor: JobProcessor,
        reel_processor: JobProcessor | None = None,
    ) -> None:
        self.jobs = jobs
        self.standard_processor = standard_processor
        self.clip_processor = clip_processor
        self.reel_processor = reel_processor

    def run(self, job_id: str) -> JobRecord:
        job = self.jobs.get(job_id)
        if job.is_reel():
            if self.reel_processor is None:
                raise ValueError("The reel processor is not configured")
            return self.reel_processor.run(job_id)
        if job.is_clip():
            return self.clip_processor.run(job_id)
        return self.standard_processor.run(job_id)