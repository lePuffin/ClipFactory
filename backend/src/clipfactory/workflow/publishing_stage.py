"""Workflow adapter for provider-independent publishing."""

from __future__ import annotations

from uuid import UUID

from clipfactory.publishing.service import PublishService
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import WorkflowState


class PublishStageUseCase:
    def __init__(self, publisher: PublishService) -> None:
        self._publisher = publisher

    async def execute(self, state: WorkflowState) -> dict[str, str]:
        clip_id = state.get("clip_id")
        if not clip_id:
            raise StageFailure("internal_error", "Publish stage requires an approved Clip ID")
        try:
            return await self._publisher.execute(UUID(state["run_id"]), UUID(clip_id))
        except RuntimeError as exc:
            raise StageFailure("clip_not_approved", str(exc)) from exc
