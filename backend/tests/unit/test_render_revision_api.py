from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from clipfactory.api.app import create_app
from clipfactory.infrastructure.settings import EnvironmentSettings


class Renderer:
    def __init__(self):
        self.calls = []

    async def execute(self, request):
        self.calls.append(request)
        return {
            "revision_id": str(uuid4()),
            "base_clip_id": str(request.base_clip_id),
            "status": "pending_review",
            "storage_key": "clips/revisions/fixture.mp4",
            "sha256": "a" * 64,
            "composition_spec_hash": "b" * 64,
            "request": request.model_dump(mode="json"),
            "probe": {},
            "credits": [],
            "sources": [],
            "template_version": "modern-news-v1",
            "openrouter_calls": 0,
            "tts_calls": 0,
            "research_calls": 0,
            "transcription_calls": 0,
        }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-361")
@pytest.mark.req("CF-REQ-417")
@pytest.mark.asyncio
async def test_recipe_api_exposes_pending_revision_not_publication():
    settings = EnvironmentSettings(
        APP_ENV="development",
        DATABASE_URL=SecretStr("sqlite://"),
        HOST="127.0.0.1",
        API_TOKEN=None,
        PUBLIC_MEDIA_BASE_URL=None,
        MEDIA_URL_SIGNING_KEY=None,
    )
    renderer = Renderer()
    app = create_app(settings, saved_news_renderer=renderer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/render-revisions", json={"base_clip_id": str(uuid4())})
        invalid = await client.post("/api/render-revisions", json={"base_clip_id": "bad", "output_path": "/etc/passwd"})
    assert response.status_code == 201
    assert response.json()["status"] == "pending_review"
    assert response.json()["openrouter_calls"] == 0
    assert invalid.status_code == 422
    assert len(renderer.calls) == 1
