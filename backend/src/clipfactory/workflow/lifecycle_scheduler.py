"""Execute publication lifecycle tasks persisted by the publish stage."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class LifecycleTasks(Protocol):
    def claim_task(self, now: datetime) -> dict[str, Any] | None: ...
    def task_done(self, task_id: UUID, now: datetime) -> None: ...
    def task_failed(self, task_id: UUID, now: datetime, message: str, attempts: int) -> None: ...


class Metrics(Protocol):
    async def collect(
        self, publication_id: UUID, offset_label: str, scheduled_for: datetime, captured_at: datetime
    ) -> None: ...


class ApprovalPublisher(Protocol):
    async def approve(self, clip_id: UUID, *, approved_by: str) -> dict[str, Any]: ...


class LifecycleScheduler:
    def __init__(self, tasks: LifecycleTasks, metrics: Metrics, approvals: ApprovalPublisher, *, clock: Any) -> None:
        self._tasks = tasks
        self._metrics = metrics
        self._approvals = approvals
        self._clock = clock
        self.last_tick_at: datetime | None = None

    async def run_once(self) -> None:
        now = self._clock()
        task = await asyncio.to_thread(self._tasks.claim_task, now)
        if task is None:
            self.last_tick_at = now
            return
        try:
            if task["kind"] == "metric_snapshot":
                await self._metrics.collect(
                    UUID(task["payload"]["publication_id"]),
                    task["payload"]["offset_label"],
                    task["due_at"],
                    now,
                )
            else:
                await self._approvals.approve(UUID(task["payload"]["clip_id"]), approved_by="auto_timeout")
        except Exception as exc:
            await asyncio.to_thread(self._tasks.task_failed, UUID(task["id"]), now, str(exc), int(task["attempts"]))
        else:
            await asyncio.to_thread(self._tasks.task_done, UUID(task["id"]), now)
        self.last_tick_at = now


class CompositeScheduler:
    def __init__(self, *schedulers: Any) -> None:
        self._schedulers = schedulers
        self.last_tick_at: datetime | None = None

    async def run_once(self) -> None:
        for scheduler in self._schedulers:
            await scheduler.run_once()
            if scheduler.last_tick_at is not None:
                self.last_tick_at = scheduler.last_tick_at
