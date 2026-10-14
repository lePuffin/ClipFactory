from copy import deepcopy
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from test_settings_and_api import settings

from clipfactory.api.app import create_app, settings_snapshot
from clipfactory.domain.models import ContentProfile, ResearchPolicy, RunTrigger
from clipfactory.domain.research_policy import ResearchControls
from clipfactory.domain.research_snapshot import run_research_policy
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.configuration_repository import ConfigurationRepository
from clipfactory.infrastructure.db.models import AppSettingsRow, ContentProfileRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.research_defaults import materialize_research, research_defaults
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.manual_url_stage import ManualURLStageUseCase
from clipfactory.workflow.research_stages import ResearchStageUseCase
from clipfactory.workflow.scheduler import DailyRunScheduler

NOW = datetime(2026, 10, 13, 16, tzinfo=UTC)
FEEDS = [["Football", "https://news.example/football/rss"]]


@pytest.mark.req("CF-REQ-551")
@pytest.mark.parametrize(
    "research",
    [
        {"feeds": [["Publisher", "file:///tmp/feed"]]},
        {"feeds": [["Publisher", "not a URL"]]},
        {"feeds": [["Publisher", "https://user:secret@news.example/feed"]]},
        {"feeds": [[" ", "https://news.example/rss"]]},
        {"feeds": [["Publisher"]]},
        {"publisher_quality": {"news.example": "excellent"}},
        {"max_article_bytes": 0},
        {"story_novelty_window_hours": 2161},
        {"near_duplicate_threshold": 0.49},
        {"max_additional_sources": 21},
        {"selection_weights": {"recency": 0.5}},
    ],
)
def test_profile_research_rejects_invalid_controls(research: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ContentProfile.model_validate({"research": research})


@pytest.mark.req("CF-REQ-551")
def test_feed_pairs_remain_json_pairs_and_empty_is_valid() -> None:
    assert ResearchPolicy.model_validate({"feeds": FEEDS}).model_dump(mode="json")["feeds"] == FEEDS
    assert ResearchPolicy(feeds=[]).feeds == []


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
def test_materialization_fills_absent_fields_once_not_explicit_values() -> None:
    legacy = {"feeds": FEEDS, "max_article_bytes": 123456, "publisher_quality": {"news.example": "high"}}
    original = {"research": {"feeds": [], "min_sources": 2, "max_article_bytes": 77}}
    result = materialize_research(original, legacy)
    assert result["research"]["feeds"] == []
    assert result["research"]["max_article_bytes"] == 77
    assert result["research"]["min_sources"] == 2
    assert result["research"]["publisher_quality"] == legacy["publisher_quality"]
    assert result == materialize_research(result, {"feeds": [["Other", "https://other.example/rss"]]})
    assert original == {"research": {"feeds": [], "min_sources": 2, "max_article_bytes": 77}}
    assert materialize_research({}, legacy)["research"]["feeds"] == FEEDS
    assert materialize_research({}, {})["research"] == research_defaults()


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
def test_legacy_snapshot_resolution_uses_only_its_stored_split_values() -> None:
    profile = {"research": {"min_sources": 2}}
    old = {"research": {"feeds": FEEDS, "max_article_bytes": 42, "story_novelty_window_hours": 0}}
    before = deepcopy((profile, old))
    result = run_research_policy(profile, old)
    assert result.feeds == [tuple(FEEDS[0])]
    assert result.min_sources == 2
    assert result.max_article_bytes == 42
    assert result.story_novelty_window_hours == 0
    assert (profile, old) == before
    complete = materialize_research(profile, old["research"])
    assert run_research_policy(complete, {"research": {"feeds": [], "max_article_bytes": 999}}) == result


@pytest.mark.integration
@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
def test_data_migration_preserves_runs_and_explicit_empty_feeds(tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0008_profile_research.py"
    spec = spec_from_file_location("profile_research_migration", path)
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    metadata = sa.MetaData()
    profiles = sa.Table(
        "content_profile", metadata, sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("value", sa.JSON())
    )
    app_settings = sa.Table(
        "app_settings", metadata, sa.Column("section", sa.String(), primary_key=True), sa.Column("value", sa.JSON())
    )
    runs = sa.Table(
        "run",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_snapshot", sa.JSON()),
        sa.Column("settings_snapshot", sa.JSON()),
    )
    first, empty, run_id = uuid4(), uuid4(), uuid4()
    historic = {"research": {"min_sources": 1}}
    legacy = {"research": {"feeds": FEEDS, "max_article_bytes": 77}}
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(
                profiles.insert(),
                [{"id": first, "value": historic}, {"id": empty, "value": {"research": {"feeds": []}}}],
            )
            connection.execute(app_settings.insert().values(section="research", value=legacy["research"]))
            connection.execute(runs.insert().values(id=run_id, profile_snapshot=historic, settings_snapshot=legacy))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.upgrade()
            values = dict(connection.execute(sa.select(profiles.c.id, profiles.c.value)).all())
            assert values[first]["research"]["feeds"] == FEEDS
            assert values[empty]["research"]["feeds"] == []
            saved = connection.execute(sa.select(runs)).one()
            assert saved.profile_snapshot == historic
            assert saved.settings_snapshot == legacy
            assert connection.scalar(sa.select(app_settings.c.value)) == legacy["research"]
    finally:
        engine.dispose()


@pytest.mark.req("CF-REQ-550")
@pytest.mark.req("CF-REQ-551")
@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-752")
def test_api_profiles_are_isolated_and_global_research_is_hidden(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    configuration = ConfigurationRepository(sessions, clock=lambda: NOW)
    try:
        configuration.update_settings("research", {"feeds": FEEDS})
        client = TestClient(create_app(settings(), configuration=configuration))
        first = client.post(
            "/api/content-profiles", json={"name": "Football", "profile": {"research": {"feeds": FEEDS}}}
        )
        second = client.post("/api/content-profiles", json={"name": "World", "profile": {}})
        assert first.status_code == second.status_code == 201
        assert second.json()["profile"]["research"]["feeds"] == research_defaults()["feeds"]
        updated = client.put(
            f"/api/content-profiles/{first.json()['id']}", json={"profile": {"research": {"feeds": []}}}
        )
        assert updated.json()["profile"]["research"]["feeds"] == []
        items = {item["id"]: item for item in client.get("/api/content-profiles").json()["items"]}
        assert items[second.json()["id"]]["profile"]["research"] == second.json()["profile"]["research"]
        assert "research" not in client.get("/api/settings").json()
        assert "research" not in settings_snapshot(settings())
        rejected = client.put("/api/settings/research", json={"feeds": FEEDS})
        assert rejected.status_code == 422
        invalid = client.put(
            f"/api/content-profiles/{first.json()['id']}",
            json={"profile": {"research": {"feeds": [["P", "ftp://news.example/rss"]]}}},
        )
        assert invalid.status_code == 422
        assert configuration.profiles()[0]["profile"]["research"]["feeds"] == []
        with sessions() as session:
            assert session.get(AppSettingsRow, "research").value == {"feeds": FEEDS}  # type: ignore[union-attr]
    finally:
        engine.dispose()


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
@pytest.mark.parametrize("trigger", [RunTrigger.RUN_NOW, RunTrigger.MANUAL_URL, RunTrigger.SCHEDULED])
def test_run_creation_edit_continuation_and_deleted_profile_retain_research(
    tmp_path: Path, trigger: RunTrigger
) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    configuration = ConfigurationRepository(sessions, clock=lambda: NOW)
    runs = RunRepository(sessions)
    try:
        item = configuration.create_profile("Football", ContentProfile.model_validate({"research": {"feeds": FEEDS}}))
        profile_id = UUID(item["id"])
        created = runs.create(
            trigger,
            manual_url="https://news.example/story" if trigger == RunTrigger.MANUAL_URL else None,
            settings_snapshot={},
            profile_id=profile_id,
        )
        run_id = UUID(created["run_id"])
        snapshot = runs.get(run_id)["profile_snapshot"]
        configuration.update_profile(profile_id, profile=ContentProfile(research=ResearchPolicy(feeds=[])))
        runs.fail(run_id, "research", "no_candidates", "fixture", NOW)
        configuration.delete_profile(profile_id)
        runs.continue_failed(run_id, settings_snapshot={"research": {"feeds": []}}, expected_stage="research", now=NOW)
        detail = runs.get(run_id)
        assert detail["profile_id"] is None
        assert detail["profile_snapshot"] == snapshot
        assert run_research_policy(detail["profile_snapshot"], detail["settings_snapshot"]).feeds == [tuple(FEEDS[0])]
        with sessions() as session:
            assert session.get(ContentProfileRow, profile_id) is None
    finally:
        engine.dispose()


class SnapshotRuns:
    def __init__(self, profile: dict[str, Any], global_research: dict[str, Any]) -> None:
        self.detail = {
            "profile_snapshot": profile,
            "settings_snapshot": {"research": global_research},
            "manual_url": "https://news.example/story",
        }

    def get(self, _: UUID) -> dict[str, Any]:
        return self.detail

    def append_event(self, *args: Any, **kwargs: Any) -> None:
        pass


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_stage_consumers_use_profile_controls_not_global(manual: bool) -> None:
    captured: dict[str, Any] = {}

    async def execute(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        captured["profile"] = args[2] if manual else args[1]
        if not manual:
            captured["policy"] = args[2]
        return SimpleNamespace(
            story_id=uuid4(),
            title="Fixture",
            fallback_index=0,
            research=SimpleNamespace(references_seen=0, articles=(), articles_skipped=0),
        )

    profile = ContentProfile.model_validate(
        {
            "research": {
                "feeds": FEEDS,
                "max_article_bytes": 123,
                "publisher_quality": {"news.example": "low"},
                "story_novelty_window_hours": 0,
            }
        }
    ).model_dump(mode="json")
    runs = SnapshotRuns(profile, {"feeds": [], "max_article_bytes": 999, "publisher_quality": {"news.example": "high"}})
    service: Any = SimpleNamespace(execute=execute)
    if manual:
        stage: Any = ManualURLStageUseCase(service, runs)
    else:
        repository: Any = SimpleNamespace(summary=lambda _: None)
        stage = ResearchStageUseCase(service, repository, runs)
    await stage.execute({"run_id": str(uuid4())})
    assert captured["profile"].research.max_article_bytes == 123
    if manual:
        assert captured["max_article_bytes"] == 123
        assert captured["publisher_quality"] == {"news.example": "low"}
    else:
        assert captured["policy"].max_article_bytes == 123
        assert captured["policy"].feeds == [tuple(FEEDS[0])]
        assert captured["recently_covered"] == ()


@pytest.mark.req("CF-REQ-100")
@pytest.mark.req("CF-REQ-555")
@pytest.mark.asyncio
async def test_explicit_empty_feeds_fail_automatic_research_without_provider_io() -> None:
    runs = SnapshotRuns(ContentProfile(research=ResearchPolicy(feeds=[])).model_dump(mode="json"), {"feeds": FEEDS})
    repository: Any = SimpleNamespace(summary=lambda _: None)
    service: Any = SimpleNamespace()
    with pytest.raises(StageFailure) as error:
        await ResearchStageUseCase(service, repository, runs).execute({"run_id": str(uuid4())})  # type: ignore[typeddict-item]
    assert error.value.code == "no_candidates"


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
def test_continuation_preserves_legacy_research_settings(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    runs = RunRepository(sessions)
    try:
        profile = ContentProfile().model_dump(mode="json")
        for key in ResearchControls.model_fields:
            profile["research"].pop(key)
        with sessions.begin() as session:
            session.add(
                ContentProfileRow(id=UUID(profile["id"]), name="Legacy", is_active=True, value=profile, updated_at=NOW)
            )
        old = {"feeds": FEEDS, "max_article_bytes": 123}
        created = runs.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={"research": old})
        run_id = UUID(created["run_id"])
        runs.fail(run_id, "research", "no_candidates", "fixture", NOW)
        runs.continue_failed(run_id, settings_snapshot={"research": {"feeds": []}}, expected_stage="research", now=NOW)
        detail = runs.get(run_id)
        assert detail["settings_snapshot"]["research"] == old
        assert detail["profile_snapshot"] == profile
    finally:
        engine.dispose()


@pytest.mark.req("CF-REQ-555")
@pytest.mark.req("CF-REQ-653")
@pytest.mark.asyncio
async def test_scheduler_selects_its_profiles_research_not_another_active_profile(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'scheduler.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    configuration = ConfigurationRepository(sessions, clock=lambda: NOW)
    runs = RunRepository(sessions)
    try:
        football = configuration.create_profile(
            "Football", ContentProfile.model_validate({"research": {"feeds": FEEDS}}), activate=True
        )
        configuration.create_profile("Other", ContentProfile(research=ResearchPolicy(feeds=[])), activate=True)
        task_id = str(uuid4())
        captured: list[dict[str, Any]] = []
        tasks: Any = SimpleNamespace(
            reconcile=lambda *_: None,
            claim_due=lambda _: {"task_id": task_id, "payload": {"profile_id": football["id"]}},
            finish=lambda *args, **kwargs: captured.append(kwargs),
        )
        scheduler = DailyRunScheduler(
            tasks,
            runs,
            clock=lambda: NOW,
            settings_snapshot=lambda: {"research": {"feeds": []}},
            grace_minutes=30,
        )
        await scheduler.run_once()
        active = runs.active()
        assert active is not None
        detail = runs.get(UUID(active["run_id"]))
        assert detail["trigger"] == "scheduled"
        assert detail["profile_snapshot"]["id"] == football["id"]
        assert run_research_policy(detail["profile_snapshot"], detail["settings_snapshot"]).feeds == [tuple(FEEDS[0])]
        assert captured == [{"skipped_reason": None}]
    finally:
        engine.dispose()
