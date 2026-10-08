"""Transactional persistence for publication, approval and analytics."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from clipfactory.infrastructure.db.models import (
    ClipRow,
    MetricSnapshotRow,
    PublicationRow,
    RunRow,
    ScheduledTaskRow,
)


class PublishingRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def publishing_clip_storage_key(self, clip_id: UUID) -> str | None:
        statement = (
            select(ClipRow.storage_key)
            .join(PublicationRow, PublicationRow.clip_id == ClipRow.id)
            .where(ClipRow.id == clip_id, PublicationRow.status == "publishing")
            .limit(1)
        )
        with self.sessions() as session:
            return session.scalar(statement)

    def context(self, run_id: UUID, clip_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            run = session.get(RunRow, run_id)
            clip = session.get(ClipRow, clip_id)
            if run is None or clip is None or clip.run_id != run_id:
                raise LookupError(str(clip_id))
            return {
                "clip_status": clip.status,
                "storage_key": clip.storage_key,
                "social_metadata": clip.metadata_json["social_metadata"],
                "platforms": run.profile_snapshot.get("platforms", []),
                "settings": run.settings_snapshot,
            }

    def prepare(
        self,
        clip_id: UUID,
        platform: str,
        mode: str,
        request: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            row = session.scalar(
                select(PublicationRow)
                .where(PublicationRow.clip_id == clip_id, PublicationRow.platform == platform)
                .with_for_update()
            )
            if row is None:
                row = PublicationRow(
                    id=uuid4(),
                    clip_id=clip_id,
                    platform=platform,
                    status=status,
                    mode=mode,
                    request=_json_request(request),
                    call_retries=0,
                )
                session.add(row)
                session.flush()
            return _publication(row)

    def mark_publishing(self, publication_id: UUID) -> None:
        self._transition(publication_id, status="publishing")

    def mark_published(self, publication_id: UUID, result: dict[str, Any], published_at: datetime) -> None:
        self._transition(
            publication_id,
            status="published",
            platform_post_id=result["platform_post_id"],
            platform_url=result["platform_url"],
            published_at=published_at,
            request_update={"disclosure_note": result.get("disclosure_note")},
        )

    def mark_failed(self, publication_id: UUID, code: str, message: str) -> None:
        self._transition(publication_id, status="failed", error_code=code, error_message=message)

    def schedule_metrics(
        self,
        publication_id: UUID,
        published_at: datetime,
        offsets: list[str],
        now: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            for label in offsets:
                exists = session.scalar(
                    select(ScheduledTaskRow.id).where(
                        ScheduledTaskRow.kind == "metric_snapshot",
                        ScheduledTaskRow.payload["publication_id"].as_string() == str(publication_id),
                        ScheduledTaskRow.payload["offset_label"].as_string() == label,
                    )
                )
                if exists is None:
                    session.add(
                        ScheduledTaskRow(
                            kind="metric_snapshot",
                            due_at=published_at + _offset(label),
                            payload={"publication_id": str(publication_id), "offset_label": label},
                            status="pending",
                            attempts=0,
                            created_at=now,
                            updated_at=now,
                        )
                    )

    def schedule_auto_publish(self, run_id: UUID, clip_id: UUID, due_at: datetime, now: datetime) -> None:
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(ScheduledTaskRow.id).where(
                    ScheduledTaskRow.kind == "auto_publish",
                    ScheduledTaskRow.payload["clip_id"].as_string() == str(clip_id),
                    ScheduledTaskRow.status == "pending",
                )
            )
            if existing is None:
                session.add(
                    ScheduledTaskRow(
                        kind="auto_publish",
                        due_at=due_at,
                        payload={"run_id": str(run_id), "clip_id": str(clip_id)},
                        status="pending",
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def resolve_approval(self, clip_id: UUID, decision: str, now: datetime) -> dict[str, Any]:
        with self.sessions.begin() as session:
            clip = session.get(ClipRow, clip_id)
            if clip is None:
                raise LookupError(str(clip_id))
            rows = list(
                session.scalars(select(PublicationRow).where(PublicationRow.clip_id == clip_id).with_for_update())
            )
            pending = [row for row in rows if row.status == "awaiting_approval"]
            run = session.get(RunRow, clip.run_id)
            if run is None:
                raise LookupError(str(clip.run_id))
            if decision == "reject":
                for row in pending:
                    row.status = "rejected"
                    row.request = {**row.request, "approved_by": "owner_rejected"}
                run.outcome = "not_published"
            elif decision != "approve":
                raise ValueError("decision must be approve or reject")
            else:
                for row in pending:
                    row.request = {**row.request, "approved_by": "owner"}
            for task in session.scalars(
                select(ScheduledTaskRow).where(
                    ScheduledTaskRow.kind == "auto_publish",
                    ScheduledTaskRow.payload["clip_id"].as_string() == str(clip_id),
                    ScheduledTaskRow.status == "pending",
                )
            ):
                task.status = "skipped"
                task.updated_at = now
            return {
                "run_id": str(run.id),
                "clip_id": str(clip_id),
                "decision": decision,
                "already_resolved": not pending,
            }

    def update_run_outcome(self, run_id: UUID, outcome: str) -> None:
        with self.sessions.begin() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise LookupError(str(run_id))
            run.outcome = outcome

    def claim_task(self, now: datetime) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            row = session.scalar(
                select(ScheduledTaskRow)
                .where(
                    ScheduledTaskRow.kind.in_(("metric_snapshot", "auto_publish")),
                    ScheduledTaskRow.status == "pending",
                    ScheduledTaskRow.due_at <= now,
                )
                .order_by(ScheduledTaskRow.due_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
            row.attempts += 1
            row.updated_at = now
            return {
                "id": str(row.id),
                "kind": row.kind,
                "payload": row.payload,
                "due_at": row.due_at,
                "attempts": row.attempts,
            }

    def task_done(self, task_id: UUID, now: datetime) -> None:
        self._task_status(task_id, "done", now, None)

    def task_failed(self, task_id: UUID, now: datetime, message: str, attempts: int) -> None:
        self._task_status(task_id, "pending" if attempts < 3 else "failed", now, message)

    def metric_context(self, publication_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(PublicationRow, publication_id)
            if row is None or row.status != "published" or row.platform_post_id is None:
                raise LookupError(str(publication_id))
            clip = session.get(ClipRow, row.clip_id)
            run = session.get(RunRow, clip.run_id) if clip else None
            if run is None:
                raise LookupError(str(publication_id))
            return {
                "platform": row.platform,
                "platform_post_id": row.platform_post_id,
                "analytics": run.settings_snapshot.get("analytics", {}),
            }

    def save_metric(
        self,
        publication_id: UUID,
        offset_label: str,
        scheduled_for: datetime,
        captured_at: datetime,
        values: dict[str, Any],
    ) -> None:
        with self.sessions.begin() as session:
            exists = session.scalar(
                select(MetricSnapshotRow.id).where(
                    MetricSnapshotRow.publication_id == publication_id,
                    MetricSnapshotRow.offset_label == offset_label,
                )
            )
            if exists is not None:
                return
            session.add(
                MetricSnapshotRow(
                    publication_id=publication_id,
                    platform=values.pop("platform"),
                    offset_label=offset_label,
                    scheduled_for=scheduled_for,
                    captured_at=captured_at,
                    raw=values.pop("raw", {}),
                    **values,
                )
            )

    def snapshots(self, publication_id: UUID) -> list[dict[str, Any]]:
        with self.sessions() as session:
            return [
                _snapshot(row)
                for row in session.scalars(
                    select(MetricSnapshotRow)
                    .where(MetricSnapshotRow.publication_id == publication_id)
                    .order_by(MetricSnapshotRow.captured_at)
                )
            ]

    def analytics_summary(self, since: datetime | None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            latest = (
                select(
                    MetricSnapshotRow.publication_id,
                    func.max(MetricSnapshotRow.captured_at).label("captured_at"),
                )
                .group_by(MetricSnapshotRow.publication_id)
                .subquery()
            )
            statement = select(MetricSnapshotRow).join(
                latest,
                (MetricSnapshotRow.publication_id == latest.c.publication_id)
                & (MetricSnapshotRow.captured_at == latest.c.captured_at),
            )
            if since is not None:
                statement = statement.where(MetricSnapshotRow.captured_at >= since)
            rows = list(session.scalars(statement))
            platforms = sorted({row.platform for row in rows})
            return [_aggregate(rows, platform) for platform in platforms] + [_aggregate(rows, None)]

    def _transition(self, publication_id: UUID, **values: Any) -> None:
        request_update = values.pop("request_update", None)
        with self.sessions.begin() as session:
            row = session.get(PublicationRow, publication_id)
            if row is None:
                raise LookupError(str(publication_id))
            for key, value in values.items():
                setattr(row, key, value)
            if request_update:
                row.request = {**row.request, **request_update}

    def _task_status(self, task_id: UUID, status: str, now: datetime, message: str | None) -> None:
        with self.sessions.begin() as session:
            row = session.get(ScheduledTaskRow, task_id)
            if row is None:
                raise LookupError(str(task_id))
            row.status = status
            row.updated_at = now
            row.last_error = message


def _offset(label: str) -> timedelta:
    unit = label[-1]
    amount = int(label[:-1])
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    raise ValueError(f"Unsupported analytics offset: {label}")


def _json_request(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(item) if isinstance(item, UUID) else list(item) if isinstance(item, tuple) else item
        for key, item in value.items()
    }


def _publication(row: PublicationRow) -> dict[str, Any]:
    return {"id": str(row.id), "status": row.status, "platform": row.platform}


def _snapshot(row: MetricSnapshotRow) -> dict[str, Any]:
    return {
        column: getattr(row, column)
        for column in (
            "offset_label",
            "scheduled_for",
            "captured_at",
            "platform",
            "views",
            "likes",
            "comments",
            "shares",
            "watch_time_seconds",
            "average_retention_ratio",
            "followers_delta",
            "estimated_revenue",
            "revenue_currency",
            "revenue_basis",
        )
    }


def _aggregate(rows: list[MetricSnapshotRow], platform: str | None) -> dict[str, Any]:
    selected = [row for row in rows if platform is None or row.platform == platform]
    return {
        "platform": platform or "overall",
        **{
            name: sum((getattr(row, name) or 0) for row in selected)
            for name in ("views", "likes", "comments", "shares", "watch_time_seconds")
        },
        "estimated_revenue": str(sum((row.estimated_revenue or Decimal("0")) for row in selected)),
        "revenue_by_basis": {
            basis: str(sum((row.estimated_revenue or Decimal("0")) for row in selected if row.revenue_basis == basis))
            for basis in sorted({row.revenue_basis for row in selected if row.revenue_basis})
        },
    }
