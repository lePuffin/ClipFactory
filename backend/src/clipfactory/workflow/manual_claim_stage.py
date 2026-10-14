"""Claim extraction stage for persisted Stories that do not yet have Claims."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from clipfactory.domain.models import Stage
from clipfactory.ports.errors import ProviderError
from clipfactory.research.manual_url import ManualURLClaimExtractor, ManualURLFailure
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import WorkflowState
from clipfactory.workflow.research_stages import PersistedResearchStageUseCase


class ClaimExtractionStageUseCase:
    def __init__(self, extractor: ManualURLClaimExtractor, repository: Any, runs: Any) -> None:
        self._extractor = extractor
        self._repository = repository
        self._runs = runs
        self._persisted = PersistedResearchStageUseCase(Stage.EXTRACT_CLAIMS, repository, runs)

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        summary = await asyncio.to_thread(self._repository.summary, run_id)
        if summary is None:
            raise StageFailure("internal_error", "Persisted grounded research output is missing")
        if int(summary["accepted"]) + int(summary["rejected"]) == 0:
            detail = await asyncio.to_thread(self._runs.get, run_id)
            try:
                await self._extractor.execute(
                    run_id,
                    max_input_chars=int(detail["settings_snapshot"].get("llm", {}).get("max_input_chars", 60_000)),
                )
            except ManualURLFailure as exc:
                raise StageFailure(exc.code, str(exc)) from exc
            except ProviderError as exc:
                code = "llm_invalid_output" if exc.code == "llm_invalid_output" else "llm_unavailable"
                raise StageFailure(code, str(exc)) from exc
        return await self._persisted.execute(state)
