"""Single-process ownership of queued and interrupted workflow Runs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from clipfactory.ports.generation import GENERATION_ABORT
from clipfactory.ports.runs import RunContinuationConflict
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import StageTimeout, reset_stage_timeout, set_stage_timeout

logger = logging.getLogger(__name__)


class RunStore(Protocol):
    def stop_queued(self, run_id: UUID, now: datetime) -> dict[str, Any]: ...
    def append_event(
        self,
        run_id: UUID,
        event_type: str,
        message: str,
        *,
        stage: str | None = None,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def continue_failed(
        self, run_id: UUID, *, settings_snapshot: dict[str, Any], expected_stage: str, now: datetime
    ) -> dict[str, Any]: ...
    def claim_next_queued(self, now: datetime) -> dict[str, Any] | None: ...

    def running(self) -> list[dict[str, Any]]: ...

    def get(self, run_id: UUID) -> dict[str, Any]: ...

    def complete(self, run_id: UUID, outcome: str, clip_id: str | None, now: datetime) -> None: ...

    def fail(self, run_id: UUID, stage: str | None, code: str, message: str, now: datetime) -> None: ...


class WorkflowGraph(Protocol):
    async def aget_state(self, config: Any) -> Any: ...
    async def ainvoke(
        self,
        input: Any,
        config: Any = None,
        **kwargs: Any,
    ) -> Mapping[str, Any]: ...


class ActionableWorkflowError(RuntimeError):
    pass


class Scheduler(Protocol):
    last_tick_at: datetime | None

    async def run_once(self) -> None: ...


class WorkflowRunner:
    def __init__(
        self,
        runs: RunStore,
        graph: WorkflowGraph,
        *,
        clock: Callable[[], datetime],
        default_stage_timeout_seconds: float,
        prepare_run: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self._runs = runs
        self._graph = graph
        self._clock = clock
        self._default_stage_timeout_seconds = default_stage_timeout_seconds
        self._prepare_run = prepare_run
        self.last_config: dict[str, Any] | None = None
        self._control_lock = asyncio.Lock()
        self._active: dict[UUID, tuple[asyncio.Task[None], Event]] = {}

    async def run_next(self) -> bool:
        async with self._control_lock:
            run = await asyncio.to_thread(self._runs.claim_next_queued, self._clock())
            if run is None:
                return False
            task = self._start_execution(run, resume=bool(run.get("current_stage")))
        await task
        return True

    def _start_execution(self, run: dict[str, Any], *, resume: bool) -> asyncio.Task[None]:
        rid = UUID(run["run_id"])
        abort = Event()

        async def owned_execution() -> None:
            token = GENERATION_ABORT.set(abort)
            try:
                await self._execute(run, resume=resume)
            finally:
                GENERATION_ABORT.reset(token)
                self._active.pop(rid, None)

        task = asyncio.create_task(owned_execution())
        self._active[rid] = (task, abort)
        return task

    async def stop_run(self, run_id: UUID) -> dict[str, Any]:
        async with self._control_lock:
            run = await asyncio.to_thread(self._runs.get, run_id)
            if run["status"] == "queued":
                return await asyncio.to_thread(self._runs.stop_queued, run_id, self._clock())
            if run["status"] != "running":
                raise RunContinuationConflict("Only queued or running Runs can be stopped")
            if run.get("current_stage") == "publish":
                raise RunContinuationConflict("Publication cannot be safely interrupted; check platform outcomes")
            active = self._active.get(run_id)
            if active is None:
                raise RunContinuationConflict("Run has no active worker; refresh and retry")
            task, abort = active
            if not abort.is_set():
                await asyncio.to_thread(
                    self._runs.append_event,
                    run_id,
                    "run_stop_requested",
                    "Owner requested immediate cancellation; waiting for active work to release resources",
                    stage=run.get("current_stage"),
                    payload={},
                )
                abort.set()
                task.cancel()
            return {"run_id": str(run_id)}

    async def continue_run(self, run_id: UUID, settings_snapshot: dict[str, Any]) -> dict[str, Any]:
        run = await asyncio.to_thread(self._runs.get, run_id)
        if run["status"] != "failed":
            raise RunContinuationConflict("Only failed Runs can be continued")
        if run.get("failure_code") == "evaluation_failed_after_retries":
            raise RunContinuationConflict("Revision retries are exhausted; start a new Run")
        stage = run.get("failure_stage")
        if not stage or stage == "publish":
            raise RunContinuationConflict("This failure cannot be safely continued; check publication outcomes")
        checkpoint = await self._graph.aget_state({"configurable": {"thread_id": str(run_id)}})
        if tuple(checkpoint.next) != (stage,):
            raise RunContinuationConflict("No matching pending checkpoint exists; start a new Run")
        return await asyncio.to_thread(
            self._runs.continue_failed,
            run_id,
            settings_snapshot=settings_snapshot,
            expected_stage=stage,
            now=self._clock(),
        )

    async def recover_interrupted(self) -> None:
        for run in await asyncio.to_thread(self._runs.running):
            workflow_settings = run.get("settings_snapshot", {}).get("workflow", {})
            if workflow_settings.get("resume_interrupted_runs", True):
                await self._start_execution(run, resume=True)
            else:
                await asyncio.to_thread(
                    self._runs.fail,
                    UUID(run["run_id"]),
                    run.get("current_stage"),
                    "interrupted",
                    "Run was interrupted and automatic resumption is disabled",
                    self._clock(),
                )

    async def _execute(self, run: dict[str, Any], *, resume: bool) -> None:
        run_id = UUID(run["run_id"])
        workflow_settings = run.get("settings_snapshot", {}).get("workflow", {})
        timeout_seconds = float(workflow_settings.get("stage_timeout_seconds", self._default_stage_timeout_seconds))
        config = {"configurable": {"thread_id": str(run_id)}}
        self.last_config = config
        state = None if resume else {"run_id": str(run_id), "trigger": run["trigger"], "attempt": run["attempt"]}
        token = set_stage_timeout(timeout_seconds)
        context = {"run_id": str(run_id)}
        logger.info("Run %s (%s)", "resumed" if resume else "started", run["trigger"], extra=context)
        try:
            if self._prepare_run is not None:
                self._prepare_run(run.get("settings_snapshot", {}))
            result = await self._graph.ainvoke(state, config)
            outcome = result.get("outcome")
            if not isinstance(outcome, str) or not outcome:
                raise RuntimeError("workflow finished without an outcome")
            clip_id = result.get("clip_id")
            logger.info("Run completed: outcome=%s clip_id=%s", outcome, clip_id, extra=context)
            await asyncio.to_thread(
                self._runs.complete,
                run_id,
                outcome,
                str(clip_id) if clip_id else None,
                self._clock(),
            )
        except asyncio.CancelledError:
            abort = GENERATION_ABORT.get()
            if abort is not None and abort.is_set():
                detail = await asyncio.to_thread(self._runs.get, run_id)
                await asyncio.to_thread(
                    self._runs.fail,
                    run_id,
                    detail["current_stage"],
                    "owner_stopped",
                    "Run stopped by owner; unfinished generation may be unavailable",
                    self._clock(),
                )
                return
            raise
        except StageTimeout as exc:
            logger.error("Run failed: stage_timeout: %s", exc, extra={**context, "stage": exc.stage.value})
            await asyncio.to_thread(
                self._runs.fail,
                run_id,
                exc.stage.value,
                "stage_timeout",
                str(exc),
                self._clock(),
            )
        except StageFailure as exc:
            detail = await asyncio.to_thread(self._runs.get, run_id)
            logger.error(
                "Run failed: %s: %s",
                exc.code,
                exc,
                extra={**context, "stage": detail["current_stage"]},
                exc_info=exc.__cause__ is not None and logger.isEnabledFor(logging.DEBUG),
            )
            await asyncio.to_thread(
                self._runs.fail,
                run_id,
                detail["current_stage"],
                exc.code,
                str(exc),
                self._clock(),
            )
        except ActionableWorkflowError as exc:
            detail = await asyncio.to_thread(self._runs.get, run_id)
            logger.exception("Workflow configuration failure", extra=context)
            await asyncio.to_thread(
                self._runs.fail,
                run_id,
                detail["current_stage"],
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                self._clock(),
            )
        except Exception as exc:
            detail = await asyncio.to_thread(self._runs.get, run_id)
            logger.exception(
                "Unexpected workflow failure: %s: %s",
                type(exc).__name__,
                exc,
                extra={**context, "stage": detail["current_stage"]},
            )
            await asyncio.to_thread(
                self._runs.fail,
                run_id,
                detail["current_stage"],
                "internal_error",
                f"{type(exc).__name__}: unexpected workflow failure; see the server log for the stack trace",
                self._clock(),
            )
        finally:
            reset_stage_timeout(token)


class RunLifecycleService:
    def __init__(
        self,
        runner: WorkflowRunner,
        *,
        scheduler_enabled: bool,
        scheduler: Scheduler | None = None,
        poll_interval_seconds: float = 0.25,
        scheduler_poll_interval_seconds: float = 30,
    ) -> None:
        self._runner = runner
        self._scheduler_enabled = scheduler_enabled
        self._scheduler = scheduler
        self._poll_interval_seconds = poll_interval_seconds
        self._scheduler_poll_interval_seconds = scheduler_poll_interval_seconds
        self._worker_task: asyncio.Task[None] | None = None
        self._scheduler_task: asyncio.Task[None] | None = None

    @property
    def worker_alive(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    @property
    def scheduler_alive(self) -> bool:
        if not self._scheduler_enabled:
            return True
        return (
            self._scheduler_task is not None
            and not self._scheduler_task.done()
            and self._scheduler is not None
            and self._scheduler.last_tick_at is not None
        )

    async def start(self) -> None:
        if self.worker_alive:
            return
        self._worker_task = asyncio.create_task(self._run(), name="clipfactory-run-worker")
        if self._scheduler_enabled and self._scheduler is not None:
            self._scheduler_task = asyncio.create_task(self._run_scheduler(), name="clipfactory-scheduler")

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None

    async def _run(self) -> None:
        await self._runner.recover_interrupted()
        while True:
            claimed = await self._runner.run_next()
            if not claimed:
                await asyncio.sleep(self._poll_interval_seconds)

    async def _run_scheduler(self) -> None:
        if self._scheduler is None:
            return
        while True:
            await self._scheduler.run_once()
            await asyncio.sleep(self._scheduler_poll_interval_seconds)
