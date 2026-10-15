"""In-process execution of persisted daily Run tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import RunTrigger


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
        profile_id: UUID | None = None,
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
            profile_id = (
                UUID(str(task["payload"]["profile_id"]))
                if task.get("payload") and "profile_id" in task["payload"]
                else None
            )
            await asyncio.to_thread(
                self._runs.create,
                RunTrigger.SCHEDULED,
                manual_url=None,
                settings_snapshot=self._settings_snapshot(),
                profile_id=profile_id,
            )
            await asyncio.to_thread(
                self._tasks.finish,
                UUID(task["task_id"]),
                now,
                skipped_reason=None,
            )
        self.last_tick_at = now
