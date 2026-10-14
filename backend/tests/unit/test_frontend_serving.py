from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from clipfactory.api.app import create_app
from clipfactory.bootstrap import mount_frontend
from clipfactory.infrastructure.settings import EnvironmentSettings


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


@pytest.mark.unit
@pytest.mark.req("CF-NFR-113")
def test_fastapi_serves_frontend_and_keeps_unknown_api_paths_as_json_404(tmp_path: Path) -> None:
    distribution = tmp_path / "dist"
    assets = distribution / "assets"
    assets.mkdir(parents=True)
    (distribution / "index.html").write_text("<main>ClipFactory UI</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ui')", encoding="utf-8")

    app = create_app(_settings())
    mount_frontend(app, distribution)
    client = TestClient(app)
    assert "ClipFactory UI" in client.get("/runs/123").text
    assert client.get("/assets/app.js").text == "console.log('ui')"
    missing_api = client.get("/api/unknown")
    assert missing_api.status_code == 404
    assert missing_api.json()["error"]["code"] == "not_found"
