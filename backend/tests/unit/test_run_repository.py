from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select

from clipfactory.domain.models import RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ContentProfileRow, LLMRequestRow, RunRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.ports.runs import LLMBudgetExhausted, RunContinuationConflict


@pytest.fixture
def repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    Base.metadata.create_all(engine)
    yield RunRepository(create_session_factory(engine))
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-650")
@pytest.mark.req("CF-REQ-653")
@pytest.mark.req("CF-REQ-850")
def test_run_repository_creates_run_with_profile_snapshot_and_ordered_events(repository) -> None:
    created = repository.create(
        RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={"workflow": {"max_revision_retries": 3}}
    )
    run_id = created["run_id"]
    repository.append_event(UUID(run_id), "stage_started", "Research started", stage="research")
    detail = repository.get(UUID(run_id))
    assert detail["status"] == "queued"
    assert detail["profile_snapshot"]["language"] == "en"
    assert detail["settings_snapshot"] == {"workflow": {"max_revision_retries": 3}}
    assert [event["sequence"] for event in detail["events"]] == [1, 2]
    assert detail["events"][0]["type"] == "run_started"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-701")
def test_run_detail_exposes_the_manual_url_for_url_ingestion(repository) -> None:
    created = repository.create(RunTrigger.MANUAL_URL, manual_url="https://news.example/story", settings_snapshot={})
    detail = repository.get(UUID(created["run_id"]))
    assert detail["manual_url"] == "https://news.example/story"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-652")
def test_run_repository_queues_manual_order_behind_executing_run(repository) -> None:
    first = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    now = datetime.now(UTC)
    repository.claim_next_queued(now)
    second = repository.create(
        RunTrigger.MANUAL_URL, manual_url="https://news.example/story", settings_snapshot={"saved": True}
    )
    assert second["status"] == "queued"
    assert repository.active()["run_id"] == first["run_id"]
    assert repository.claim_next_queued(now) is None
    repository.complete(UUID(first["run_id"]), "not_published", None, now)
    claimed = repository.claim_next_queued(now)
    assert claimed["run_id"] == second["run_id"]
    assert claimed["settings_snapshot"] == {"saved": True}
    assert repository.get(UUID(second["run_id"]))["manual_url"] == "https://news.example/story"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-652")
@pytest.mark.req("CF-REQ-653")
def test_concurrent_admission_and_claims_are_serialized_and_fifo(repository) -> None:
    def create(_):
        return repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={"frozen": True})

    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(create, range(2)))
    assert len({run["run_id"] for run in created}) == 2
    now = datetime.now(UTC)
    # Force a creation-time tie to exercise the documented UUID ordering.
    with repository.sessions.begin() as session:
        for run in session.scalars(select(RunRow)):
            run.created_at = now
        for profile in session.scalars(select(ContentProfileRow)):
            profile.value = {**profile.value, "name": "Changed after admission"}
    expected = sorted(run["run_id"] for run in created)
    assert [run["run_id"] for run in repository.list(status="queued")] == expected

    def claim(_):
        return repository.claim_next_queued(now)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(claim, range(2)))
    assert sum(run is not None for run in claimed) == 1
    first = next(run for run in claimed if run is not None)
    assert first["run_id"] == expected[0]
    assert first["settings_snapshot"] == {"frozen": True}
    assert repository.get(UUID(first["run_id"]))["profile_snapshot"]["name"] != "Changed after admission"
    repository.fail(UUID(expected[0]), "research", "internal_error", "Failure", now)
    # A new repository instance sees and claims durable pending work.
    restarted = RunRepository(repository.sessions)
    next_run = restarted.claim_next_queued(now)
    assert next_run is not None
    assert next_run["run_id"] == expected[1]
    assert restarted.claim_next_queued(now) is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-652")
@pytest.mark.req("CF-REQ-657")
def test_concurrent_continuation_is_admitted_once_and_latest_admission_controls_fifo(repository) -> None:
    rid = UUID(repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    now = datetime.now(UTC)
    repository.claim_next_queued(now)
    repository.fail(rid, "select_assets", "stage_timeout", "Failure", now)
    pending = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    now = datetime.fromisoformat(pending["created_at"]) + timedelta(seconds=1)

    def resume(_):
        try:
            return repository.continue_failed(rid, settings_snapshot={}, expected_stage="select_assets", now=now)
        except RunContinuationConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(resume, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len([event for event in repository.get(rid)["events"] if event["type"] == "run_resumed"]) == 1
    assert repository.active()["run_id"] == pending["run_id"]
    assert repository.claim_next_queued(now)["run_id"] == pending["run_id"]
    repository.complete(UUID(pending["run_id"]), "not_published", None, now)
    assert repository.claim_next_queued(now)["run_id"] == str(rid)
    repository.fail(rid, "select_assets", "stage_timeout", "Failure again", now)
    next_pending = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    # Keep a pending order between the first and second continuation times.
    with repository.sessions.begin() as session:
        session.get(RunRow, UUID(next_pending["run_id"])).created_at = now + timedelta(seconds=1)
    now += timedelta(seconds=2)
    repository.continue_failed(rid, settings_snapshot={}, expected_stage="select_assets", now=now)
    assert [run["run_id"] for run in repository.list(status="queued")] == [next_pending["run_id"], str(rid)]
    assert len([event for event in repository.get(rid)["events"] if event["type"] == "run_resumed"]) == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-668")
def test_daily_admission_reserves_five_requests_for_run_now_and_four_for_manual_url(repository) -> None:
    now = datetime.now(UTC)
    with repository.sessions.begin() as session:
        for _ in range(46):
            session.add(
                LLMRequestRow(
                    task="prior_request",
                    provider="test",
                    model="test-model",
                    attempt_kind="call",
                    started_at=now,
                    outcome="succeeded",
                    rate_limit_headers={},
                )
            )

    policy = {"llm": {"requests_per_day": 50, "daily_reset_timezone": "UTC"}}
    with pytest.raises(LLMBudgetExhausted):
        repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot=policy)

    manual = repository.create(
        RunTrigger.MANUAL_URL,
        manual_url="https://news.example/story",
        settings_snapshot=policy,
    )
    assert manual["trigger"] == RunTrigger.MANUAL_URL.value


@pytest.mark.unit
@pytest.mark.req("CF-REQ-652")
@pytest.mark.req("CF-REQ-654")
def test_run_repository_claims_a_queued_run_and_records_stage_transition(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

    claimed = repository.claim_next_queued(now)
    repository.start_stage(UUID(created["run_id"]), "research", now)

    assert claimed is not None
    assert claimed["run_id"] == created["run_id"]
    detail = repository.get(UUID(created["run_id"]))
    assert detail["status"] == "running"
    assert detail["current_stage"] == "research"
    assert detail["started_at"] == now.isoformat()
    assert [event["type"] for event in detail["events"]] == ["run_started", "stage_started"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
def test_run_repository_failure_is_terminal_and_events_are_ordered(repository) -> None:
    created = repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    run_id = UUID(created["run_id"])
    now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    repository.claim_next_queued(now)
    repository.start_stage(run_id, "write_script", now)

    repository.fail(run_id, "write_script", "internal_error", "RuntimeError: stage unavailable", now)

    detail = repository.get(run_id)
    assert detail["status"] == "failed"
    assert detail["failure_stage"] == "write_script"
    assert detail["failure_code"] == "internal_error"
    assert detail["finished_at"] == now.isoformat()
    assert [event["type"] for event in detail["events"][-2:]] == ["stage_failed", "run_failed"]
    assert detail["events"][-1]["payload"]["failure_code"] == "internal_error"
