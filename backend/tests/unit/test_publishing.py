from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from clipfactory.domain.models import Platform
from clipfactory.infrastructure.providers.publishing.retrying import RetryingPublisher
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.publishing import PlatformMetrics, PublicationRequest, PublicationResult
from clipfactory.publishing.service import PublishService


class Store:
    def __init__(self, *, status: str = "approved", mode: str = "live", platforms: list[str] | None = None) -> None:
        self.clip_id = uuid4()
        self.publication_id = uuid4()
        self.context_value = {
            "clip_status": status,
            "storage_key": "clips/final.mp4",
            "platforms": platforms or ["youtube"],
            "settings": {
                "publishing": {"mode": mode, "approval_required": False},
                "analytics": {"snapshot_offsets": ["1h", "6h"]},
            },
            "social_metadata": {
                "title": "Title",
                "description": "Description",
                "hashtags": ["news"],
                "source_attributions": [],
                "asset_attributions": [],
                "contains_synthetic_media": True,
                "synthetic_voice": False,
            },
        }
        self.prepared: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []
        self.published: list[dict[str, Any]] = []
        self.metric_offsets: list[str] = []
        self.auto_publish_due: datetime | None = None

    def context(self, run_id: UUID, clip_id: UUID) -> dict[str, Any]:
        del run_id, clip_id
        return self.context_value

    def prepare(self, clip_id: UUID, platform: str, mode: str, request: dict[str, Any], status: str) -> dict[str, Any]:
        del clip_id, mode, request
        self.prepared.append((platform, status))
        return {"id": str(self.publication_id), "status": status, "platform": platform}

    def mark_publishing(self, publication_id: UUID) -> None:
        assert publication_id == self.publication_id

    def mark_published(self, publication_id: UUID, result: dict[str, Any], published_at: datetime) -> None:
        del publication_id, published_at
        self.published.append(result)

    def mark_failed(self, publication_id: UUID, code: str, message: str) -> None:
        del publication_id
        self.failed.append((code, message))

    def schedule_metrics(self, publication_id: UUID, published_at: datetime, offsets: list[str], now: datetime) -> None:
        del publication_id, published_at, now
        self.metric_offsets = offsets

    def schedule_auto_publish(self, run_id: UUID, clip_id: UUID, due_at: datetime, now: datetime) -> None:
        del run_id, clip_id, now
        self.auto_publish_due = due_at


class Storage:
    def local_path(self, key: str) -> Path:
        return Path(key)


class Publisher:
    platform = Platform.YOUTUBE
    name = "fake-youtube"

    def __init__(
        self,
        outcomes: list[PublicationResult | ProviderError] | None = None,
        *,
        configured: bool = True,
    ) -> None:
        self.outcomes = outcomes or [PublicationResult("post-1", "https://example/post-1")]
        self.configured = configured
        self.calls = 0

    def is_configured(self) -> bool:
        return self.configured

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del request, clip_file
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        del platform_post_id
        return PlatformMetrics(views=10)


NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_retrying_publisher_retries_only_transient_failures() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    transient = ProviderError("publisher_unreachable", "offline", transient=True)
    publisher = Publisher([transient, transient, PublicationResult("post-1", "https://example/post-1")])
    retrying = RetryingPublisher(publisher, sleep=sleep)

    result = await retrying.publish(_request(), Path("clip.mp4"))

    assert result.platform_post_id == "post-1"
    assert publisher.calls == 3
    assert delays == [2.0, 4.0]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-456")
@pytest.mark.asyncio
async def test_retrying_publisher_does_not_retry_permanent_failure() -> None:
    publisher = Publisher([ProviderError("auth_failed", "bad token", transient=False)])
    retrying = RetryingPublisher(publisher)

    with pytest.raises(ProviderError, match="bad token"):
        await retrying.publish(_request(), Path("clip.mp4"))

    assert publisher.calls == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-450")
@pytest.mark.asyncio
async def test_publish_service_refuses_non_approved_clip() -> None:
    store = Store(status="rejected")
    service = PublishService(store, Storage(), {}, clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="approved"):
        await service.execute(uuid4(), store.clip_id)

    assert store.prepared == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-452")
@pytest.mark.asyncio
async def test_dry_run_persists_without_calling_publisher() -> None:
    store = Store(mode="dry_run")
    publisher = Publisher()
    result = await PublishService(store, Storage(), {Platform.YOUTUBE: publisher}, clock=lambda: NOW).execute(
        uuid4(), store.clip_id
    )

    assert result["outcome"] == "not_published"
    assert store.prepared == [("youtube", "dry_run")]
    assert publisher.calls == 0


@pytest.mark.unit
@pytest.mark.req("CF-REQ-457")
@pytest.mark.asyncio
async def test_live_unconfigured_publisher_is_failed_without_call() -> None:
    store = Store()
    publisher = Publisher(configured=False)
    result = await PublishService(store, Storage(), {Platform.YOUTUBE: publisher}, clock=lambda: NOW).execute(
        uuid4(), store.clip_id
    )

    assert result["outcome"] == "not_published"
    assert store.failed[0][0] == "not_configured"
    assert publisher.calls == 0


@pytest.mark.unit
@pytest.mark.req("CF-REQ-458")
@pytest.mark.req("CF-REQ-454")
@pytest.mark.asyncio
async def test_successful_publication_schedules_configured_metrics() -> None:
    store = Store()
    publisher = Publisher()
    result = await PublishService(store, Storage(), {Platform.YOUTUBE: publisher}, clock=lambda: NOW).execute(
        uuid4(), store.clip_id
    )

    assert result["outcome"] == "published"
    assert store.metric_offsets == ["1h", "6h"]
    assert store.published[0]["platform_post_id"] == "post-1"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-459")
@pytest.mark.asyncio
async def test_approval_gate_holds_without_timeout_or_platform_call() -> None:
    store = Store()
    store.context_value["settings"]["publishing"].update({"approval_required": True, "auto_publish_after_minutes": 10})
    publisher = Publisher()
    result = await PublishService(store, Storage(), {Platform.YOUTUBE: publisher}, clock=lambda: NOW).execute(
        uuid4(), store.clip_id
    )

    assert result["outcome"] == "awaiting_approval"
    assert store.prepared == [("youtube", "awaiting_approval")]
    assert store.auto_publish_due is None
    assert publisher.calls == 0


def _request() -> PublicationRequest:
    return PublicationRequest(
        clip_id=uuid4(),
        title="Title",
        description="Description",
        hashtags=(),
        source_attributions=(),
        asset_attributions=(),
        contains_synthetic_media=False,
        synthetic_voice=False,
    )
