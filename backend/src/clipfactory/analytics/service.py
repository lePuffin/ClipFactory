"""Metric collection and deterministic estimated-revenue calculation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import Platform
from clipfactory.ports.publishing import Publisher


class MetricStore(Protocol):
    def metric_context(self, publication_id: UUID) -> dict[str, Any]: ...

    def save_metric(
        self,
        publication_id: UUID,
        offset_label: str,
        scheduled_for: Any,
        captured_at: Any,
        values: dict[str, Any],
    ) -> None: ...


class MetricCollector:
    def __init__(self, store: MetricStore, publishers: Mapping[Platform, Publisher]) -> None:
        self._store = store
        self._publishers = dict(publishers)

    async def collect(
        self,
        publication_id: UUID,
        offset_label: str,
        scheduled_for: Any,
        captured_at: Any,
    ) -> None:
        context = await asyncio.to_thread(self._store.metric_context, publication_id)
        platform = Platform(context["platform"])
        publisher = self._publishers.get(platform)
        if publisher is None or not publisher.is_configured():
            raise RuntimeError(f"{platform.value} metrics provider is not configured")
        metrics = await publisher.fetch_metrics(context["platform_post_id"])
        analytics = context["analytics"]
        estimate = metrics.estimated_revenue
        basis = "platform_reported_estimate" if estimate is not None else None
        rpm_used: Decimal | None = None
        if estimate is None and metrics.views is not None:
            raw_rpm = analytics.get("rpm_by_platform", {}).get(platform.value)
            if raw_rpm is not None:
                rpm_used = Decimal(str(raw_rpm))
                estimate = Decimal(metrics.views) / Decimal(1000) * rpm_used
                basis = "rpm_estimate"
        await asyncio.to_thread(
            self._store.save_metric,
            publication_id,
            offset_label,
            scheduled_for,
            captured_at,
            {
                "platform": platform.value,
                "views": metrics.views,
                "likes": metrics.likes,
                "comments": metrics.comments,
                "shares": metrics.shares,
                "watch_time_seconds": metrics.watch_time_seconds,
                "average_retention_ratio": metrics.average_retention_ratio,
                "followers_delta": metrics.followers_delta,
                "estimated_revenue": estimate,
                "revenue_currency": analytics.get("currency", "USD") if estimate is not None else None,
                "revenue_basis": basis,
                "raw": {"rpm_used": str(rpm_used) if rpm_used is not None else None},
            },
        )
