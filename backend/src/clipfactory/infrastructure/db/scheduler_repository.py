"""Persistence and calendar calculation for the daily Run task."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import ContentProfile, ScheduleRule
from clipfactory.infrastructure.db.models import ContentProfileRow, ScheduledTaskRow


class DailyScheduleRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def reconcile(self, now: datetime, grace_minutes: int) -> None:
        with self.sessions.begin() as session:
            active_profiles = list(
                session.scalars(
                    select(ContentProfileRow).where(ContentProfileRow.is_active.is_(True)).with_for_update()
                )
            )
            pending_tasks = list(
                session.scalars(
                    select(ScheduledTaskRow)
                    .where(ScheduledTaskRow.kind == "daily_run", ScheduledTaskRow.status == "pending")
                    .order_by(ScheduledTaskRow.due_at)
                    .with_for_update()
                )
            )

            # Map pending tasks by (profile_id, rule_id)
            pending_by_key: dict[tuple[str, str], ScheduledTaskRow] = {}
            for task in pending_tasks:
                pid = str(task.payload.get("profile_id")) if task.payload else None
                rule_id = str(task.payload.get("rule_id", "default")) if task.payload else None
                if pid and rule_id and (pid, rule_id) not in pending_by_key:
                    pending_by_key[(pid, rule_id)] = task
                else:
                    task.status = "skipped"
                    task.last_error = "Superfluous or unattached scheduled task"
                    task.updated_at = now

            active_ids = {str(p.id) for p in active_profiles}
            for (pid, rule_id), pending in list(pending_by_key.items()):
                if pid not in active_ids:
                    pending.status = "skipped"
                    pending.last_error = "Content Profile is no longer active"
                    pending.updated_at = now
                    del pending_by_key[(pid, rule_id)]

            for profile in active_profiles:
                p_obj = ContentProfile.model_validate(profile.value)
                rules = _effective_rules(p_obj)
                current_rule_ids = {str(r.id) for r in rules}

                # Cancel tasks for rules that no longer exist for this profile
                for (pid, rule_id), pending in list(pending_by_key.items()):
                    if pid == str(profile.id) and rule_id not in current_rule_ids:
                        pending.status = "skipped"
                        pending.last_error = "Schedule rule removed"
                        pending.updated_at = now
                        del pending_by_key[(pid, rule_id)]

                for rule in rules:
                    rule_key = (str(profile.id), str(rule.id))
                    signature = _rule_payload(profile.id, rule)
                    pending = pending_by_key.get(rule_key)

                    if not rule.enabled:
                        if pending is not None:
                            pending.status = "skipped"
                            pending.last_error = "Schedule rule is disabled"
                            pending.updated_at = now
                        continue

                    if pending is not None and pending.payload != signature:
                        pending.status = "skipped"
                        pending.last_error = "Schedule rule changed"
                        pending.updated_at = now
                        pending = None

                    if pending is not None and _as_utc(now) - _as_utc(pending.due_at) > timedelta(
                        minutes=grace_minutes
                    ):
                        pending.status = "skipped"
                        pending.last_error = "Daily Run missed its configured grace period"
                        pending.updated_at = now
                        self._add_task(
                            session, _next_occurrence_local(_as_utc(pending.due_at), rule.local_time), signature, now
                        )
                    elif pending is None:
                        due_at, missed_at = _initial_occurrence_local(now, rule.local_time, grace_minutes)
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
            if not task.payload or "profile_id" not in task.payload:
                return
            profile = session.get(ContentProfileRow, UUID(str(task.payload["profile_id"])))
            if profile is None or not profile.is_active:
                return
            p_obj = ContentProfile.model_validate(profile.value)
            rule_id = str(task.payload.get("rule_id", "default"))
            matching_rule = next((r for r in _effective_rules(p_obj) if str(r.id) == rule_id), None)
            if matching_rule is not None and matching_rule.enabled:
                self._add_task(
                    session,
                    _next_occurrence_local(_as_utc(task.due_at), matching_rule.local_time),
                    _rule_payload(profile.id, matching_rule),
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

    def all_schedules(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            profiles = list(session.scalars(select(ContentProfileRow).order_by(ContentProfileRow.name)))
            tasks = list(
                session.scalars(
                    select(ScheduledTaskRow)
                    .where(ScheduledTaskRow.kind == "daily_run", ScheduledTaskRow.status == "pending")
                    .order_by(ScheduledTaskRow.due_at)
                )
            )
            tasks_by_key: dict[tuple[str, str], ScheduledTaskRow] = {}
            for t in tasks:
                if t.payload and "profile_id" in t.payload:
                    pid = str(t.payload["profile_id"])
                    rid = str(t.payload.get("rule_id", "default"))
                    if (pid, rid) not in tasks_by_key:
                        tasks_by_key[(pid, rid)] = t

            results = []
            for profile in profiles:
                p = ContentProfile.model_validate(profile.value)
                rules = _effective_rules(p)
                if not rules:
                    results.append(
                        {
                            "profile_id": str(profile.id),
                            "profile_name": profile.name,
                            "rule_id": None,
                            "is_active": profile.is_active,
                            "local_time": None,
                            "enabled": False,
                            "schedule": {"enabled": False, "local_time": None, "timezone": "local"},
                            "task_id": None,
                            "due_at": None,
                            "status": "idle",
                        }
                    )
                for rule in rules:
                    task = tasks_by_key.get((str(profile.id), str(rule.id)))
                    results.append(
                        {
                            "profile_id": str(profile.id),
                            "profile_name": profile.name,
                            "rule_id": str(rule.id),
                            "is_active": profile.is_active,
                            "local_time": rule.local_time,
                            "enabled": rule.enabled,
                            "schedule": {
                                "enabled": rule.enabled,
                                "local_time": rule.local_time,
                                "timezone": "local",
                            },
                            "task_id": str(task.id) if task else None,
                            "due_at": _as_utc(task.due_at).isoformat() if task else None,
                            "status": "pending" if task else ("disabled" if not rule.enabled else "idle"),
                        }
                    )
            return results

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


def _effective_rules(profile: ContentProfile) -> list[ScheduleRule]:
    return profile.schedule_rules()


def _rule_payload(profile_id: UUID, rule: ScheduleRule) -> dict[str, Any]:
    return {
        "profile_id": str(profile_id),
        "rule_id": str(rule.id),
        "local_time": rule.local_time,
    }


def _local_timezone() -> tzinfo:
    configured = os.environ.get("TZ")
    if configured:
        return ZoneInfo(configured.removeprefix(":"))
    with Path("/etc/localtime").open("rb") as source:
        return ZoneInfo.from_file(source)


def _initial_occurrence_local(
    now: datetime, local_time_str: str, grace_minutes: int
) -> tuple[datetime, datetime | None]:
    current = _as_utc(now)
    tz = _local_timezone()
    local_date = current.astimezone(tz).date()
    today = _occurrence_local(local_date, local_time_str)
    if current <= today or current - today <= timedelta(minutes=grace_minutes):
        return today, None
    return _occurrence_local(local_date + timedelta(days=1), local_time_str), today


def _next_occurrence_local(previous: datetime, local_time_str: str) -> datetime:
    tz = _local_timezone()
    next_date = previous.astimezone(tz).date() + timedelta(days=1)
    return _occurrence_local(next_date, local_time_str)


def _occurrence_local(local_date: date, local_time_str: str) -> datetime:
    tz = _local_timezone()
    hour, minute = (int(part) for part in local_time_str.split(":"))
    candidate = datetime.combine(local_date, time(hour, minute))
    for offset in range(181):
        local_candidate = candidate + timedelta(minutes=offset)
        valid: list[datetime] = []
        for fold in (0, 1):
            aware = local_candidate.replace(tzinfo=tz, fold=fold)
            round_trip = aware.astimezone(UTC).astimezone(tz)
            if round_trip.replace(tzinfo=None) == local_candidate:
                valid.append(aware.astimezone(UTC))
        if valid:
            return min(valid)
    raise ValueError("No valid local schedule time within the DST gap window")


def _as_utc(value: datetime) -> datetime:
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).astimezone(UTC)
