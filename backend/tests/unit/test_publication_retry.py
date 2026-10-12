from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from clipfactory.domain.models import Platform
from clipfactory.infrastructure.public_media import PublicMediaStaging
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.publishing import PlatformMetrics, PublicationRequest, PublicationResult
from clipfactory.publishing.approval import ApprovalService, PublicationRetryConflict
from clipfactory.publishing.service import PublishService

NOW = datetime(2026, 10, 11, 10, tzinfo=UTC)
CLIP_ID = UUID("4743e208-5040-4762-91f3-7e5df4544ac9")


class MultiStore:
    """In-memory Publication store with one row per platform."""

    def __init__(self, statuses: dict[str, str], *, clip_status: str = "approved") -> None:
        self.run_id = uuid4()
        self.clip_status = clip_status
        self.rows = {platform: {"id": str(uuid4()), "status": status} for platform, status in statuses.items()}
        self.outcome: str | None = None

    def _row(self, publication_id: UUID) -> dict[str, Any]:
        return next(row for row in self.rows.values() if row["id"] == str(publication_id))

    def context(self, run_id: UUID, clip_id: UUID) -> dict[str, Any]:
        del run_id, clip_id
        return {
            "clip_status": self.clip_status,
            "storage_key": "clips/final.mp4",
            "platforms": list(self.rows),
            "settings": {"publishing": {"mode": "live", "approval_required": True}, "analytics": {}},
            "social_metadata": {"title": "Title", "description": "Description", "hashtags": []},
        }

    def prepare(self, clip_id: UUID, platform: str, mode: str, request: dict[str, Any], status: str) -> dict[str, Any]:
        del clip_id, mode, request, status
        return {**self.rows[platform], "platform": platform}

    def mark_publishing(self, publication_id: UUID) -> None:
        self._row(publication_id)["status"] = "publishing"

    def mark_published(self, publication_id: UUID, result: dict[str, Any], published_at: datetime) -> None:
        del result, published_at
        self._row(publication_id)["status"] = "published"

    def mark_failed(self, publication_id: UUID, code: str, message: str) -> None:
        del message
        self._row(publication_id).update(status="failed", error_code=code)

    def schedule_metrics(self, publication_id: UUID, published_at: datetime, offsets: list[str], now: datetime) -> None:
        del publication_id, published_at, offsets, now

    def schedule_auto_publish(self, run_id: UUID, clip_id: UUID, due_at: datetime, now: datetime) -> None:
        del run_id, clip_id, due_at, now

    def reset_failed_publications(self, clip_id: UUID) -> dict[str, Any]:
        del clip_id
        reset: list[str] = []
        if self.clip_status == "approved":
            for platform, row in self.rows.items():
                if row["status"] == "failed":
                    row["status"] = "pending"
                    reset.append(platform)
        return {"run_id": str(self.run_id), "clip_status": self.clip_status, "reset": reset}

    def update_run_outcome(self, run_id: UUID, outcome: str) -> None:
        del run_id
        self.outcome = outcome


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def local_path(self, key: str) -> Path:
        del key
        return self.path


class FakePublisher:
    name = "fake"

    def __init__(self, platform: Platform, outcome: PublicationResult | ProviderError | None = None) -> None:
        self.platform = platform
        self.outcome = outcome or PublicationResult("post-1", "https://example/post-1")
        self.requests: list[PublicationRequest] = []

    def is_configured(self) -> bool:
        return True

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        del clip_file
        self.requests.append(request)
        if isinstance(self.outcome, ProviderError):
            raise self.outcome
        return self.outcome

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        del platform_post_id
        return PlatformMetrics()


def _signed_url(clip_id: UUID, expires_at: datetime) -> str:
    return f"https://media.example/public/media/{clip_id}.{int(expires_at.timestamp())}.{'a' * 64}"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
