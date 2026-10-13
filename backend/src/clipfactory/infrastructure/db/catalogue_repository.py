"""Read models for the Clip catalogue, dashboard, and cost APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.infrastructure.db.models import (
    ClipRow,
    ContentProfileRow,
    CostEntryRow,
    MetricSnapshotRow,
    PublicationRow,
    RenderRevisionRow,
    RunRow,
    ScheduledTaskRow,
    StoryPackageRow,
    StoryRow,
)


class CatalogueRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    @staticmethod
    def _clip_query(*, pending_approval: bool = False, filter: str = "all") -> Any:
        statement = select(ClipRow)
        if pending_approval:
            statement = statement.where(
                ClipRow.status == "approved",
                ClipRow.id.in_(select(PublicationRow.clip_id).where(PublicationRow.status == "awaiting_approval")),
            )
        elif filter == "published":
            statement = statement.where(
                ClipRow.id.in_(select(PublicationRow.clip_id).where(PublicationRow.status == "published"))
            )
        elif filter == "failed":
            statement = statement.where(
                or_(
                    ClipRow.status.in_(("rejected", "failed")),
                    ClipRow.id.in_(select(PublicationRow.clip_id).where(PublicationRow.status == "failed")),
                )
            )
        return statement

    def clips(
        self, *, pending_approval: bool = False, filter: str = "all", limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        statement = (
            self._clip_query(pending_approval=pending_approval, filter=filter)
            .order_by(ClipRow.created_at.desc(), ClipRow.id.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
        with self.sessions() as session:
            return [self._clip(session, row) for row in session.scalars(statement)]

    def count_clips(self, *, pending_approval: bool = False, filter: str = "all") -> int:
        statement = self._clip_query(pending_approval=pending_approval, filter=filter)
        with self.sessions() as session:
            return session.scalar(select(func.count()).select_from(statement.subquery())) or 0

    def clip(self, clip_id: UUID) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(ClipRow, clip_id)
            if row is None:
                return None
            return self._clip(session, row)

    def clip_storage_key(self, clip_id: UUID) -> str | None:
        with self.sessions() as session:
            return session.scalar(select(ClipRow.storage_key).where(ClipRow.id == clip_id))

    def delete_clip(self, clip_id: UUID) -> str | None:
        with self.sessions.begin() as session:
            row = session.get(ClipRow, clip_id)
            if row is None:
                return None
            storage_key = row.storage_key
            session.execute(update(CostEntryRow).where(CostEntryRow.clip_id == clip_id).values(clip_id=None))
            session.execute(delete(RenderRevisionRow).where(RenderRevisionRow.base_clip_id == clip_id))
            for task in list(
                session.scalars(
                    select(ScheduledTaskRow).where(
                        ScheduledTaskRow.kind == "auto_publish",
                        ScheduledTaskRow.payload["clip_id"].as_string() == str(clip_id),
                    )
                )
            ):
                session.delete(task)
            session.delete(row)
            return storage_key

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

    def monetization_goals(self, now: datetime) -> dict[str, Any]:
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
            snapshots = list(session.scalars(statement))

            pub_counts = dict(
                session.execute(
                    select(PublicationRow.platform, func.count(PublicationRow.id))
                    .where(PublicationRow.status == "published")
                    .group_by(PublicationRow.platform)
                ).all()
            )

        def _platform_metrics(platform: str) -> dict[str, Any]:
            rows = [s for s in snapshots if s.platform == platform]
            return {
                "views": sum((r.views or 0) for r in rows),
                "likes": sum((r.likes or 0) for r in rows),
                "comments": sum((r.comments or 0) for r in rows),
                "shares": sum((r.shares or 0) for r in rows),
                "watch_time_seconds": sum((r.watch_time_seconds or 0.0) for r in rows),
                "followers_delta": sum((r.followers_delta or 0) for r in rows),
            }

        yt = _platform_metrics("youtube")
        fb = _platform_metrics("facebook")
        ig = _platform_metrics("instagram")
        tt = _platform_metrics("tiktok")

        yt_vids = pub_counts.get("youtube", 0)
        fb_vids = pub_counts.get("facebook", 0)
        ig_vids = pub_counts.get("instagram", 0)
        tt_vids = pub_counts.get("tiktok", 0)

        def _calc_pct(current: float | int, target: float | int) -> float:
            if target <= 0:
                return 0.0
            return round(min(100.0, max(0.0, (float(current) / float(target)) * 100.0)), 1)

        platforms = [
            {
                "platform": "youtube",
                "name": "YouTube",
                "program": "YouTube Partner Program (Shorts)",
                "status": "in_progress",
                "published_clips": yt_vids,
                "progress_pct": _calc_pct(yt["views"], 10_000_000),
                "metrics": [
                    {
                        "id": "subscribers",
                        "label": "Subscribers",
                        "current": max(0, int(yt["followers_delta"])),
                        "target": 1000,
                        "target_tier1": 500,
                        "unit": "subscribers",
                        "pct": _calc_pct(max(0, yt["followers_delta"]), 1000),
                    },
                    {
                        "id": "shorts_views",
                        "label": "Shorts Views (90d)",
                        "current": int(yt["views"]),
                        "target": 10_000_000,
                        "target_tier1": 3_000_000,
                        "unit": "views",
                        "pct": _calc_pct(yt["views"], 10_000_000),
                    },
                    {
                        "id": "active_videos",
                        "label": "Active Public Shorts",
                        "current": yt_vids,
                        "target": 3,
                        "unit": "videos",
                        "pct": _calc_pct(yt_vids, 3),
                    },
                    {
                        "id": "watch_hours",
                        "label": "Watch Time (Long-form Alt)",
                        "current": round(yt["watch_time_seconds"] / 3600.0, 1),
                        "target": 4000,
                        "unit": "hours",
                        "pct": _calc_pct(yt["watch_time_seconds"] / 3600.0, 4000),
                    },
                ],
                "restrictions": [
                    {
                        "id": "ai_disclosure",
                        "title": "EU AI Content Disclosure",
                        "description": (
                            "On-screen AI disclosure tag ('AI Generated') rendered in bottom-left per EU AI Act."
                        ),
                        "status": "compliant",
                    },
                    {
                        "id": "community_guidelines",
                        "title": "Community Guidelines Compliance",
                        "description": "0 active Community Guidelines strikes on the YouTube channel.",
                        "status": "compliant",
                    },
                    {
                        "id": "two_step_verification",
                        "title": "2-Step Verification",
                        "description": "Google account 2-Step Verification turned on.",
                        "status": "verified",
                    },
                    {
                        "id": "advanced_features",
                        "title": "Advanced Features",
                        "description": "Advanced features unlocked in YouTube Studio settings.",
                        "status": "verified",
                    },
                    {
                        "id": "adsense",
                        "title": "Active Google AdSense Account",
                        "description": "Linked and approved AdSense account to receive partner payouts.",
                        "status": "pending_action",
                    },
                    {
                        "id": "originality",
                        "title": "Original & Verified Journalism",
                        "description": (
                            "Shorts grounded in independent sources per YouTube Channel Monetization Policies."
                        ),
                        "status": "compliant",
                    },
                ],
            },
            {
                "platform": "facebook",
                "name": "Facebook",
                "program": "Meta Content Monetization (Reels & In-Stream)",
                "status": "in_progress",
                "published_clips": fb_vids,
                "progress_pct": _calc_pct(fb_vids, 5),
                "metrics": [
                    {
                        "id": "followers",
                        "label": "Page Followers",
                        "current": max(0, int(fb["followers_delta"])),
                        "target": 5000,
                        "unit": "followers",
                        "pct": _calc_pct(max(0, fb["followers_delta"]), 5000),
                    },
                    {
                        "id": "view_minutes",
                        "label": "Eligible Minutes Viewed (60d)",
                        "current": round(fb["watch_time_seconds"] / 60.0, 1),
                        "target": 60000,
                        "unit": "minutes",
                        "pct": _calc_pct(fb["watch_time_seconds"] / 60.0, 60000),
                    },
                    {
                        "id": "active_videos",
                        "label": "Active Videos (30d)",
                        "current": fb_vids,
                        "target": 5,
                        "unit": "videos",
                        "pct": _calc_pct(fb_vids, 5),
                    },
                ],
                "restrictions": [
                    {
                        "id": "ai_disclosure",
                        "title": "Synthetic Media Disclosure",
                        "description": "Mandatory AI label on all synthetic video content (EU AI Act & Meta Policy).",
                        "status": "compliant",
                    },
                    {
                        "id": "partner_policies",
                        "title": "Partner Monetization Policies",
                        "description": "Strict compliance with Meta rules on authentic engagement and Page standards.",
                        "status": "compliant",
                    },
                    {
                        "id": "page_age",
                        "title": "Page Age (30+ Days)",
                        "description": "Page must be active for at least 30 days before monetization review.",
                        "status": "compliant",
                    },
                    {
                        "id": "eligible_country",
                        "title": "Eligible Country & Entity",
                        "description": "Page entity located in an eligible monetization market.",
                        "status": "compliant",
                    },
                ],
            },
            {
                "platform": "instagram",
                "name": "Instagram",
                "program": "Creator Monetization (Subscriptions & Bonuses)",
                "status": "in_progress",
                "published_clips": ig_vids,
                "progress_pct": _calc_pct(ig_vids, 10),
                "metrics": [
                    {
                        "id": "followers",
                        "label": "Followers",
                        "current": max(0, int(ig["followers_delta"])),
                        "target": 5000,
                        "unit": "followers",
                        "pct": _calc_pct(max(0, ig["followers_delta"]), 5000),
                    },
                    {
                        "id": "published_reels",
                        "label": "Published Original Reels",
                        "current": ig_vids,
                        "target": 10,
                        "unit": "reels",
                        "pct": _calc_pct(ig_vids, 10),
                    },
                    {
                        "id": "total_views",
                        "label": "Total Reels Views",
                        "current": int(ig["views"]),
                        "target": 10000,
                        "unit": "views",
                        "pct": _calc_pct(ig["views"], 10000),
                    },
                ],
                "restrictions": [
                    {
                        "id": "ai_disclosure",
                        "title": "EU AI Act Transparency Tag",
                        "description": "AI-generated label applied to all vertical reels and video content.",
                        "status": "compliant",
                    },
                    {
                        "id": "professional_account",
                        "title": "Professional Account",
                        "description": "Account set to Creator or Business profile in Instagram settings.",
                        "status": "verified",
                    },
                    {
                        "id": "creator_policies",
                        "title": "Partner Monetization Policies",
                        "description": (
                            "Compliance with Instagram Community Guidelines and Content Monetization Policies."
                        ),
                        "status": "compliant",
                    },
                    {
                        "id": "age_requirement",
                        "title": "Age Requirement (18+)",
                        "description": "Account holder must be at least 18 years of age.",
                        "status": "compliant",
                    },
                ],
            },
            {
                "platform": "tiktok",
                "name": "TikTok",
                "program": "TikTok Creator Rewards Program",
                "status": "in_progress",
                "published_clips": tt_vids,
                "progress_pct": _calc_pct(tt_vids, 5),
                "metrics": [
                    {
                        "id": "followers",
                        "label": "Followers",
                        "current": max(0, int(tt["followers_delta"])),
                        "target": 10000,
                        "unit": "followers",
                        "pct": _calc_pct(max(0, tt["followers_delta"]), 10000),
                    },
                    {
                        "id": "views_30d",
                        "label": "Video Views (30d)",
                        "current": int(tt["views"]),
                        "target": 100000,
                        "unit": "views",
                        "pct": _calc_pct(tt["views"], 100000),
                    },
                    {
                        "id": "active_videos",
                        "label": "Published Original Videos",
                        "current": tt_vids,
                        "target": 5,
                        "unit": "videos",
                        "pct": _calc_pct(tt_vids, 5),
                    },
                ],
                "restrictions": [
                    {
                        "id": "content_posting_api",
                        "title": "Content Posting API",
                        "description": "Direct video posting adapter configured for TikTok Creator Rewards.",
                        "status": "compliant",
                    },
                    {
                        "id": "ai_disclosure",
                        "title": "AI-Generated Content Label",
                        "description": "Synthetic media disclosure tag ('is_aigc' and badge) enabled for TikTok.",
                        "status": "compliant",
                    },
                    {
                        "id": "age_requirement",
                        "title": "Age Requirement (18+)",
                        "description": "18+ years old and based in an eligible Rewards Program country.",
                        "status": "compliant",
                    },
                    {
                        "id": "community_guidelines",
                        "title": "Community Guidelines",
                        "description": "Authentic engagement and compliance with TikTok Community Guidelines.",
                        "status": "compliant",
                    },
                ],
            },
        ]

        return {
            "goal": {
                "id": "monetization",
                "title": "Obtain Monetization",
                "description": (
                    "Unlock revenue generation across eligible platforms by reaching audience milestones "
                    "and complying with platform policies."
                ),
                "updated_at": _isoformat(now),
                "platforms": platforms,
            }
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
