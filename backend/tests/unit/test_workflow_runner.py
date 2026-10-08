import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine

from clipfactory.domain.models import RunTrigger, Stage
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.ports.runs import ActiveRunConflict, RunContinuationConflict
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import WorkflowState, build_workflow
from clipfactory.workflow.runner import ActionableWorkflowError, RunLifecycleService, WorkflowRunner

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


class FakeGraph:
    def __init__(self, *, result: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.result = result or {"outcome": "not_published", "clip_id": None}
        self.error = error
        self.inputs: list[dict[str, Any] | None] = []
        self.next: tuple[str, ...] = ("select_assets",)

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(next=self.next)

    async def ainvoke(self, input: dict[str, Any] | None, config: Any = None, **kwargs: Any) -> dict[str, Any]:
        self.inputs.append(input)
        if self.error:
            raise self.error
        return self.result


class BlockingExecutor:
    async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
        await asyncio.Event().wait()
        return {}

    async def evaluation_passed(self, state: WorkflowState) -> bool:
        return True


class TickingScheduler:
    def __init__(self) -> None:
        self.last_tick_at: datetime | None = None

    async def run_once(self) -> None:
        self.last_tick_at = NOW


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runner.db'}")
    Base.metadata.create_all(engine)
    yield RunRepository(create_session_factory(engine))
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-411")
def test_retry_counters_and_event_are_persisted_once(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    run_id = UUID(created["run_id"])
    repository.claim_next_queued(NOW)
    for _ in range(2):
        repository.apply_retry(
            run_id,
            attempt=2,
            revision_retries_used=1,
            reentry_stage="write_script",
            action_types=("rewrite_script",),
            retries_remaining=2,
        )
    detail = repository.get(run_id)
    assert detail["attempt"] == 2
    assert detail["revision_retries_used"] == 1
    retries = [event for event in detail["events"] if event["type"] == "retry_started"]
    assert len(retries) == 1
    assert retries[0]["payload"]["reentry_stage"] == "write_script"
    assert retries[0]["payload"]["retries_remaining"] == 2
    with pytest.raises(ValueError, match="exactly once"):
        repository.apply_retry(run_id, attempt=4, revision_retries_used=3)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-654")
@pytest.mark.asyncio
async def test_runner_completes_claimed_run_with_postgres_thread_id(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    graph = FakeGraph()
    runner = WorkflowRunner(repository, graph, clock=lambda: NOW, default_stage_timeout_seconds=1)

    assert await runner.run_next() is True

    detail = repository.get(UUID(created["run_id"]))
    assert detail["status"] == "completed"
    assert detail["outcome"] == "not_published"
    assert detail["events"][-1]["type"] == "run_completed"
    assert graph.inputs == [{"run_id": created["run_id"], "trigger": "run_now", "attempt": 1}]
    assert runner.last_config == {"configurable": {"thread_id": created["run_id"]}}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_owner_continuation_preserves_run_and_resumes_checkpoint_with_current_settings(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={"old": True})
    rid = UUID(created["run_id"])
    repository.claim_next_queued(NOW)
    repository.apply_retry(rid, attempt=2, revision_retries_used=1)
    repository.start_stage(rid, "select_assets")
    repository.fail(rid, "select_assets", "stage_timeout", "Timed out", NOW)
    graph = FakeGraph()
    prepared = []
    runner = WorkflowRunner(
        repository,
        graph,
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
        prepare_run=lambda snapshot: prepared.append(snapshot),
    )
    await runner.continue_run(rid, {"workflow": {"stage_timeout_seconds": 7200}})
    queued = repository.get(rid)
    assert queued["status"] == "queued"
    assert queued["failure_code"] is None
    assert queued["finished_at"] is None
    assert queued["attempt"] == 2
    assert queued["revision_retries_used"] == 1
    assert queued["events"][-1]["type"] == "run_resumed"
    assert queued["events"][-1]["payload"]["previous_settings_snapshot"] == {"old": True}
    await runner.run_next()
    assert graph.inputs == [None]
    assert prepared == [{"workflow": {"stage_timeout_seconds": 7200}}]
    assert repository.get(rid)["status"] == "completed"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["missing_checkpoint", "exhausted", "publication", "not_failed", "active_run"])
async def test_unsafe_continuations_are_rejected_without_modifying_run(repository, reason) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    rid = UUID(created["run_id"])
    repository.claim_next_queued(NOW)
    stage = "publish" if reason == "publication" else "select_assets"
    repository.start_stage(rid, stage)
    if reason != "not_failed":
        repository.fail(
            rid, stage, "evaluation_failed_after_retries" if reason == "exhausted" else "stage_timeout", "Failure", NOW
        )
    if reason == "active_run":
        repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    graph = FakeGraph()
    graph.next = () if reason == "missing_checkpoint" else (stage,)
    before = repository.get(rid)
    runner = WorkflowRunner(repository, graph, clock=lambda: NOW, default_stage_timeout_seconds=1)
    with pytest.raises(ActiveRunConflict if reason == "active_run" else RunContinuationConflict):
        await runner.continue_run(rid, {"changed": True})
    assert repository.get(rid) == before


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_real_checkpoint_continues_failed_stage_without_repeating_research(repository) -> None:
    class Executor:
        def __init__(self) -> None:
            self.calls: list[Stage] = []
            self.fail = True

        async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
            self.calls.append(stage)
            if stage == Stage.SELECT_ASSETS and self.fail:
                raise StageFailure("stage_timeout", "Test timeout")
            return {"outcome": "not_published"} if stage == Stage.PUBLISH else {}

        async def evaluation_passed(self, state: WorkflowState) -> bool:
            return True

    executor = Executor()
    graph = build_workflow(executor, checkpointer=MemorySaver(), stage_observer=repository)
    runner = WorkflowRunner(repository, graph, clock=lambda: NOW, default_stage_timeout_seconds=1)
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    await runner.run_next()
    assert repository.get(rid)["status"] == "failed"
    executor.fail = False
    await runner.continue_run(rid, {})
    await runner.run_next()
    assert executor.calls.count(Stage.RESEARCH) == 1
    assert executor.calls.count(Stage.WRITE_SCRIPT) == 1
    assert executor.calls.count(Stage.SELECT_ASSETS) == 2
    assert repository.get(rid)["status"] == "completed"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_stop_cancels_only_owned_run_and_worker_can_run_again(repository) -> None:
    entered = asyncio.Event()

    class BlockingGraph(FakeGraph):
        async def ainvoke(self, input, config=None, **kwargs):
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Blocking graph should only exit by cancellation")

    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    runner = WorkflowRunner(repository, BlockingGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1)
    worker = asyncio.create_task(runner.run_next())
    await entered.wait()
    repository.start_stage(rid, "select_assets")
    await runner.stop_run(rid)
    assert await worker is True
    detail = repository.get(rid)
    assert detail["failure_code"] == "owner_stopped"
    assert detail["status"] == "failed"
    assert any(e["type"] == "run_stop_requested" for e in detail["events"])
    runner._graph = FakeGraph()
    repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    assert await runner.run_next()
    assert repository.active() is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_stop_queued_run_and_reject_stop_of_terminal_run(repository) -> None:
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    runner = WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1)
    await runner.stop_run(rid)
    assert repository.get(rid)["failure_code"] == "owner_stopped"
    assert not await runner.run_next()
    with pytest.raises(RunContinuationConflict):
        await runner.stop_run(rid)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_stop_rejects_publication_without_cancelling_worker(repository) -> None:
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    repository.claim_next_queued(NOW)
    repository.start_stage(rid, "publish")
    runner = WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1)
    with pytest.raises(RunContinuationConflict, match="Publication"):
        await runner.stop_run(rid)
    assert repository.get(rid)["status"] == "running"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_stop_is_idempotent_while_cleanup_drains_and_keeps_checkpoint_for_continue(repository) -> None:
    entered, draining, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class Executor:
        stop_once = True

        async def execute(self, stage, state):
            if stage == Stage.SELECT_ASSETS and self.stop_once:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    draining.set()
                    await release.wait()
                    raise
            return {"outcome": "not_published"} if stage == Stage.PUBLISH else {}

        async def evaluation_passed(self, state):
            return True

    executor = Executor()
    runner = WorkflowRunner(
        repository,
        build_workflow(executor, checkpointer=MemorySaver(), stage_observer=repository),
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
    )
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    worker = asyncio.create_task(runner.run_next())
    await entered.wait()
    await runner.stop_run(rid)
    await draining.wait()
    await runner.stop_run(rid)
    assert repository.get(rid)["status"] == "running"
    assert len([e for e in repository.get(rid)["events"] if e["type"] == "run_stop_requested"]) == 1
    release.set()
    await worker
    assert repository.get(rid)["failure_code"] == "owner_stopped"
    executor.stop_once = False
    await runner.continue_run(rid, {})
    await runner.run_next()
    assert repository.get(rid)["status"] == "completed"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
