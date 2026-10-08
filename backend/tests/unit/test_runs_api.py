from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from clipfactory.api.app import create_app
from clipfactory.domain.models import RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.http import SafeHTTPClient
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.runs import ActiveRunConflict, RunContinuationConflict, RunNotFound


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
def run_client(tmp_path: Path) -> Generator[tuple[TestClient, RunRepository]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'api-runs.db'}")
    Base.metadata.create_all(engine)
    repository = RunRepository(create_session_factory(engine))

    async def healthy() -> dict[str, bool | str | None]:
        return {"database": True, "ffmpeg": True}

    def resolve_for_test(host: str, _port: int) -> list[str]:
        return [host if host[0].isdigit() else "93.184.216.34"]

    url_validator = SafeHTTPClient(resolver=resolve_for_test).validate_url
    client = TestClient(
        create_app(
            _settings(),
            health_check=healthy,
            run_reader=repository,
            run_creator=repository,
            url_validator=url_validator,
        )
    )
    yield client, repository
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-650")
@pytest.mark.req("CF-REQ-659")
def test_run_now_api_creates_run_and_rejects_second_active_run(run_client) -> None:
    client, _ = run_client

    created = client.post("/api/runs")
    conflict = client.post("/api/runs")

    assert created.status_code == 202
    assert UUID(created.json()["run_id"])
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "active_run_conflict"
    assert conflict.json()["error"]["details"]["active_run_id"] == created.json()["run_id"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-700")
def test_manual_url_api_creates_manual_run_for_public_url(run_client) -> None:
    client, _ = run_client

    response = client.post("/api/runs/manual-url", json={"url": "https://news.example/article"})

    assert response.status_code == 202
    assert client.get(f"/api/runs/{response.json()['run_id']}").json()["trigger"] == "manual_url"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-700")
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "https://user:pw@example.com/",
    ],
)
def test_manual_url_api_rejects_unsafe_urls_without_creating_run(run_client, url: str) -> None:
    client, repository = run_client

    response = client.post("/api/runs/manual-url", json={"url": url})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_manual_url"
    assert repository.active() is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-659")
@pytest.mark.req("CF-REQ-850")
def test_runs_api_lists_active_detail_and_resumable_events(run_client) -> None:
    client, repository = run_client
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    run_id = created["run_id"]
    repository.append_event(UUID(run_id), "stage_started", "Research started", stage="research")

    listed = client.get("/api/runs")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["run_id"] == run_id
    assert client.get("/api/runs/active").json()["run_id"] == run_id
    assert client.get(f"/api/runs/{run_id}").json()["events"][-1]["sequence"] == 2
    assert client.get(f"/api/runs/{run_id}/events?after_sequence=1").json()["items"][0]["sequence"] == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-659")
def test_runs_api_returns_404_for_unknown_run(run_client) -> None:
    client, _ = run_client
    response = client.get(f"/api/runs/{UUID(int=1)}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "run_not_found"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
def test_continue_api_passes_current_settings_and_returns_same_run_id() -> None:
    rid = UUID(int=1)
    captured = []

    async def resume(run_id, snapshot):
        captured.append((run_id, snapshot))
        return {"run_id": str(run_id)}

    client = TestClient(create_app(_settings(), continue_run=resume))
    response = client.post(f"/api/runs/{rid}/continue")
    assert response.status_code == 202
    assert response.json()["run_id"] == str(rid)
    assert captured[0][0] == rid
    assert "environment" in captured[0][1]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RunNotFound("missing"), 404, "run_not_found"),
        (ActiveRunConflict(UUID(int=2)), 409, "active_run_conflict"),
        (RunContinuationConflict("No checkpoint"), 409, "run_continuation_conflict"),
    ],
)
def test_continue_api_surfaces_conflicts(error, status, code) -> None:
    async def resume(run_id, snapshot):
        raise error

    response = TestClient(create_app(_settings(), continue_run=resume)).post(f"/api/runs/{UUID(int=1)}/continue")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
@pytest.mark.req("CF-REQ-852")
def test_event_stream_replays_past_failure_through_continuation(run_client) -> None:
    client, repository = run_client
    now = datetime(2026, 10, 1, tzinfo=UTC)
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    repository.claim_next_queued(now)
    repository.start_stage(rid, "select_assets")
    repository.fail(rid, "select_assets", "stage_timeout", "First failure", now)
    repository.continue_failed(rid, settings_snapshot={}, expected_stage="select_assets", now=now)
    repository.claim_next_queued(now)
    repository.start_stage(rid, "select_assets")
    repository.fail(rid, "select_assets", "stage_timeout", "Second failure", now)
    response = client.get(f"/api/runs/{rid}/events/stream")
    assert "First failure" in response.text
    assert "run_resumed" in response.text
    assert "Second failure" in response.text


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
def test_stop_api_dispatches_to_worker_and_reports_conflicts() -> None:
    rid = UUID(int=1)
    calls = []

    async def stop(run_id):
        calls.append(run_id)
        return {"run_id": str(run_id)}

    response = TestClient(create_app(_settings(), stop_run=stop)).post(f"/api/runs/{rid}/stop")
    assert response.status_code == 202
    assert response.json() == {"run_id": str(rid)}
    assert calls == [rid]

    async def rejected(run_id):
        raise RunContinuationConflict("Publication cannot be stopped")

    response = TestClient(create_app(_settings(), stop_run=rejected)).post(f"/api/runs/{rid}/stop")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "run_stop_conflict"

    async def missing(run_id):
        raise RunNotFound(str(run_id))

    assert TestClient(create_app(_settings(), stop_run=missing)).post(f"/api/runs/{rid}/stop").status_code == 404


@pytest.mark.unit
@pytest.mark.req("CF-REQ-852")
def test_run_event_stream_resumes_after_last_event_id_and_closes(run_client) -> None:
    client, repository = run_client
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    run_id = UUID(created["run_id"])
    repository.claim_next_queued(datetime(2026, 10, 1, tzinfo=UTC))
    repository.start_stage(run_id, "research")
    repository.fail(run_id, "research", "no_candidates", "No candidates", datetime(2026, 10, 1, tzinfo=UTC))

    response = client.get(
        f"/api/runs/{run_id}/events/stream",
        headers={"Last-Event-ID": "2"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 3" in response.text
    assert "id: 4" in response.text
    assert "id: 1" not in response.text
    assert "event: run_failed" in response.text
