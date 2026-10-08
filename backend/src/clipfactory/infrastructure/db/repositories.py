"""SQLAlchemy repositories for Runs and their ordered operational events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import ContentProfile, RunTrigger
from clipfactory.infrastructure.db.models import ContentProfileRow, EvaluationRow, LLMRequestRow, RunEventRow, RunRow
from clipfactory.ports.runs import ActiveRunConflict, LLMBudgetExhausted, RunContinuationConflict, RunNotFound


class RunRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def reserve_generation_start(
        self, run_id: UUID, *, provider: str, limit: int, segment_index: int, now: datetime
    ) -> bool:
        """Commit the start before entering the generator; legacy starts are already reservations."""
        if not 0 <= limit <= 100:
            raise ValueError("Generation limit must be between 0 and 100")
        with self.sessions.begin() as session:
            # SQLite test stores have no row locks; serialize writers before reading usage.
            if session.get_bind().dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(RunEventRow)
                    .where(
                        RunEventRow.run_id == run_id,
                        RunEventRow.payload["provider"].as_string() == provider,
                        RunEventRow.payload["generation_phase"].as_string() == "started",
                    )
                )
                or 0
            )
            permitted = count < limit
            _append_event(
                session,
                run,
                "progress",
                f"{provider}: reserved generation {count + 1} of {limit}"
                if permitted
                else f"{provider}: generation cap reached ({count}/{limit}); choosing permitted alternatives",
                now,
                stage="select_assets",
                payload={
                    "provider": provider,
                    "generation_phase": "started" if permitted else "cap_skipped",
                    "generation_reserved": permitted,
                    "generation_count": count + int(permitted),
                    "generation_limit": limit,
                    "segment_index": segment_index,
                },
            )
            return permitted

    def create(
        self,
        trigger: RunTrigger,
        *,
        manual_url: str | None,
        settings_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        try:
            with self.sessions.begin() as session:
                llm_policy = settings_snapshot.get("llm", {})
                timezone = ZoneInfo(llm_policy.get("daily_reset_timezone", "UTC"))
                local_now = now.astimezone(timezone)
                day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
                used_today = (
                    session.scalar(
                        select(func.count()).select_from(LLMRequestRow).where(LLMRequestRow.started_at >= day_start)
                    )
                    or 0
                )
                daily_limit = int(llm_policy.get("requests_per_day", 50))
                minimum = int(
                    llm_policy.get(
                        "min_daily_requests_to_start_manual_run"
                        if trigger == RunTrigger.MANUAL_URL
                        else "min_daily_requests_to_start_run",
                        4 if trigger == RunTrigger.MANUAL_URL else 5,
                    )
                )
                if trigger != RunTrigger.SCHEDULED and daily_limit - used_today < minimum:
                    raise LLMBudgetExhausted("Not enough daily LLM requests remain to start this Run")
                profile = session.scalar(
                    select(ContentProfileRow).where(ContentProfileRow.is_active.is_(True)).with_for_update()
                )
                if profile is None:
                    default_profile = ContentProfile()
                    profile = ContentProfileRow(
                        id=default_profile.id,
                        name=default_profile.name,
                        is_active=True,
                        value=default_profile.model_dump(mode="json"),
                        updated_at=now,
                    )
                    session.add(profile)
                    session.flush()
                run = RunRow(
                    id=uuid4(),
                    trigger=trigger.value,
                    manual_url=manual_url,
                    profile_id=profile.id,
                    profile_snapshot=profile.value,
                    settings_snapshot=settings_snapshot,
                    status="queued",
                    attempt=1,
                    revision_retries_used=0,
                    created_at=now,
                    cost_total=0,
                )
                session.add(run)
                session.flush()
                session.add(
                    RunEventRow(
                        run_id=run.id,
                        sequence=1,
                        type="run_started",
                        stage=None,
                        attempt=1,
                        level="info",
                        message="Run queued",
                        payload={"trigger": trigger.value, "profile_id": str(profile.id)},
                        created_at=now,
                    )
                )
                session.flush()
                result = _run_summary(run)
        except IntegrityError as exc:
            with self.sessions() as session:
                active = session.scalar(select(RunRow).where(RunRow.status.in_(("queued", "running"))).limit(1))
                raise ActiveRunConflict(active.id if active else None) from exc
        return result

    def get(self, run_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise RunNotFound(str(run_id))
            result = _run_summary(run)
            result["profile_snapshot"] = run.profile_snapshot
            result["settings_snapshot"] = run.settings_snapshot
            result["events"] = [
                _event_dict(event)
                for event in session.scalars(
                    select(RunEventRow).where(RunEventRow.run_id == run_id).order_by(RunEventRow.sequence)
                )
            ]
            result["evaluations"] = [
                _evaluation_dict(evaluation)
                for evaluation in session.scalars(
                    select(EvaluationRow)
                    .where(EvaluationRow.run_id == run_id)
                    .order_by(EvaluationRow.attempt, EvaluationRow.created_at)
                )
            ]
            return result

    def active(self) -> dict[str, Any] | None:
        with self.sessions() as session:
            run = session.scalar(
                select(RunRow)
                .where(RunRow.status.in_(("queued", "running")))
                .order_by(RunRow.created_at.desc())
                .limit(1)
            )
            return _run_summary(run) if run else None

    def list(self, *, limit: int = 50, status: str | None = None, trigger: str | None = None) -> list[dict[str, Any]]:
        statement = select(RunRow).order_by(RunRow.created_at.desc()).limit(max(1, min(limit, 100)))
        if status:
            statement = statement.where(RunRow.status == status)
        if trigger:
            statement = statement.where(RunRow.trigger == trigger)
        with self.sessions() as session:
            return [_run_summary(run) for run in session.scalars(statement)]

    def claim_next_queued(self, now: datetime) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            run = session.scalar(
                select(RunRow)
                .where(RunRow.status == "queued")
                .order_by(RunRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return None
            run.status = "running"
            if run.started_at is None:
                run.started_at = now
            session.flush()
            return _run_execution(run)

    def continue_failed(
        self, run_id: UUID, *, settings_snapshot: dict[str, Any], expected_stage: str, now: datetime
    ) -> dict[str, Any]:
        try:
            with self.sessions.begin() as session:
                run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
                if run is None:
                    raise RunNotFound(str(run_id))
                if run.status != "failed" or run.failure_stage != expected_stage:
                    raise RunContinuationConflict("Run is no longer failed at the saved checkpoint stage")
                if run.failure_code == "evaluation_failed_after_retries" or expected_stage == "publish":
                    raise RunContinuationConflict("Exhausted retries or publication failures cannot be continued")
                active = session.scalar(select(RunRow).where(RunRow.status.in_(("queued", "running"))).limit(1))
                if active is not None:
                    raise ActiveRunConflict(active.id)
                _append_event(
                    session,
                    run,
                    "run_resumed",
                    "Failed Run queued to continue with current application settings",
                    now,
                    stage=expected_stage,
                    payload={
                        "failure_code": run.failure_code,
                        "failure_message": run.failure_message,
                        "previous_settings_snapshot": run.settings_snapshot,
                        "settings_snapshot": settings_snapshot,
                        "resume_stage": expected_stage,
                    },
                )
                run.settings_snapshot = settings_snapshot
                run.status = "queued"
                run.current_stage = expected_stage
                run.finished_at = None
                run.failure_stage = run.failure_code = run.failure_message = None
                run.outcome = None
                session.flush()
                return _run_summary(run)
        except IntegrityError as exc:
            active = self.active()
            raise ActiveRunConflict(UUID(active["run_id"]) if active else None) from exc

    def running(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            return [_run_execution(run) for run in session.scalars(select(RunRow).where(RunRow.status == "running"))]

    def stop_queued(self, run_id: UUID, now: datetime) -> dict[str, Any]:
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status != "queued":
                raise RunContinuationConflict("Run is no longer queued; refresh and retry")
            run.status = "failed"
            run.failure_stage = run.current_stage
            run.failure_code = "owner_stopped"
            run.failure_message = "Queued Run stopped by owner"
            run.finished_at = now
            _append_event(
                session,
                run,
                "run_failed",
                run.failure_message,
                now,
                stage=run.current_stage,
                payload={
                    "failure_stage": run.current_stage,
                    "failure_code": run.failure_code,
                    "failure_message": run.failure_message,
                },
            )
            return _run_summary(run)

    def start_stage(self, run_id: UUID, stage: str, now: datetime | None = None) -> None:
        occurred_at = now or datetime.now(UTC)
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status != "running":
                raise RuntimeError(f"Run {run_id} is not running")
            run.current_stage = stage
            _append_event(
                session,
                run,
                "stage_started",
                f"Stage {stage} started",
                occurred_at,
                stage=stage,
                payload={"stage": stage, "attempt": run.attempt},
            )

    def complete(
        self,
        run_id: UUID,
        outcome: str,
        clip_id: str | None,
        now: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status != "running":
                raise RuntimeError(f"Run {run_id} is not running")
            run.status = "completed"
            run.outcome = outcome
            run.finished_at = now
            if clip_id:
                run.approved_clip_id = UUID(clip_id)
            _append_event(
                session,
                run,
                "run_completed",
                "Run completed",
                now,
                payload={"outcome": outcome, "clip_id": clip_id},
            )

    def fail(
        self,
        run_id: UUID,
        stage: str | None,
        code: str,
        message: str,
        now: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status not in {"queued", "running"}:
                return
            run.status = "failed"
            run.failure_stage = stage
            run.failure_code = code
            run.failure_message = message
            run.finished_at = now
            if stage:
                _append_event(
                    session,
                    run,
                    "stage_failed",
                    message,
                    now,
                    stage=stage,
                    level="error",
                    payload={"stage": stage, "error_code": code, "message": message},
                )
            _append_event(
                session,
                run,
                "run_failed",
                message,
                now,
                stage=stage,
                level="error",
                payload={"failure_stage": stage, "failure_code": code, "failure_message": message},
            )

    def apply_retry(
        self,
        run_id: UUID,
        *,
        attempt: int,
        revision_retries_used: int,
        reentry_stage: str | None = None,
        action_types: tuple[str, ...] = (),
        retries_remaining: int = 0,
    ) -> None:
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            if run.status != "running":
                raise RuntimeError(f"Run {run_id} is not running")
            if (run.attempt, run.revision_retries_used) == (attempt, revision_retries_used):
                return
            if attempt != run.attempt + 1 or revision_retries_used != run.revision_retries_used + 1:
                raise ValueError("Retry must advance the Attempt and retry count exactly once")
            run.attempt = attempt
            run.revision_retries_used = revision_retries_used
            _append_event(
                session,
                run,
                "retry_started",
                f"Revision Retry started: Attempt {attempt}",
                datetime.now(UTC),
                stage="plan_retry",
                payload={
                    "attempt": attempt,
                    "reentry_stage": reentry_stage,
                    "action_types": list(action_types),
                    "retries_remaining": retries_remaining,
                },
            )

    def events(self, run_id: UUID, *, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self.sessions() as session:
            if session.get(RunRow, run_id) is None:
                raise RunNotFound(str(run_id))
            events = session.scalars(
                select(RunEventRow)
                .where(RunEventRow.run_id == run_id, RunEventRow.sequence > after_sequence)
                .order_by(RunEventRow.sequence)
            )
            return [_event_dict(event) for event in events]

    def append_event(
        self,
        run_id: UUID,
        event_type: str,
        message: str,
        *,
        stage: str | None = None,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            if run is None:
                raise RunNotFound(str(run_id))
            latest = (
                session.scalar(
                    select(RunEventRow.sequence)
                    .where(RunEventRow.run_id == run_id)
                    .order_by(RunEventRow.sequence.desc())
                    .limit(1)
                )
                or 0
            )
            event = RunEventRow(
                run_id=run_id,
                sequence=latest + 1,
                type=event_type,
                stage=stage,
                attempt=run.attempt,
                level=level,
                message=message,
                payload=payload or {},
                created_at=now,
            )
            session.add(event)
            session.flush()
            return _event_dict(event)


def _run_summary(run: RunRow) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "trigger": run.trigger,
        "status": run.status,
        "outcome": run.outcome,
        "current_stage": run.current_stage,
        "attempt": run.attempt,
        "revision_retries_used": run.revision_retries_used,
        "failure_stage": run.failure_stage,
        "failure_code": run.failure_code,
        "failure_message": run.failure_message,
        "cost_total": str(run.cost_total),
        "created_at": _isoformat(run.created_at),
        "started_at": _isoformat(run.started_at) if run.started_at else None,
        "finished_at": _isoformat(run.finished_at) if run.finished_at else None,
    }


def _run_execution(run: RunRow) -> dict[str, Any]:
    result = _run_summary(run)
    result.update(
        {
            "trigger": run.trigger,
            "manual_url": run.manual_url,
            "settings_snapshot": run.settings_snapshot,
        }
    )
    return result


def _append_event(
    session: Any,
    run: RunRow,
    event_type: str,
    message: str,
    created_at: datetime,
    *,
    stage: str | None = None,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> None:
    latest = (
        session.scalar(
            select(RunEventRow.sequence)
            .where(RunEventRow.run_id == run.id)
            .order_by(RunEventRow.sequence.desc())
            .limit(1)
        )
        or 0
    )
    session.add(
        RunEventRow(
            run_id=run.id,
            sequence=latest + 1,
            type=event_type,
            stage=stage,
            attempt=run.attempt,
            level=level,
            message=message,
            payload=payload or {},
            created_at=created_at,
        )
    )
    session.flush()


def _isoformat(value: datetime) -> str:
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).isoformat()


def _event_dict(event: RunEventRow) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "type": event.type,
        "stage": event.stage,
        "attempt": event.attempt,
        "level": event.level,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


def _evaluation_dict(evaluation: EvaluationRow) -> dict[str, Any]:
    return {
        "id": str(evaluation.id),
        "clip_id": str(evaluation.clip_id) if evaluation.clip_id else None,
        "attempt": evaluation.attempt,
        "layer": evaluation.layer,
        "passed": evaluation.passed,
        "issues": evaluation.issues,
        "warnings": evaluation.warnings,
        "actions": evaluation.actions,
        "metrics": evaluation.metrics,
        "evaluator": evaluation.evaluator,
        "created_at": evaluation.created_at.isoformat(),
    }