@pytest.mark.asyncio
async def test_runner_converts_unexpected_exception_to_actionable_internal_error(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    runner = WorkflowRunner(
        repository,
        FakeGraph(error=ValueError("secret detail")),
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
    )

    await runner.run_next()

    detail = repository.get(UUID(created["run_id"]))
    assert detail["failure_code"] == "internal_error"
    assert detail["failure_message"] == (
        "ValueError: unexpected workflow failure; see the server log for the stack trace"
    )
    assert "secret detail" not in detail["failure_message"]
    assert detail["events"][-1]["type"] == "run_failed"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-851")
@pytest.mark.asyncio
async def test_stage_failure_is_logged_with_run_context(repository, caplog: pytest.LogCaptureFixture) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    runner = WorkflowRunner(
        repository,
        FakeGraph(error=StageFailure("llm_unavailable", "LLM request failed with HTTP 404")),
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
    )

    with caplog.at_level(logging.INFO, logger="clipfactory"):
        await runner.run_next()

    failure = next(record for record in caplog.records if record.levelno == logging.ERROR)
    assert "llm_unavailable: LLM request failed with HTTP 404" in failure.getMessage()
    assert getattr(failure, "run_id", None) == created["run_id"]
    assert hasattr(failure, "stage")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
@pytest.mark.asyncio
async def test_runner_preserves_safe_action_for_unassembled_stage_executor(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    runner = WorkflowRunner(
        repository,
        FakeGraph(error=ActionableWorkflowError("Production StageExecutor is not assembled")),
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
    )

    await runner.run_next()

    detail = repository.get(UUID(created["run_id"]))
    assert detail["failure_code"] == "internal_error"
    assert detail["failure_message"] == ("ActionableWorkflowError: Production StageExecutor is not assembled")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-656")
@pytest.mark.asyncio
async def test_runner_enforces_timeout_around_each_graph_stage(repository) -> None:
    created = repository.create(
        RunTrigger.RUN_NOW,
        manual_url=None,
        settings_snapshot={"workflow": {"stage_timeout_seconds": 0.01}},
    )
    runner = WorkflowRunner(
        repository,
        build_workflow(BlockingExecutor(), stage_observer=repository),
        clock=lambda: NOW,
        default_stage_timeout_seconds=1,
    )

    await runner.run_next()

    detail = repository.get(UUID(created["run_id"]))
    assert detail["failure_code"] == "stage_timeout"
    assert detail["failure_stage"] == "research"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_runner_resumes_running_run_from_checkpoint_when_enabled(repository) -> None:
    created = repository.create(
        RunTrigger.RUN_NOW,
        manual_url=None,
        settings_snapshot={"workflow": {"resume_interrupted_runs": True}},
    )
    repository.claim_next_queued(datetime(2026, 10, 1, tzinfo=UTC))
    graph = FakeGraph()
    runner = WorkflowRunner(repository, graph, clock=lambda: NOW, default_stage_timeout_seconds=1)

    await runner.recover_interrupted()

    assert graph.inputs == [None]
    assert repository.get(UUID(created["run_id"]))["status"] == "completed"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.asyncio
async def test_runner_fails_running_run_when_resumption_is_disabled(repository) -> None:
    created = repository.create(
        RunTrigger.RUN_NOW,
        manual_url=None,
        settings_snapshot={"workflow": {"resume_interrupted_runs": False}},
    )
    repository.claim_next_queued(datetime(2026, 10, 1, tzinfo=UTC))
    runner = WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1)

    await runner.recover_interrupted()

    detail = repository.get(UUID(created["run_id"]))
    assert detail["failure_code"] == "interrupted"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-660")
@pytest.mark.asyncio
async def test_lifecycle_worker_processes_queue_with_scheduler_disabled(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    lifecycle = RunLifecycleService(
        WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1),
        scheduler_enabled=False,
        poll_interval_seconds=0.01,
    )

    await lifecycle.start()
    for _ in range(50):
        if repository.get(UUID(created["run_id"]))["status"] == "completed":
            break
        await asyncio.sleep(0.01)
    assert lifecycle.worker_alive is True
    assert lifecycle.scheduler_alive is True
    await lifecycle.stop()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
async def test_lifecycle_reports_enabled_unassembled_scheduler_not_live(repository) -> None:
    lifecycle = RunLifecycleService(
        WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1),
        scheduler_enabled=True,
        poll_interval_seconds=0.01,
    )

    await lifecycle.start()
    assert lifecycle.scheduler_alive is False
    await lifecycle.stop()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
async def test_lifecycle_reports_enabled_scheduler_live_after_tick(repository) -> None:
    scheduler = TickingScheduler()
    lifecycle = RunLifecycleService(
        WorkflowRunner(repository, FakeGraph(), clock=lambda: NOW, default_stage_timeout_seconds=1),
        scheduler_enabled=True,
        scheduler=scheduler,
        scheduler_poll_interval_seconds=60,
    )

    await lifecycle.start()
    await asyncio.sleep(0)
    assert lifecycle.scheduler_alive is True
    await lifecycle.stop()
