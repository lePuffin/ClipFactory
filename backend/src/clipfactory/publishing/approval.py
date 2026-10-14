"""Resolve owner or timeout approval through the normal publication service."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from clipfactory.publishing.service import PublishService


class PublicationRetryConflict(RuntimeError):
    """The Clip is not approved or has no failed Publication to retry."""


class ApprovalService:
    def __init__(self, repository: Any, publisher: PublishService, *, clock: Any) -> None:
        self._repository = repository
        self._publisher = publisher
        self._clock = clock

    async def decide(self, clip_id: UUID, decision: str) -> dict[str, Any]:
        resolution = await asyncio.to_thread(self._repository.resolve_approval, clip_id, decision, self._clock())
        if decision == "reject" or resolution["already_resolved"]:
            return resolution
        result = await self._publisher.execute(UUID(resolution["run_id"]), clip_id, approval_resolved=True)
        await asyncio.to_thread(self._repository.update_run_outcome, UUID(resolution["run_id"]), result["outcome"])
        return {**resolution, **result}

    async def approve(self, clip_id: UUID, *, approved_by: str) -> dict[str, Any]:
        if approved_by == "auto_timeout":
            eligibility = getattr(self._repository, "auto_publish_eligible", None)
            if not callable(eligibility) or not await asyncio.to_thread(eligibility, clip_id):
                raise RuntimeError("Automatic publication requires explicit benchmark and exact-version eligibility")
        result = await self.decide(clip_id, "approve")
        return {**result, "approved_by": approved_by}

    async def retry_failed(self, clip_id: UUID) -> dict[str, Any]:
        """Re-publish only the failed Publications of an approved Clip (CF-REQ-462)."""
        reset = await asyncio.to_thread(self._repository.reset_failed_publications, clip_id)
        if reset["clip_status"] != "approved":
            raise PublicationRetryConflict("Only approved Clips may be published")
        if not reset["reset"]:
            raise PublicationRetryConflict("The Clip has no failed Publication to retry")
        run_id = UUID(reset["run_id"])
        result = await self._publisher.execute(run_id, clip_id, approval_resolved=True)
        await asyncio.to_thread(self._repository.update_run_outcome, run_id, result["outcome"])
        return {"run_id": reset["run_id"], "clip_id": str(clip_id), "retried": reset["reset"], **result}
