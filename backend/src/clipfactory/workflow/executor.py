"""Production stage dispatch across provider-independent application boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from clipfactory.domain.models import Stage
from clipfactory.workflow.graph import WorkflowState


class StageFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StageUseCase(Protocol):
    async def execute(self, state: WorkflowState) -> Mapping[str, Any]: ...


class EvaluationStatusReader(Protocol):
    async def passed(self, state: WorkflowState) -> bool: ...


class ProductionStageExecutor:
    def __init__(
        self,
        handlers: Mapping[Stage, StageUseCase],
        *,
        evaluation_status: EvaluationStatusReader | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self._evaluation_status = evaluation_status

    @property
    def supported_stages(self) -> frozenset[Stage]:
        return frozenset(self._handlers)

    async def execute(self, stage: Stage, state: WorkflowState) -> Mapping[str, Any]:
        handler = self._handlers.get(stage)
        if handler is None:
            raise StageFailure(
                "provider_unavailable",
                f"Stage {stage.value} has no configured production application boundary",
            )
        return await handler.execute(state)

    async def evaluation_passed(self, state: WorkflowState) -> bool:
        if self._evaluation_status is None:
            raise StageFailure(
                "provider_unavailable",
                "Evaluation status application boundary is not configured",
            )
        return await self._evaluation_status.passed(state)
