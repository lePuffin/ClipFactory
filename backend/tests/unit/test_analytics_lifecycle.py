from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from clipfactory.analytics.service import MetricCollector
from clipfactory.domain.models import Platform
from clipfactory.ports.publishing import PlatformMetrics
from clipfactory.workflow.lifecycle_scheduler import LifecycleScheduler


class MetricStore:
    def __init__(self, metrics_settings: dict[str, Any]) -> None:
        self.settings = metrics_settings
        self.saved: dict[str, Any] | None = None

    def metric_context(self, publication_id: UUID) -> dict[str, Any]:
        del publication_id
        return {
            "platform": "youtube",
            "platform_post_id": "post-1",
            "analytics": self.settings,
        }

    def save_metric(
        self,
        publication_id: UUID,
        offset_label: str,
        scheduled_for: Any,
        captured_at: Any,
        values: dict[str, Any],
    ) -> None:
        self.saved = {
            "publication_id": publication_id,
            "offset_label": offset_label,
            "scheduled_for": scheduled_for,
            "captured_at": captured_at,
            **values,
        }


class MetricsPublisher:
    platform = Platform.YOUTUBE
    name = "youtube"

    def __init__(self, metrics: PlatformMetrics) -> None:
        self.metrics = metrics

    def is_configured(self) -> bool:
        return True

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        assert platform_post_id == "post-1"
        return self.metrics

    async def publish(self, request: Any, clip_file: Any) -> Any:
        raise AssertionError("publish is not used")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-500")
@pytest.mark.req("CF-REQ-504")
@pytest.mark.asyncio
async def test_metric_collection_persists_values_and_rpm_revenue() -> None:
    store = MetricStore({"rpm_by_platform": {"youtube": 0.5}, "currency": "USD"})
    collector = MetricCollector(
        store,
        {Platform.YOUTUBE: MetricsPublisher(PlatformMetrics(views=12_000, likes=30, shares=None))},
    )
    scheduled = datetime(2026, 10, 1, 11, tzinfo=UTC)
    captured = datetime(2026, 10, 1, 16, tzinfo=UTC)

    await collector.collect(uuid4(), "1h", scheduled, captured)

    assert store.saved is not None
    assert store.saved["views"] == 12_000
    assert store.saved["shares"] is None
    assert store.saved["estimated_revenue"] == Decimal("6.0")
    assert store.saved["revenue_basis"] == "rpm_estimate"
    assert store.saved["captured_at"] == captured


@pytest.mark.unit
@pytest.mark.req("CF-REQ-502")
@pytest.mark.req("CF-REQ-504")
@pytest.mark.asyncio
async def test_metric_collection_keeps_unavailable_values_null() -> None:
    store = MetricStore({"rpm_by_platform": {}, "currency": "USD"})
    collector = MetricCollector(
        store,
        {Platform.YOUTUBE: MetricsPublisher(PlatformMetrics(views=None, shares=None))},
    )

    await collector.collect(uuid4(), "1h", datetime.now(UTC), datetime.now(UTC))

    assert store.saved is not None
    assert store.saved["shares"] is None
    assert store.saved["estimated_revenue"] is None
    assert store.saved["revenue_basis"] is None


class Tasks:
    def __init__(self, task: dict[str, Any]) -> None:
        self.task = task
        self.done: list[UUID] = []
        self.failures: list[tuple[int, str]] = []

    def claim_task(self, now: datetime) -> dict[str, Any] | None:
        del now
        task, self.task = self.task, None  # type: ignore[assignment]
        return task

    def task_done(self, task_id: UUID, now: datetime) -> None:
        del now
        self.done.append(task_id)

    def task_failed(self, task_id: UUID, now: datetime, message: str, attempts: int) -> None:
        del task_id, now
        self.failures.append((attempts, message))


class RecordingMetrics:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.captured_at: datetime | None = None

    async def collect(
        self, publication_id: UUID, offset_label: str, scheduled_for: datetime, captured_at: datetime
    ) -> None:
        del publication_id, offset_label, scheduled_for
        self.captured_at = captured_at
        if self.fail:
            raise RuntimeError("metrics unavailable")


class Approval:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    async def approve(self, clip_id: UUID, *, approved_by: str) -> dict[str, Any]:
        self.calls.append((clip_id, approved_by))
        return {}


def metric_task(*, attempts: int = 1) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "kind": "metric_snapshot",
        "payload": {"publication_id": str(uuid4()), "offset_label": "1h"},
        "due_at": datetime(2026, 10, 1, 11, tzinfo=UTC),
        "attempts": attempts,
    }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-503")
@pytest.mark.asyncio
async def test_late_metric_task_uses_current_capture_time() -> None:
    now = datetime(2026, 10, 1, 16, tzinfo=UTC)
    tasks = Tasks(metric_task())
    metrics = RecordingMetrics()

    await LifecycleScheduler(tasks, metrics, Approval(), clock=lambda: now).run_once()

    assert metrics.captured_at == now
    assert len(tasks.done) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-503")
@pytest.mark.asyncio
async def test_failed_metric_task_records_attempt_for_bounded_retry() -> None:
    tasks = Tasks(metric_task(attempts=3))

    await LifecycleScheduler(
        tasks,
        RecordingMetrics(fail=True),
        Approval(),
        clock=lambda: datetime(2026, 10, 1, 16, tzinfo=UTC),
    ).run_once()

    assert tasks.failures == [(3, "metrics unavailable")]
    assert tasks.done == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-460")
@pytest.mark.asyncio
async def test_due_auto_publish_task_records_timeout_approval_actor() -> None:
    clip_id = uuid4()
    task = {
        "id": str(uuid4()),
        "kind": "auto_publish",
        "payload": {"clip_id": str(clip_id)},
        "due_at": datetime(2026, 10, 1, 10, 10, tzinfo=UTC),
        "attempts": 1,
    }
    tasks = Tasks(task)
    approvals = Approval()

    await LifecycleScheduler(
        tasks,
        RecordingMetrics(),
        approvals,
        clock=lambda: datetime(2026, 10, 1, 10, 10, tzinfo=UTC),
    ).run_once()

    assert approvals.calls == [(clip_id, "auto_timeout")]
    assert len(tasks.done) == 1
