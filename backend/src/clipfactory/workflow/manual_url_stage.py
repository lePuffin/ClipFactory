"""Workflow adapter for deterministic Manual URL ingestion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from clipfactory.domain.models import ContentProfile, Stage
from clipfactory.research.manual_url import ManualURLFailure, ManualURLIngest
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import WorkflowState


class ManualURLStageUseCase:
    def __init__(self, ingest: ManualURLIngest, runs: Any) -> None:
        self._ingest = ingest
        self._runs = runs

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        detail = await asyncio.to_thread(self._runs.get, run_id)
        manual_url = detail.get("manual_url")
        if not manual_url:
            raise StageFailure("url_unreachable", "Manual URL is missing from the Run")
        profile = ContentProfile.model_validate(detail["profile_snapshot"])
        configured = detail["settings_snapshot"].get("research", {})
        try:
            result = await self._ingest.execute(
                run_id,
                manual_url,
                profile,
                now=datetime.now(UTC),
                max_article_bytes=int(configured.get("max_article_bytes", 5_000_000)),
                publisher_quality=dict(configured.get("publisher_quality", {})),
            )
        except ManualURLFailure as exc:
            raise StageFailure(exc.code, str(exc)) from exc
        await asyncio.to_thread(
            self._runs.append_event,
            run_id,
            "story_selected",
            "Manual URL Story selected",
            stage=Stage.INGEST_URL.value,
            payload={"story_id": str(result.story_id), "title": result.title},
        )
        return {"story_id": str(result.story_id)}
