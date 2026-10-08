"""In-process execution of persisted daily Run tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import RunTrigger
from clipfactory.ports.runs import ActiveRunConflict


class DailyTasks(Protocol):
    def reconcile(self, now: datetime, grace_minutes: int) -> None: ...

    def claim_due(self, now: datetime) -> dict[str, Any] | None: ...

    def finish(self, task_id: UUID, now: datetime, *, skipped_reason: str | None = None) -> None: ...


class ScheduledRunCreator(Protocol):
    def create(
        self,
        trigger: RunTrigger,
        *,
        manual_url: str | None,
        settings_snapshot: dict[str, Any],
    ) -> dict[str, Any]: ...


class DailyRunScheduler:
    def __init__(
        self,
        tasks: DailyTasks,
        runs: ScheduledRunCreator,
        *,
        clock: Callable[[], datetime],
        settings_snapshot: Callable[[], dict[str, Any]],
        grace_minutes: int,
    ) -> None:
        self._tasks = tasks
        self._runs = runs
        self._clock = clock
        self._settings_snapshot = settings_snapshot
        self._grace_minutes = grace_minutes
        self.last_tick_at: datetime | None = None

    async def run_once(self) -> None:
        now = self._clock()
        await asyncio.to_thread(self._tasks.reconcile, now, self._grace_minutes)
        task = await asyncio.to_thread(self._tasks.claim_due, now)
        if task is not None:
            skipped_reason = None
            try:
                await asyncio.to_thread(
                    self._runs.create,
                    RunTrigger.SCHEDULED,
                    manual_url=None,
                    settings_snapshot=self._settings_snapshot(),
                )
            except ActiveRunConflict as exc:
                active = str(exc.active_run_id) if exc.active_run_id else "unknown"
                skipped_reason = f"Skipped because Run {active} is already active"
            await asyncio.to_thread(
                self._tasks.finish,
                UUID(task["task_id"]),
                now,
                skipped_reason=skipped_reason,
            )
        self.last_tick_at = now
