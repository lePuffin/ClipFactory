from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.api.app import create_app
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.catalogue_repository import CatalogueRepository
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
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.storage import LocalStorageProvider

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _settings() -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
        "PUBLIC_MEDIA_BASE_URL": None,
        "MEDIA_URL_SIGNING_KEY": None,
    }
    return EnvironmentSettings(**values)


class Configuration:
    def settings(self, defaults: dict[str, Any]) -> dict[str, Any]:
        defaults["budget"] = {
            **defaults["budget"],
            "currency": "EUR",
            "max_cost_per_clip": 1.0,
            "max_cost_per_month": 30.0,
        }
        return defaults


@pytest.fixture
def catalogue_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session], UUID, UUID]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'catalogue-api.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    repository = CatalogueRepository(sessions)
    storage = LocalStorageProvider(tmp_path / "storage")
    approved_clip_id, pending_clip_id = _seed_catalogue(sessions, storage)
    client = TestClient(
        create_app(
            _settings(),
            storage_provider=storage,
            catalogue=repository,
            budget_reader=repository,
            dashboard_reader=repository,
            configuration=Configuration(),
            clock=lambda: NOW,
        )
    )
    yield client, sessions, approved_clip_id, pending_clip_id
    engine.dispose()


def _seed_catalogue(sessions: sessionmaker[Session], storage: LocalStorageProvider) -> tuple[UUID, UUID]:
    profile_id = uuid4()
    approved_clip_id = uuid4()
    pending_clip_id = uuid4()
    approved_run_id: UUID | None = None
    with sessions.begin() as session:
        session.add(
            ContentProfileRow(
                id=profile_id,
                name="Test",
                is_active=True,
                value={
                    "name": "Test",
                    "schedule": {"enabled": True, "local_time": "09:00", "timezone": "Europe/Lisbon"},
                },
                updated_at=NOW,
            )
        )
        for index, clip_id in enumerate((approved_clip_id, pending_clip_id)):
            run_id, story_id, package_id = uuid4(), uuid4(), uuid4()
            if index == 0:
                approved_run_id = run_id
            session.add(
                RunRow(
                    id=run_id,
                    trigger="run_now",
                    profile_id=profile_id,
                    profile_snapshot={},
                    settings_snapshot={},
                    status="completed",
                    outcome="awaiting_approval" if index else "published",
                    approved_clip_id=clip_id,
                    attempt=1,
                    revision_retries_used=0,
                    cost_total=Decimal("0.75") if index == 0 else Decimal("0.25"),
                    created_at=NOW - timedelta(days=index + 1),
                    finished_at=NOW - timedelta(days=index + 1),
                )
            )
            session.add(
                StoryRow(
                    id=story_id,
                    run_id=run_id,
                    status="selected",
                    title=f"Story {index + 1}",
                    summary="Summary",
                    category="technology",
                )
            )
            session.add(
                StoryPackageRow(
                    id=package_id,
                    run_id=run_id,
                    story_id=story_id,
                    key_fact_claim_ids=[],
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                ClipRow(
                    id=clip_id,
                    run_id=run_id,
                    story_package_id=package_id,
                    story_package_version=1,
                    attempt=1,
                    status="approved",
                    storage_key=f"clips/{clip_id}.mp4",
                    sha256=str(index + 1) * 64,
                    duration_seconds=70,
                    width=720,
                    height=1280,
                    fps=30,
                    video_codec="h264",
                    audio_codec="aac",
                    size_bytes=14,
                    composition_spec_hash="c" * 64,
                    metadata_json={
                        "social_metadata": {
                            "title": f"Platform title {index + 1}",
                            "description": "Grounded description",
                            "hashtags": ["news"],
                            "source_attributions": ["Example News"],
                            "asset_attributions": [],
                            "contains_synthetic_media": False,
                            "synthetic_voice": True,
                        }
                    },
                    created_at=NOW - timedelta(days=index + 1),
                )
            )
            publication_id = uuid4()
            session.add(
                PublicationRow(
                    id=publication_id,
                    clip_id=clip_id,
                    platform="youtube" if index == 0 else "instagram",
                    status="published" if index == 0 else "awaiting_approval",
                    mode="live",
                    request={},
                    platform_post_id="post-1" if index == 0 else None,
                    platform_url="https://youtube.example/watch/post-1" if index == 0 else None,
                    published_at=NOW - timedelta(days=1) if index == 0 else None,
                )
            )
            if index == 0:
                for offset, views in (("1h", 100), ("24h", 900)):
                    session.add(
                        MetricSnapshotRow(
                            publication_id=publication_id,
                            platform="youtube",
                            offset_label=offset,
                            scheduled_for=NOW,
                            captured_at=NOW - (timedelta(hours=2) if offset == "1h" else timedelta(hours=1)),
                            views=views,
                            likes=90,
                            comments=9,
                            shares=3,
                            watch_time_seconds=3600,
                            average_retention_ratio=0.75,
                            followers_delta=4,
                            estimated_revenue=Decimal("0.45"),
                            revenue_currency="USD",
                            revenue_basis="rpm_estimate",
                            raw={},
                        )
                    )
            else:
                session.add(
                    ScheduledTaskRow(
                        kind="auto_publish",
                        due_at=NOW + timedelta(minutes=8),
                        payload={"run_id": str(run_id), "clip_id": str(clip_id)},
                        status="pending",
                        attempts=0,
                        created_at=NOW - timedelta(minutes=2),
                        updated_at=NOW - timedelta(minutes=2),
                    )
                )
        assert approved_run_id is not None
        session.add_all(
            [
                CostEntryRow(
                    run_id=approved_run_id,
                    clip_id=approved_clip_id,
                    provider="openrouter",
                    operation="write_script",
                    quantity=Decimal("1"),
                    amount=Decimal("0.75"),
                    currency="EUR",
                    basis="reported",
                    created_at=NOW - timedelta(hours=1),
                ),
                CostEntryRow(
                    run_id=approved_run_id,
                    clip_id=approved_clip_id,
                    provider="google_tts",
                    operation="narration",
                    quantity=Decimal("3000"),
                    amount=Decimal("0.25"),
                    currency="EUR",
                    basis="estimated",
                    created_at=datetime(2026, 9, 30, 23, 30, tzinfo=UTC),
                ),
            ]
        )
        session.add(
            ScheduledTaskRow(
                kind="daily_run",
                due_at=NOW + timedelta(hours=21),
                payload={"profile_id": str(profile_id)},
                status="pending",
                attempts=0,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    for clip_id in (approved_clip_id, pending_clip_id):
        path = storage.local_path(f"clips/{clip_id}.mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"preview-bytes")
    return approved_clip_id, pending_clip_id


@pytest.mark.unit
@pytest.mark.req("CF-REQ-505")
@pytest.mark.req("CF-REQ-610")
def test_clip_list_and_detail_include_publication_link_latest_metrics_and_preview(
    catalogue_client,
) -> None:
    client, _sessions, approved_clip_id, _pending_clip_id = catalogue_client

    listed = client.get("/api/clips")
    detail = client.get(f"/api/clips/{approved_clip_id}")
    preview = client.get(f"/api/clips/{approved_clip_id}/media", headers={"Range": "bytes=0-6"})

    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2
    clip = detail.json()
    assert clip["story_title"] == "Story 1"
    assert clip["cost_total"] == "0.7500"
    assert clip["preview"] == {
        "media_url": f"/api/clips/{approved_clip_id}/media",
        "mime_type": "video/mp4",
        "duration_seconds": 70.0,
        "width": 720,
        "height": 1280,
        "fps": 30.0,
        "size_bytes": 14,
    }
    publication = clip["publications"][0]
    assert publication["status"] == "published"
    assert publication["platform_url"] == "https://youtube.example/watch/post-1"
    assert publication["latest_metrics"]["views"] == 900
    assert preview.status_code == 206
    assert preview.content == b"preview"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-459")
@pytest.mark.req("CF-REQ-460")
@pytest.mark.req("CF-REQ-613")
def test_pending_approval_queue_has_platform_metadata_and_exact_due_time(
    catalogue_client,
) -> None:
    client, _sessions, _approved_clip_id, pending_clip_id = catalogue_client

    response = client.get("/api/clips/pending-approval")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(pending_clip_id)]
    item = response.json()["items"][0]
    assert item["auto_publish_due_at"] == "2026-10-01T12:08:00Z"
    assert item["publications"][0]["platform"] == "instagram"
    assert item["publications"][0]["status"] == "awaiting_approval"
    assert item["social_metadata"]["title"] == "Platform title 2"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-601")
def test_dashboard_summary_uses_last_seven_days_and_latest_publication_snapshot(
    catalogue_client,
) -> None:
    client, _sessions, _approved_clip_id, _pending_clip_id = catalogue_client

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200
    assert response.json() == {
        "period": "7d",
        "clips_approved": 2,
        "publications": 1,
        "views": 900,
        "estimated_revenue": "0.4500",
        "estimated_revenue_currency": "USD",
        "next_scheduled_run_at": "2026-10-02T09:00:00Z",
    }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-612")
@pytest.mark.req("CF-REQ-665")
def test_budget_and_run_cost_endpoints_return_persisted_spend_and_limits(
    catalogue_client,
) -> None:
    client, sessions, approved_clip_id, _pending_clip_id = catalogue_client
    with sessions() as session:
        run_id = session.get(ClipRow, approved_clip_id).run_id

    budget = client.get("/api/budget")
    costs = client.get(f"/api/runs/{run_id}/costs")

    assert budget.status_code == 200
    assert budget.json() == {
        "currency": "EUR",
        "month_to_date_spend": "1.0000",
        "monthly_limit": "30.0000",
        "monthly_remaining": "29.0000",
        "per_clip_limit": "1.0000",
    }
    assert costs.status_code == 200
    assert costs.json()["total"] == "1.0000"
    assert [entry["basis"] for entry in costs.json()["entries"]] == ["estimated", "reported"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-610")
def test_unknown_clip_returns_canonical_not_found_error(catalogue_client) -> None:
    client, _sessions, _approved_clip_id, _pending_clip_id = catalogue_client
    response = client.get(f"/api/clips/{UUID(int=1)}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "clip_not_found"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-505")
@pytest.mark.req("CF-REQ-613")
@pytest.mark.req("CF-REQ-665")
def test_catalogue_repository_reads_pending_latest_metrics_and_cost_entries(
    catalogue_client,
) -> None:
    _client, sessions, approved_clip_id, pending_clip_id = catalogue_client
    repository = CatalogueRepository(sessions)

    pending = repository.clips(pending_approval=True)
    approved = repository.clip(approved_clip_id)
    assert approved is not None
    costs = repository.run_costs(UUID(approved["run_id"]))

    assert [item["id"] for item in pending] == [str(pending_clip_id)]
    assert approved["publications"][0]["latest_metrics"]["views"] == 900
    assert costs is not None
    assert costs["total"] == "1.0000"
