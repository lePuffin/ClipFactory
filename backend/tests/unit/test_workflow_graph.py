import asyncio
from typing import Any

import pytest

from clipfactory.domain.models import Stage
from clipfactory.workflow.graph import (
    StageTimeout,
    WorkflowState,
    _stage_node,
    build_workflow,
    renew_generation_watchdog,
    reset_stage_timeout,
    set_stage_timeout,
)


class FakeStageExecutor:
    def __init__(self, *, fail_first_evaluation: bool = False, fail_first_assets: bool = False) -> None:
        self.stages: list[Stage] = []
        self.fail_first_evaluation = fail_first_evaluation
        self.fail_first_assets = fail_first_assets

    async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
        self.stages.append(stage)
        if stage == Stage.SELECT_ASSETS:
            if self.fail_first_assets and state.get("attempt", 1) == 1:
                return {"last_evaluation_ids": ["eval-assets-failed"]}
            return {"last_evaluation_ids": ["eval-pass"]}
        if stage == Stage.EVALUATE_CLIP:
            if self.fail_first_evaluation and state.get("attempt", 1) == 1:
                return {"last_evaluation_ids": ["eval-1"]}
            return {"last_evaluation_ids": ["eval-pass"], "clip_id": "clip-1"}
        if stage == Stage.PLAN_RETRY:
            return {
                "attempt": 2,
                "revision_retries_used": 1,
                "reentry_stage": Stage.SELECT_ASSETS.value,
                "affected_segments": [2],
            }
        if stage == Stage.PUBLISH:
            return {"outcome": "not_published"}
        if stage in {Stage.WRITE_SCRIPT, Stage.GENERATE_NARRATION, Stage.COMPOSE_CLIP, Stage.VALIDATE_CLIP}:
            return {"last_evaluation_ids": ["eval-pass"]}
        return {}

    async def evaluation_passed(self, state: WorkflowState) -> bool:
        evaluation_ids = state.get("last_evaluation_ids") or []
        return bool(evaluation_ids) and evaluation_ids[-1] == "eval-pass"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-654")
@pytest.mark.asyncio
async def test_workflow_routes_manual_url_into_shared_production_stages() -> None:
    executor = FakeStageExecutor()
    graph = build_workflow(executor)
    result = await graph.ainvoke({"run_id": "run-1", "trigger": "manual_url", "attempt": 1})
    assert executor.stages[0] == Stage.INGEST_URL
    assert Stage.RESEARCH not in executor.stages
    assert executor.stages[1] == Stage.GATHER_SOURCES
    assert executor.stages[-1] == Stage.PUBLISH
    assert result["outcome"] == "not_published"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-410")
@pytest.mark.asyncio
async def test_failed_evaluation_reenters_only_the_selected_stage_and_approves_before_publish() -> None:
    executor = FakeStageExecutor(fail_first_evaluation=True)
    graph = build_workflow(executor)
    result = await graph.ainvoke({"run_id": "run-2", "trigger": "run_now", "attempt": 1})
    assert executor.stages.count(Stage.RESEARCH) == 1
    assert executor.stages.count(Stage.WRITE_SCRIPT) == 1
    assert executor.stages.count(Stage.SELECT_ASSETS) == 2
    assert executor.stages.count(Stage.PUBLISH) == 1
    assert result["clip_id"] == "clip-1"
    assert result["affected_segments"] == [2]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-410")
@pytest.mark.asyncio
async def test_failed_asset_gate_retries_before_narration_or_composition() -> None:
    executor = FakeStageExecutor(fail_first_assets=True)
    result = await build_workflow(executor).ainvoke({"run_id": "run-3", "trigger": "run_now", "attempt": 1})
    first_selection = executor.stages.index(Stage.SELECT_ASSETS)
    assert executor.stages[first_selection + 1] == Stage.PLAN_RETRY
    assert executor.stages[first_selection + 2] == Stage.SELECT_ASSETS
    assert executor.stages.count(Stage.GENERATE_NARRATION) == 1
    assert executor.stages.count(Stage.COMPOSE_CLIP) == 1
    assert executor.stages.count(Stage.WRITE_SCRIPT) == 1
    assert result["attempt"] == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-656")
@pytest.mark.asyncio
async def test_generation_watchdog_renews_deadline_and_expires_without_activity() -> None:
    class Executor(FakeStageExecutor):
        async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
            for _ in range(4):
                await asyncio.sleep(0.02)
                renew_generation_watchdog()
            return {}

    token = set_stage_timeout(0.05)
    try:
        node = _stage_node(Executor(), Stage.SELECT_ASSETS, None)
        assert await node({"run_id": "run-watchdog", "trigger": "run_now"}) == {}

        class Stalled(Executor):
            async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
                renew_generation_watchdog()
                await asyncio.sleep(0.1)
                return {}

        with pytest.raises(StageTimeout):
            await _stage_node(Stalled(), Stage.SELECT_ASSETS, None)({"run_id": "run-stalled", "trigger": "run_now"})
    finally:
        reset_stage_timeout(token)
