from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from test_settings_and_api import settings

from clipfactory.api.app import create_app
from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.configuration_repository import ConfigurationRepository
from clipfactory.infrastructure.db.models import ContentProfileRow
from clipfactory.infrastructure.db.scheduler_repository import DailyScheduleRepository
from clipfactory.infrastructure.db.session import create_session_factory

NOW = datetime(2026, 10, 11, 21, 0, tzinfo=UTC)


@pytest.fixture
def profile_client(tmp_path: Path) -> Generator[tuple[TestClient, ConfigurationRepository]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    repository = ConfigurationRepository(create_session_factory(engine), clock=lambda: NOW)
    repository.replace_active_profile(ContentProfile(name="Original"))
    yield (
        TestClient(
            create_app(
                settings(),
                configuration=repository,
                schedule_repository=DailyScheduleRepository(repository._sessions),
                clock=lambda: NOW,
            )
        ),
        repository,
    )
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_named_profiles_crud_activation_and_active_endpoint(profile_client) -> None:
    client, repository = profile_client
    original = client.get("/api/content-profiles").json()["items"][0]
    assert original["name"] == "Original"
    assert original["is_active"] is True
    created = client.post("/api/content-profiles", json={"name": "Second", "profile": {"language": "es"}})
    assert created.status_code == 201
    second = created.json()
    assert second["name"] == second["profile"]["name"] == "Second"
    assert second["id"] == second["profile"]["id"]
    assert second["is_active"] is second["profile"]["is_active"] is False
    assert second["updated_at"] == second["profile"]["updated_at"]
    assert second["updated_at"].startswith("2026-10-11T21:00:00")
    assert client.get("/api/content-profile").json()["id"] == original["id"]
    updated = client.put(f"/api/content-profiles/{second['id']}", json={"name": "Renamed"})
    assert updated.json()["profile"]["language"] == "es"
    assert updated.json()["profile"]["name"] == "Renamed"
    activated = client.post(f"/api/content-profiles/{second['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True
    assert client.post(f"/api/content-profiles/{second['id']}/activate").status_code == 200
    items = client.get("/api/content-profiles").json()["items"]
    assert sum(item["is_active"] for item in items) == 2
    assert all(item["is_active"] == item["profile"]["is_active"] for item in items)
    assert client.get("/api/content-profile").json()["id"] == second["id"]
    active_update = client.put("/api/content-profile", json={"name": "Active renamed", "language": "fr"})
    assert active_update.status_code == 200
    assert active_update.json()["id"] == second["id"]
    with repository._sessions() as session:
        rows = list(session.scalars(select(ContentProfileRow)))
        assert len(rows) == 2
        assert sum(row.is_active for row in rows) == 2
    deactivated = client.post(f"/api/content-profiles/{original['id']}/deactivate")
    assert deactivated.status_code == 200
    deleted = client.delete(f"/api/content-profiles/{original['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert len(client.get("/api/content-profiles").json()["items"]) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_named_profile_creation_can_activate_and_ignores_submitted_identity(profile_client) -> None:
    client, _ = profile_client
    submitted_id = str(uuid4())
    response = client.post(
        "/api/content-profiles",
        json={
            "name": "Activated",
            "activate": True,
            "profile": {"id": submitted_id, "name": "Ignored", "is_active": False},
        },
    )
    assert response.status_code == 201
    item = response.json()
    assert item["id"] != submitted_id
    assert item["profile"]["name"] == "Activated"
    assert item["is_active"] is item["profile"]["is_active"] is True
    assert client.get("/api/content-profile").json()["id"] == item["id"]
    response = client.put(
        f"/api/content-profiles/{item['id']}", json={"profile": {"id": submitted_id, "language": "de"}}
    )
    assert response.json()["id"] == item["id"]
    assert response.json()["profile"]["name"] == "Activated"
    assert response.json()["is_active"] is True


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
def test_named_profile_conflicts_and_missing_ids_leave_state_unchanged(profile_client) -> None:
    client, _ = profile_client
    original = client.get("/api/content-profiles").json()["items"][0]
    duplicate = client.post("/api/content-profiles", json={"name": "Original", "profile": {}, "activate": True})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "profile_name_conflict"
    second = client.post("/api/content-profiles", json={"name": "Second", "profile": {}}).json()
    conflict = client.put(f"/api/content-profiles/{second['id']}", json={"name": "Original"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "profile_name_conflict"
    forbidden = client.delete(f"/api/content-profiles/{original['id']}")
    assert forbidden.status_code == 409
    assert forbidden.json()["error"]["code"] == "active_profile_delete_forbidden"
    for response in (
        client.put(f"/api/content-profiles/{uuid4()}", json={"name": "Missing"}),
        client.post(f"/api/content-profiles/{uuid4()}/activate"),
        client.delete(f"/api/content-profiles/{uuid4()}"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "profile_not_found"
    assert client.get("/api/content-profile").json()["id"] == original["id"]
    assert {item["name"] for item in client.get("/api/content-profiles").json()["items"]} == {"Original", "Second"}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-551")
@pytest.mark.parametrize(
    "profile",
    [
        {"duration": {"min_seconds": 90, "target_seconds": 70, "max_seconds": 60}},
        {"schedule": {"timezone": "Mars/Base"}},
    ],
)
def test_named_profile_validation_matches_active_profile_errors(profile_client, profile: dict) -> None:
    client, _ = profile_client
    original = client.get("/api/content-profiles").json()["items"][0]
    before = client.get("/api/content-profiles").json()
    for response in (
        client.post("/api/content-profiles", json={"name": "Invalid", "profile": profile}),
        client.put(f"/api/content-profiles/{original['id']}", json={"profile": profile}),
        client.put("/api/content-profile", json=profile),
    ):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "profile_validation_failed"
        assert response.json()["error"]["details"]["errors"]
    assert client.get("/api/content-profiles").json() == before


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-651")
def test_schedule_crud_preserves_other_rules_and_last_delete_stays_empty(profile_client) -> None:
    client, _ = profile_client
    profile_id = client.get("/api/content-profiles").json()["items"][0]["id"]
    base = f"/api/content-profiles/{profile_id}/schedules"
    legacy = client.get("/api/schedules").json()["items"][0]["rule_id"]
    added = client.post(base, json={"local_time": "18:00", "enabled": True})
    assert added.status_code == 200
    rule_id = added.json()["rule"]["id"]
    assert {row["rule_id"] for row in client.get("/api/schedules").json()["items"]} == {legacy, rule_id}
    assert client.put(f"{base}/{rule_id}", json={"local_time": "19:15", "enabled": False}).status_code == 200
    rules = client.get("/api/content-profile").json()["schedules"]
    assert rules[1]["local_time"] == "19:15"
    assert rules[1]["enabled"] is False
    before = client.get("/api/content-profile").json()
    for response in (
        client.put(f"{base}/{uuid4()}", json={"enabled": False}),
        client.delete(f"{base}/{uuid4()}"),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "rule_not_found"
    assert client.get("/api/content-profile").json() == before
    assert client.delete(f"{base}/{legacy}").status_code == 204
    assert client.delete(f"{base}/{rule_id}").status_code == 204
    assert client.get("/api/content-profile").json()["schedules"] == []
    assert client.get("/api/schedules").json()["items"][0]["rule_id"] is None
    assert client.post(base, json={"local_time": "06:00"}).status_code == 200
    assert len(client.get("/api/content-profile").json()["schedules"]) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-551")
@pytest.mark.parametrize("time", ["25:00", "06:99", "6:00", "06:00\n", ""])
def test_schedule_time_validation_is_atomic(profile_client, time: str) -> None:
    client, _ = profile_client
    original = client.get("/api/content-profile").json()
    base = f"/api/content-profiles/{original['id']}/schedules"
    rule_id = client.get("/api/schedules").json()["items"][0]["rule_id"]
    for response in (
        client.post(base, json={"local_time": time}),
        client.put(f"{base}/{rule_id}", json={"local_time": time}),
        client.put(f"{base}/{rule_id}", json={"enabled": None}),
    ):
        assert response.status_code == 422
    assert client.get("/api/content-profile").json() == original


@pytest.mark.unit
@pytest.mark.req("CF-REQ-551")
@pytest.mark.parametrize("prefix", ["../football", "foo-bar", "1FOOTBALL", "X" * 65])
def test_invalid_account_prefix_is_rejected(profile_client, prefix: str) -> None:
    client, _ = profile_client
    original = client.get("/api/content-profile").json()
    response = client.put("/api/content-profile", json={**original, "env_prefix": prefix})
    assert response.status_code == 422
    assert client.get("/api/content-profile").json() == original


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.parametrize("name", ["", "   ", "a" * 161])
def test_named_profile_name_validation(profile_client, name: str) -> None:
    client, _ = profile_client
    original = client.get("/api/content-profiles").json()["items"][0]
    assert client.post("/api/content-profiles", json={"name": name, "profile": {}}).status_code == 422
    assert client.put(f"/api/content-profiles/{original['id']}", json={"name": name}).status_code == 422


@pytest.mark.unit
@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-555")
def test_deleting_profile_used_by_run_preserves_immutable_snapshot(profile_client) -> None:
    from sqlalchemy import event

    from clipfactory.infrastructure.db.models import RunRow

    client, repository = profile_client
    original = client.get("/api/content-profiles").json()["items"][0]
    snapshot = original["profile"]
    run_id = uuid4()
    engine = repository._sessions.kw["bind"]

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    engine.dispose()
    with repository._sessions.begin() as session:
        session.add(
            RunRow(
                id=run_id,
                trigger="run_now",
                profile_id=UUID(original["id"]),
                profile_snapshot=snapshot,
                settings_snapshot={},
                status="completed",
                created_at=NOW,
            )
        )
    client.post("/api/content-profiles", json={"name": "Replacement", "profile": {}, "activate": True})
    client.post(f"/api/content-profiles/{original['id']}/deactivate")
    assert client.delete(f"/api/content-profiles/{original['id']}").status_code == 204
    with repository._sessions() as session:
        run = session.get(RunRow, run_id)
        assert run is not None
        assert run.profile_id is None
        assert run.profile_snapshot == snapshot
    missing = client.post(f"/api/content-profiles/{original['id']}/activate")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "profile_not_found"
    assert client.post("/api/content-profiles", json={"name": "Original", "profile": {}}).status_code == 201
