"""Read models for the Clip catalogue, dashboard, and cost APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.infrastructure.db.models import (
    ClipRow,
    ContentProfileRow,
    CostEntryRow,
    MetricSnapshotRow,
    PublicationRow,
    RunRow,
    ScheduledTaskRow,
    StoryPackageRow,
    StoryRow,
)


class CatalogueRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def clips(self, *, pending_approval: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(ClipRow).where(ClipRow.status == "approved")
        if pending_approval:
            statement = statement.where(
                ClipRow.id.in_(select(PublicationRow.clip_id).where(PublicationRow.status == "awaiting_approval"))
            )
        statement = statement.order_by(ClipRow.created_at.desc()).limit(max(1, min(limit, 100)))
        with self.sessions() as session:
            return [self._clip(session, row) for row in session.scalars(statement)]

    def clip(self, clip_id: UUID) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(ClipRow, clip_id)
            if row is None or row.status != "approved":
                return None
            return self._clip(session, row)

    def clip_storage_key(self, clip_id: UUID) -> str | None:
        with self.sessions() as session:
            return session.scalar(
                select(ClipRow.storage_key).where(ClipRow.id == clip_id, ClipRow.status == "approved")
            )

    def dashboard_summary(self, since: datetime) -> dict[str, Any]:
        with self.sessions() as session:
            clips_approved = (
                session.scalar(
                    select(func.count(ClipRow.id)).where(ClipRow.status == "approved", ClipRow.created_at >= since)
                )
                or 0
            )
            publications = list(
                session.scalars(
                    select(PublicationRow).where(
                        PublicationRow.status == "published",
                        PublicationRow.published_at >= since,
                    )
                )
            )
            snapshots = [
                snapshot
                for publication in publications
                if (
                    snapshot := session.scalar(
                        select(MetricSnapshotRow)
                        .where(MetricSnapshotRow.publication_id == publication.id)
                        .order_by(MetricSnapshotRow.captured_at.desc())
                        .limit(1)
                    )
                )
                is not None
            ]
            next_task = session.scalar(
                select(ScheduledTaskRow)
                .where(
                    ScheduledTaskRow.kind == "daily_run",
                    ScheduledTaskRow.status == "pending",
                )
                .order_by(ScheduledTaskRow.due_at)
                .limit(1)
            )
            currencies = {row.revenue_currency for row in snapshots if row.revenue_currency}
            return {
                "clips_approved": clips_approved,
                "publications": len(publications),
                "views": sum((row.views or 0) for row in snapshots),
                "estimated_revenue": _money(
                    sum(
                        (row.estimated_revenue or Decimal("0") for row in snapshots),
                        Decimal("0"),
                    )
                ),
                "estimated_revenue_currency": next(iter(currencies)) if len(currencies) == 1 else None,
                "next_scheduled_run_at": _isoformat(next_task.due_at) if next_task else None,
            }

    def budget_summary(self, now: datetime, budget: dict[str, Any]) -> dict[str, str]:
        timezone = ZoneInfo(self._profile_timezone())
        local_now = _aware(now).astimezone(timezone)
        month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        with self.sessions() as session:
            spent = session.scalar(
                select(func.coalesce(func.sum(CostEntryRow.amount), 0)).where(
                    CostEntryRow.created_at >= month_start,
                    CostEntryRow.created_at <= _aware(now),
                )
            )
        monthly_limit = Decimal(str(budget["max_cost_per_month"]))
        spent_decimal = Decimal(str(spent))
        return {
            "currency": str(budget["currency"]),
            "month_to_date_spend": _money(spent_decimal),
            "monthly_limit": _money(monthly_limit),
            "monthly_remaining": _money(max(Decimal("0"), monthly_limit - spent_decimal)),
            "per_clip_limit": _money(Decimal(str(budget["max_cost_per_clip"]))),
        }

    def run_costs(self, run_id: UUID) -> dict[str, Any] | None:
        with self.sessions() as session:
            if session.get(RunRow, run_id) is None:
                return None
            rows = list(
                session.scalars(
                    select(CostEntryRow)
                    .where(CostEntryRow.run_id == run_id)
                    .order_by(CostEntryRow.created_at, CostEntryRow.id)
                )
            )
            currencies = {row.currency for row in rows}
            return {
                "run_id": str(run_id),
                "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                "total": _money(sum((row.amount for row in rows), Decimal("0"))),
                "entries": [
                    {
                        "id": str(row.id),
                        "clip_id": str(row.clip_id) if row.clip_id else None,
                        "provider": row.provider,
                        "operation": row.operation,
                        "quantity": str(row.quantity),
                        "amount": _money(row.amount),
                        "currency": row.currency,
                        "basis": row.basis,
                        "created_at": _isoformat(row.created_at),
                    }
                    for row in rows
                ],
            }

    def _clip(self, session: Session, row: ClipRow) -> dict[str, Any]:
        package = session.get(StoryPackageRow, row.story_package_id)
        story = session.get(StoryRow, package.story_id) if package else None
        run = session.get(RunRow, row.run_id)
        publications = list(
            session.scalars(
                select(PublicationRow).where(PublicationRow.clip_id == row.id).order_by(PublicationRow.platform)
            )
        )
        auto_publish = session.scalar(
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.kind == "auto_publish",
                ScheduledTaskRow.payload["clip_id"].as_string() == str(row.id),
                ScheduledTaskRow.status == "pending",
            )
            .order_by(ScheduledTaskRow.due_at)
            .limit(1)
        )
        return {
            "id": str(row.id),
            "run_id": str(row.run_id),
            "status": row.status,
            "story_title": story.title if story else None,
            "created_at": _isoformat(row.created_at),
            "cost_total": _money(run.cost_total) if run else _money(Decimal("0")),
            "social_metadata": row.metadata_json.get("social_metadata"),
            "preview": {
                "media_url": f"/api/clips/{row.id}/media",
                "mime_type": "video/mp4",
                "duration_seconds": row.duration_seconds,
                "width": row.width,
                "height": row.height,
                "fps": row.fps,
                "size_bytes": row.size_bytes,
            },
            "auto_publish_due_at": _isoformat(auto_publish.due_at) if auto_publish else None,
            "publications": [self._publication(session, publication) for publication in publications],
        }

    @staticmethod
    def _publication(session: Session, row: PublicationRow) -> dict[str, Any]:
        latest = session.scalar(
            select(MetricSnapshotRow)
            .where(MetricSnapshotRow.publication_id == row.id)
            .order_by(MetricSnapshotRow.captured_at.desc())
            .limit(1)
        )
        return {
            "id": str(row.id),
            "platform": row.platform,
            "status": row.status,
            "mode": row.mode,
            "platform_post_id": row.platform_post_id,
            "platform_url": row.platform_url,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "approved_by": row.request.get("approved_by"),
            "published_at": _isoformat(row.published_at) if row.published_at else None,
            "latest_metrics": _snapshot(latest) if latest else None,
        }

    def _profile_timezone(self) -> str:
        with self.sessions() as session:
            value = session.scalar(select(ContentProfileRow.value).where(ContentProfileRow.is_active.is_(True))) or {}
        return str(value.get("schedule", {}).get("timezone", "UTC"))


def _snapshot(row: MetricSnapshotRow) -> dict[str, Any]:
    snapshot = {
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
    snapshot["estimated_revenue"] = _money(row.estimated_revenue) if row.estimated_revenue is not None else None
    return snapshot


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _isoformat(value: datetime) -> str:
    return _aware(value).isoformat()


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))
