"""Persistence and calendar calculation for the daily Run task."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import ContentProfile, Schedule
from clipfactory.infrastructure.db.models import ContentProfileRow, ScheduledTaskRow


class DailyScheduleRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def reconcile(self, now: datetime, grace_minutes: int) -> None:
        with self.sessions.begin() as session:
            profile = session.scalar(select(ContentProfileRow).where(ContentProfileRow.is_active.is_(True)))
            pending = session.scalar(
                select(ScheduledTaskRow)
                .where(ScheduledTaskRow.kind == "daily_run", ScheduledTaskRow.status == "pending")
                .order_by(ScheduledTaskRow.due_at)
                .with_for_update()
                .limit(1)
            )
            if profile is None:
                return
            schedule = ContentProfile.model_validate(profile.value).schedule
            signature = _schedule_payload(profile.id, schedule)
            if not schedule.enabled:
                if pending is not None:
                    pending.status = "skipped"
                    pending.last_error = "Content Profile schedule is disabled"
                    pending.updated_at = now
                return
            if pending is not None and pending.payload != signature:
                pending.status = "skipped"
                pending.last_error = "Content Profile schedule changed"
                pending.updated_at = now
                pending = None
            if pending is not None and _as_utc(now) - _as_utc(pending.due_at) > timedelta(minutes=grace_minutes):
                pending.status = "skipped"
                pending.last_error = "Daily Run missed its configured grace period"
                pending.updated_at = now
                self._add_task(session, _next_occurrence(_as_utc(pending.due_at), schedule), signature, now)
            elif pending is None:
                due_at, missed_at = _initial_occurrence(now, schedule, grace_minutes)
                if missed_at is not None:
                    session.add(
                        ScheduledTaskRow(
                            kind="daily_run",
                            due_at=missed_at,
                            payload=signature,
                            status="skipped",
                            attempts=0,
                            last_error="Daily Run missed its configured grace period",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                self._add_task(session, due_at, signature, now)

    def claim_due(self, now: datetime) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            task = session.scalar(
                select(ScheduledTaskRow)
                .where(
                    ScheduledTaskRow.kind == "daily_run",
                    ScheduledTaskRow.status == "pending",
                    ScheduledTaskRow.due_at <= now,
                )
                .order_by(ScheduledTaskRow.due_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if task is None:
                return None
            task.status = "running"
            task.attempts += 1
            task.updated_at = now
            return {"task_id": str(task.id), "due_at": _as_utc(task.due_at), "payload": task.payload}

    def finish(self, task_id: UUID, now: datetime, *, skipped_reason: str | None = None) -> None:
        with self.sessions.begin() as session:
            task = session.scalar(select(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id).with_for_update())
            if task is None:
                raise LookupError(str(task_id))
            task.status = "skipped" if skipped_reason else "done"
            task.last_error = skipped_reason
            task.updated_at = now
            profile = session.get(ContentProfileRow, UUID(str(task.payload["profile_id"])))
            if profile is None:
                return
            schedule = ContentProfile.model_validate(profile.value).schedule
            if schedule.enabled:
                self._add_task(
                    session,
                    _next_occurrence(_as_utc(task.due_at), schedule),
                    _schedule_payload(profile.id, schedule),
                    now,
                )

    def pending(self) -> dict[str, Any] | None:
        with self.sessions() as session:
            task = session.scalar(
                select(ScheduledTaskRow)
                .where(ScheduledTaskRow.kind == "daily_run", ScheduledTaskRow.status == "pending")
                .order_by(ScheduledTaskRow.due_at)
                .limit(1)
            )
            if task is None:
                return None
            return {"task_id": str(task.id), "due_at": _as_utc(task.due_at), "payload": task.payload}

    @staticmethod
    def _add_task(session: Any, due_at: datetime, payload: dict[str, Any], now: datetime) -> None:
        session.add(
            ScheduledTaskRow(
                kind="daily_run",
                due_at=due_at,
                payload=payload,
                status="pending",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )


def _schedule_payload(profile_id: UUID, schedule: Schedule) -> dict[str, Any]:
    return {
        "profile_id": str(profile_id),
        "local_time": schedule.local_time,
        "timezone": schedule.timezone,
    }


def _initial_occurrence(now: datetime, schedule: Schedule, grace_minutes: int) -> tuple[datetime, datetime | None]:
    current = _as_utc(now)
    timezone = ZoneInfo(schedule.timezone)
    local_date = current.astimezone(timezone).date()
    today = _occurrence(local_date, schedule)
    if current <= today or current - today <= timedelta(minutes=grace_minutes):
        return today, None
    return _occurrence(local_date + timedelta(days=1), schedule), today


def _next_occurrence(previous: datetime, schedule: Schedule) -> datetime:
    timezone = ZoneInfo(schedule.timezone)
    next_date = previous.astimezone(timezone).date() + timedelta(days=1)
    return _occurrence(next_date, schedule)


def _occurrence(local_date: date, schedule: Schedule) -> datetime:
    timezone = ZoneInfo(schedule.timezone)
    hour, minute = (int(part) for part in schedule.local_time.split(":"))
    candidate = datetime.combine(local_date, time(hour, minute))
    for offset in range(181):
        local_candidate = candidate + timedelta(minutes=offset)
        valid: list[datetime] = []
        for fold in (0, 1):
            aware = local_candidate.replace(tzinfo=timezone, fold=fold)
            round_trip = aware.astimezone(UTC).astimezone(timezone)
            if round_trip.replace(tzinfo=None) == local_candidate:
                valid.append(aware.astimezone(UTC))
        if valid:
            return min(valid)
    raise ValueError(f"Could not resolve local schedule time in {schedule.timezone}")


def _as_utc(value: datetime) -> datetime:
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).astimezone(UTC)
