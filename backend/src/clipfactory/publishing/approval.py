"""Resolve owner or timeout approval through the normal publication service."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from clipfactory.publishing.service import PublishService


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
