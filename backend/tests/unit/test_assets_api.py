from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from clipfactory.api.app import create_app
from clipfactory.domain.models import Asset, AssetOrigin, Provenance
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.storage import LocalStorageProvider


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


@pytest.fixture
def asset_client(tmp_path: Path) -> Generator[tuple[TestClient, AssetRepository, Asset, bytes]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'api-assets.db'}")
    Base.metadata.create_all(engine)
    repository = AssetRepository(create_session_factory(engine))
    asset = Asset(
        media_type="image",
        category="photo",
        storage_key="assets/aa/asset.png",
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=123,
        description="Parliament exterior",
        tags=["parliament"],
        subjects=["UK Parliament"],
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="manual", license="CC0"),
    )
    repository.save(asset)
    storage = LocalStorageProvider(tmp_path / "storage")
    content = b"0123456789"
    asset_path = storage.local_path(asset.storage_key)
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(content)
    client = TestClient(create_app(_settings(), asset_repository=repository, storage_provider=storage))
    yield client, repository, asset, content
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-213")
@pytest.mark.req("CF-REQ-605")
def test_asset_api_lists_details_and_removes_retired_assets_from_active_filter(asset_client) -> None:
    client, _repository, asset, _content = asset_client
    listed = client.get("/api/assets")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == str(asset.id)
    detail = client.get(f"/api/assets/{asset.id}")
    assert detail.json()["provenance"]["license"] == "CC0"
    path = Path(detail.json()["storage_path"])
    assert path.is_absolute()
    assert path.parts[-3:] == ("assets", "aa", "asset.png")
    assert path.read_bytes() == _content
    assert listed.json()["items"][0]["storage_path"] == str(path)

    updated = client.patch(f"/api/assets/{asset.id}", json={"status": "retired", "tags": ["Politics", "news"]})
    assert updated.status_code == 200
    assert updated.json()["status"] == "retired"
    assert updated.json()["tags"] == ["news", "politics"]
    assert updated.json()["storage_path"] == str(path)
    assert client.get("/api/assets").json()["items"] == []
    assert client.get("/api/assets?status=retired").json()["items"][0]["id"] == str(asset.id)


@pytest.mark.unit
@pytest.mark.req("CF-NFR-110")
def test_asset_api_rejects_unknown_update_fields(asset_client) -> None:
    client, _repository, asset, _content = asset_client
    response = client.patch(f"/api/assets/{asset.id}", json={"api_key": "not-accepted"})
    assert response.status_code == 422


@pytest.mark.unit
@pytest.mark.req("CF-REQ-605")
def test_asset_file_endpoint_streams_full_and_partial_content(asset_client) -> None:
    client, _repository, asset, content = asset_client

    full = client.get(f"/api/assets/{asset.id}/file")
    assert full.status_code == 200
    assert full.content == content
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"] == "image/png"

    partial = client.get(f"/api/assets/{asset.id}/file", headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"

    suffix = client.get(f"/api/assets/{asset.id}/file", headers={"Range": "bytes=-3"})
    assert suffix.status_code == 206
    assert suffix.content == b"789"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-605")
def test_asset_file_endpoint_hides_missing_files_and_rejects_unsatisfiable_ranges(asset_client) -> None:
    client, _repository, asset, _content = asset_client

    missing = client.get("/api/assets/00000000-0000-0000-0000-000000000000/file")
    assert missing.status_code == 404

    invalid_range = client.get(f"/api/assets/{asset.id}/file", headers={"Range": "bytes=100-"})
    assert invalid_range.status_code == 416
    assert invalid_range.headers["content-range"] == "bytes */10"
