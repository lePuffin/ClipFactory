import io
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine

from clipfactory.api.app import create_app
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.storage import LocalStorageProvider


@pytest.fixture
def import_client(tmp_path: Path) -> Generator[TestClient]:
    engine = create_engine(f"sqlite:///{tmp_path / 'asset-import-api.db'}")
    Base.metadata.create_all(engine)
    repository = AssetRepository(create_session_factory(engine))
    storage = LocalStorageProvider(tmp_path / "data")
    settings_values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "DATA_DIR": str(tmp_path / "uploads"),
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
        "PUBLIC_MEDIA_BASE_URL": None,
        "MEDIA_URL_SIGNING_KEY": None,
    }
    client = TestClient(
        create_app(EnvironmentSettings(**settings_values), asset_repository=repository, storage_provider=storage)
    )
    yield client
    engine.dispose()


def _png() -> bytes:
    payload = io.BytesIO()
    Image.new("RGB", (800, 1200), (10, 20, 30)).save(payload, format="PNG")
    return payload.getvalue()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
def test_asset_import_endpoint_requires_licence_and_stores_provenance(import_client: TestClient) -> None:
    missing = import_client.post(
        "/api/assets/import",
        files={"file": ("photo.png", _png(), "image/png")},
        data={"category": "photo"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"][0]["type"] == "missing"

    response = import_client.post(
        "/api/assets/import",
        files={"file": ("../../photo.png", _png(), "image/png")},
        data={"category": "photo", "license": "CC0", "description": " Lisbon ", "tags": "News, lisbon"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["provenance"]["origin"] == "imported"
    assert body["provenance"]["license"] == "CC0"
    assert body["storage_key"].startswith("assets/")
    assert "photo.png" not in body["storage_key"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
def test_asset_import_endpoint_rejects_invalid_media(import_client: TestClient) -> None:
    response = import_client.post(
        "/api/assets/import",
        files={"file": ("broken.png", b"<html>no media</html>", "image/png")},
        data={"category": "photo", "license": "CC0"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_media"
