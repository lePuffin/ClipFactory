from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select

from clipfactory.domain.models import ContentProfile, ScheduleRule
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ContentProfileRow, ScheduledTaskRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.scheduler_repository import DailyScheduleRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.workflow.scheduler import DailyRunScheduler


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def scheduling(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Lisbon")
    engine = create_engine(f"sqlite:///{tmp_path / 'scheduler.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    profile = ContentProfile()
    with sessions.begin() as session:
        session.add(
            ContentProfileRow(
                id=profile.id,
                name=profile.name,
                is_active=True,
                value=profile.model_dump(mode="json"),
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )
    yield sessions, DailyScheduleRepository(sessions), RunRepository(sessions)
    engine.dispose()


def make_scheduler(tasks, runs, clock: FakeClock) -> DailyRunScheduler:
    return DailyRunScheduler(
        tasks,
        runs,
        clock=clock,
        settings_snapshot=lambda: {"workflow": {"stage_timeout_seconds": 1800}},
        grace_minutes=60,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
async def test_daily_schedule_creates_exactly_one_run_when_poll_crosses_local_time(scheduling) -> None:
    _, tasks, runs = scheduling
    clock = FakeClock(datetime(2026, 10, 1, 3, 59, 50, tzinfo=UTC))  # 04:59:50 Europe/Lisbon
    scheduler = make_scheduler(tasks, runs, clock)

    await scheduler.run_once()
    clock.now = datetime(2026, 10, 1, 4, 0, 20, tzinfo=UTC)
    await scheduler.run_once()
    await scheduler.run_once()

    scheduled = runs.list(trigger="scheduled")
    assert len(scheduled) == 1
    assert scheduled[0]["status"] == "queued"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
@pytest.mark.parametrize(("hour", "expected_runs"), [(4, 1), (5, 0)])
async def test_startup_runs_only_missed_schedule_inside_grace(scheduling, hour: int, expected_runs: int) -> None:
    sessions, tasks, runs = scheduling
    clock = FakeClock(datetime(2026, 10, 1, hour, 30, tzinfo=UTC))

    await make_scheduler(tasks, runs, clock).run_once()

    assert len(runs.list(trigger="scheduled")) == expected_runs
    if expected_runs == 0:
        with sessions() as session:
            skipped = session.scalars(select(ScheduledTaskRow).where(ScheduledTaskRow.status == "skipped")).all()
        assert len(skipped) == 1
        assert skipped[0].last_error == "Daily Run missed its configured grace period"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
async def test_profile_schedule_change_replaces_pending_daily_task(scheduling) -> None:
    sessions, tasks, runs = scheduling
    clock = FakeClock(datetime(2026, 10, 1, 3, 0, tzinfo=UTC))
    scheduler = make_scheduler(tasks, runs, clock)
    await scheduler.run_once()

    with sessions.begin() as session:
        row = session.scalar(select(ContentProfileRow).where(ContentProfileRow.is_active.is_(True)))
        assert row is not None
        value = dict(row.value)
        value["schedule"] = {**value["schedule"], "local_time": "06:15"}
        row.value = value

    await scheduler.run_once()

    pending = tasks.pending()
    assert pending is not None
    assert pending["payload"]["local_time"] == "06:15"
    assert pending["due_at"] == datetime(2026, 10, 1, 5, 15, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.req("CF-REQ-550")
@pytest.mark.asyncio
async def test_multiple_active_profiles_scheduled_independently(scheduling) -> None:
    sessions, tasks, runs = scheduling
    football_profile = ContentProfile(name="Football News")
    football_val = football_profile.model_dump(mode="json")
    football_val["schedule"] = {"enabled": True, "local_time": "06:00", "timezone": "Europe/Lisbon"}
    with sessions.begin() as session:
        session.add(
            ContentProfileRow(
                id=football_profile.id,
                name="Football News",
                is_active=True,
                value=football_val,
                updated_at=datetime(2026, 10, 1, tzinfo=UTC),
            )
        )

    # At 03:00 UTC, reconcile creates tasks for both profiles (05:00 and 06:00 Lisbon -> 04:00 and 05:00 UTC)
    clock = FakeClock(datetime(2026, 10, 1, 3, 0, tzinfo=UTC))
    scheduler = make_scheduler(tasks, runs, clock)
    await scheduler.run_once()

    schedules = tasks.all_schedules()
    assert len(schedules) == 2
    names = {s["profile_name"] for s in schedules}
    assert "Football News" in names
    assert all(s["status"] == "pending" for s in schedules)

    # Advance clock to 04:05 UTC -> first profile runs (due at 04:00 UTC)
    clock.now = datetime(2026, 10, 1, 4, 5, tzinfo=UTC)
    await scheduler.run_once()
    assert len(runs.list(trigger="scheduled")) == 1

    # Mark the first run as completed so the next scheduled run can proceed
    from clipfactory.infrastructure.db.models import RunRow

    with sessions.begin() as session:
        for r in session.scalars(select(RunRow)):
            r.status = "completed"

    # Advance clock to 05:05 UTC -> second profile (Football News at 06:00 Lisbon / 05:00 UTC) runs!
    clock.now = datetime(2026, 10, 1, 5, 5, tzinfo=UTC)
    await scheduler.run_once()
    all_runs = runs.list(trigger="scheduled")
    assert len(all_runs) == 2
    # Verify that the football run was created with the football profile ID!
    details = [runs.get(UUID(r["run_id"])) for r in all_runs]
    football_run = next(r for r in details if r["profile_id"] == str(football_profile.id))
    assert football_run["profile_snapshot"]["name"] == "Football News"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.asyncio
async def test_multiple_rules_run_independently_and_empty_rules_stay_empty(scheduling) -> None:
    from clipfactory.infrastructure.db.models import RunRow

    sessions, tasks, runs = scheduling
    first, second = ScheduleRule(local_time="05:00"), ScheduleRule(local_time="06:00")
    with sessions.begin() as session:
        row = session.scalar(select(ContentProfileRow))
        row.value = {**row.value, "schedules": [first.model_dump(mode="json"), second.model_dump(mode="json")]}
    clock = FakeClock(datetime(2026, 10, 1, 3, tzinfo=UTC))
    scheduler = make_scheduler(tasks, runs, clock)
    await scheduler.run_once()
    assert {item["rule_id"] for item in tasks.all_schedules()} == {str(first.id), str(second.id)}
    clock.now = datetime(2026, 10, 1, 4, 5, tzinfo=UTC)
    await scheduler.run_once()
    assert len(runs.list(trigger="scheduled")) == 1
    with sessions.begin() as session:
        for run in session.scalars(select(RunRow)):
            run.status = "completed"
    clock.now = datetime(2026, 10, 1, 5, 5, tzinfo=UTC)
    await scheduler.run_once()
    assert len(runs.list(trigger="scheduled")) == 2
    with sessions.begin() as session:
        row = session.scalar(select(ContentProfileRow))
        row.value = {**row.value, "schedules": []}
    await scheduler.run_once()
    await scheduler.run_once()
    assert tasks.pending() is None
    assert tasks.all_schedules()[0]["rule_id"] is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-651")
@pytest.mark.parametrize(
    ("day", "local_time", "expected"),
    [
        (date(2026, 3, 29), "01:30", datetime(2026, 3, 29, 1, tzinfo=UTC)),
        (date(2026, 10, 25), "01:30", datetime(2026, 10, 25, 0, 30, tzinfo=UTC)),
        (date(2026, 12, 1), "06:00", datetime(2026, 12, 1, 6, tzinfo=UTC)),
        (date(2026, 7, 1), "06:00", datetime(2026, 7, 1, 5, tzinfo=UTC)),
    ],
)
def test_local_schedule_uses_dst_rules(monkeypatch, day, local_time, expected) -> None:
    from clipfactory.infrastructure.db.scheduler_repository import _occurrence_local

    monkeypatch.setenv("TZ", "Europe/Lisbon")
    assert _occurrence_local(day, local_time) == expected
