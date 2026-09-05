"""A minimal single-worker executor for local long-running processing jobs."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from app.pipelines.dispatch import JobProcessor

logger = logging.getLogger(__name__)


class JobRunner:
    """Keeps video work off FastAPI's request-handling thread without adding a queue service."""

    def __init__(self, pipeline: JobProcessor) -> None:
        self._pipeline = pipeline
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clipfactory-worker")
        self._futures: dict[str, Future[object]] = {}

    def submit(self, job_id: str) -> Future[object]:
        logger.info("Submitting job %s to the local worker", job_id)
        future = self._executor.submit(self._pipeline.run, job_id)
        self._futures[job_id] = future
        return future

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