def test_staging_copies_clip_as_token_mp4_and_release_removes_it(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    clip = tmp_path / "final.mp4"
    clip.write_bytes(b"video")
    staging = PublicMediaStaging(share, clock=lambda: NOW)
    signed = _signed_url(CLIP_ID, NOW + timedelta(hours=1))

    staged = staging.stage(clip, signed)

    assert staged == signed + ".mp4"
    staged_file = share / staged.rsplit("/", 1)[-1]
    assert staged_file.read_bytes() == b"video"
    staging.release(staged)
    assert not staged_file.exists()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
def test_staging_sweeps_expired_copies_and_falls_back_without_share(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    expired = share / f"{uuid4()}.{int((NOW - timedelta(minutes=1)).timestamp())}.{'b' * 64}.mp4"
    live = share / f"{uuid4()}.{int((NOW + timedelta(minutes=30)).timestamp())}.{'c' * 64}.mp4"
    unrelated = share / "test.txt"
    for path in (expired, live, unrelated):
        path.write_bytes(b"x")
    clip = tmp_path / "final.mp4"
    clip.write_bytes(b"video")

    PublicMediaStaging(share, clock=lambda: NOW).stage(clip, _signed_url(CLIP_ID, NOW + timedelta(hours=1)))

    assert not expired.exists()
    assert live.exists()
    assert unrelated.exists()
    signed = _signed_url(CLIP_ID, NOW + timedelta(hours=1))
    assert PublicMediaStaging(tmp_path / "missing").stage(clip, signed) == signed


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
@pytest.mark.asyncio
async def test_service_hands_staged_url_to_platform_and_removes_copy_after_failure(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    clip = tmp_path / "final.mp4"
    clip.write_bytes(b"video")
    store = MultiStore({"instagram": "pending"})
    seen: list[bool] = []

    class CheckingPublisher(FakePublisher):
        async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
            assert request.public_media_url is not None
            seen.append((share / request.public_media_url.rsplit("/", 1)[-1]).is_file())
            return await super().publish(request, clip_file)

    publisher = CheckingPublisher(Platform.INSTAGRAM, ProviderError("publish_failed", "rejected", transient=False))
    service = PublishService(
        store,
        Storage(clip),
        {Platform.INSTAGRAM: publisher},
        clock=lambda: NOW,
        public_url=_signed_url,
        staging=PublicMediaStaging(share, clock=lambda: NOW),
    )

    result = await service.execute(store.run_id, CLIP_ID, approval_resolved=True)

    assert result["outcome"] == "not_published"
    assert publisher.requests[0].public_media_url is not None
    assert publisher.requests[0].public_media_url.endswith(".mp4")
    assert seen == [True]
    assert list(share.iterdir()) == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-462")
@pytest.mark.req("CF-REQ-455")
@pytest.mark.asyncio
async def test_retry_republishes_only_failed_publications_and_updates_outcome(tmp_path: Path) -> None:
    store = MultiStore({"youtube": "published", "instagram": "failed"})
    youtube = FakePublisher(Platform.YOUTUBE)
    instagram = FakePublisher(Platform.INSTAGRAM)
    service = PublishService(
        store,
        Storage(tmp_path / "final.mp4"),
        {Platform.YOUTUBE: youtube, Platform.INSTAGRAM: instagram},
        clock=lambda: NOW,
        public_url=_signed_url,
    )

    result = await ApprovalService(store, service, clock=lambda: NOW).retry_failed(CLIP_ID)

    assert result["retried"] == ["instagram"]
    assert result["outcome"] == "published"
    assert store.outcome == "published"
    assert youtube.requests == []
    assert len(instagram.requests) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-462")
@pytest.mark.asyncio
async def test_retry_without_failed_publication_or_approval_is_a_conflict(tmp_path: Path) -> None:
    youtube = FakePublisher(Platform.YOUTUBE)
    for store in (
        MultiStore({"youtube": "published"}),
        MultiStore({"youtube": "failed"}, clip_status="rejected"),
    ):
        service = PublishService(store, Storage(tmp_path / "final.mp4"), {Platform.YOUTUBE: youtube}, clock=lambda: NOW)
        with pytest.raises(PublicationRetryConflict):
            await ApprovalService(store, service, clock=lambda: NOW).retry_failed(CLIP_ID)
        assert store.outcome is None
    assert youtube.requests == []
