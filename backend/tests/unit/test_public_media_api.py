from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.api.app import create_app
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import (
    ClipRow,
    ContentProfileRow,
    PublicationRow,
    RunRow,
    StoryPackageRow,
    StoryRow,
)
from clipfactory.infrastructure.db.publishing_repository import PublishingRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.publishing.media_urls import create_media_token

KEY = "s" * 32


@pytest.fixture
def public_media_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session], UUID, UUID, Path, bytes]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'public-media.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    profile_id, run_id, story_id, package_id, clip_id = (uuid4() for _ in range(5))
    publication_id = uuid4()
    now = datetime.now(UTC)
    with sessions.begin() as session:
        session.add(ContentProfileRow(id=profile_id, name="Test", is_active=True, value={}, updated_at=now))
        session.add(
            RunRow(
                id=run_id,
                trigger="run_now",
                manual_url=None,
                profile_id=profile_id,
                profile_snapshot={},
                settings_snapshot={},
                status="succeeded",
                attempt=1,
                revision_retries_used=0,
                cost_total=0,
                created_at=now,
            )
        )
        session.add(
            StoryRow(id=story_id, run_id=run_id, status="selected", title="Test", summary="Test", category="news")
        )
        session.add(
            StoryPackageRow(
                id=package_id,
                run_id=run_id,
                story_id=story_id,
                key_fact_claim_ids=[],
                version=1,
                created_at=now,
                updated_at=now,
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
                sha256="a" * 64,
                duration_seconds=10,
                width=720,
                height=1280,
                fps=30,
                video_codec="h264",
                audio_codec="aac",
                size_bytes=10,
                composition_spec_hash="b" * 64,
                metadata_json={},
                created_at=now,
            )
        )
        session.add(
            PublicationRow(
                id=publication_id,
                clip_id=clip_id,
                platform="instagram",
                status="publishing",
                mode="live",
                request={},
            )
        )
    settings_values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
        "PUBLIC_MEDIA_BASE_URL": "https://media.example.test",
        "MEDIA_URL_SIGNING_KEY": KEY,
    }
    settings = EnvironmentSettings(**settings_values)
    storage = LocalStorageProvider(tmp_path / "storage")
    clip_path = storage.local_path(f"clips/{clip_id}.mp4")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"fake-mp4-bytes"
    clip_path.write_bytes(content)
    reader = PublishingRepository(sessions)
    client = TestClient(create_app(settings, storage_provider=storage, public_media_reader=reader))
    yield client, sessions, publication_id, clip_id, clip_path, content
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
@pytest.mark.req("CF-NFR-114")
def test_public_media_serves_only_signed_clip_while_publication_is_active(public_media_client) -> None:
    client, sessions, publication_id, clip_id, _path, content = public_media_client
    token = create_media_token(clip_id, now=datetime.now(UTC), ttl_minutes=60, key=KEY.encode())

    fetched = client.get(f"/public/media/{token}")
    assert fetched.status_code == 200
    assert fetched.content == content
    assert fetched.headers["content-type"] == "video/mp4"

    head = client.head(f"/public/media/{token}")
    assert head.status_code == 200
    assert head.content == b""
    ranged = client.get(f"/public/media/{token}", headers={"Range": "bytes=5-8"})
    assert ranged.status_code == 206
    assert ranged.content == content[5:9]

    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert client.get(f"/public/media/{tampered}").status_code == 404
    assert client.get(f"/public/media/{token}/../other").status_code == 404

    with sessions.begin() as session:
        publication = session.get(PublicationRow, publication_id)
        assert publication is not None
        publication.status = "published"
    assert client.get(f"/public/media/{token}").status_code == 404


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
@pytest.mark.req("CF-NFR-114")
def test_public_media_rejects_expired_tokens(public_media_client) -> None:
    client, _sessions, _publication_id, clip_id, _path, _content = public_media_client
    expired_at = datetime(2000, 1, 1, tzinfo=UTC)
    token = create_media_token(clip_id, now=expired_at, ttl_minutes=5, key=KEY.encode())
    assert client.get(f"/public/media/{token}").status_code == 404
