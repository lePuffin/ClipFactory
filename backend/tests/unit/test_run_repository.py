from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine

from clipfactory.domain.models import RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import LLMRequestRow
from clipfactory.infrastructure.db.repositories import ActiveRunConflict, RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.ports.runs import LLMBudgetExhausted


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
@pytest.mark.req("CF-REQ-652")
def test_run_repository_rejects_a_second_active_run(repository) -> None:
    repository.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    with pytest.raises(ActiveRunConflict):
        repository.create(RunTrigger.MANUAL_URL, manual_url="https://news.example/story", settings_snapshot={})


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
