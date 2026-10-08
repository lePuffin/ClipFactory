from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select

from clipfactory.domain.models import ContentProfile
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
def scheduling(tmp_path):
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
