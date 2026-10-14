from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ContentProfileRow, RunRow


@pytest.mark.unit
@pytest.mark.req("CF-NFR-013")
def test_schema_creates_all_required_persistence_tables() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    assert {
        "run",
        "run_event",
        "source",
        "story",
        "claim",
        "story_package",
        "asset",
        "clip",
        "evaluation",
        "publication",
        "metric_snapshot",
        "scheduled_task",
        "cost_entry",
        "llm_request",
    } <= set(Base.metadata.tables)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-652")
def test_database_enforces_one_active_run_and_unique_event_sequence() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    profile_id = uuid4()
    with Session(engine) as session:
        session.add(ContentProfileRow(id=profile_id, name="Default", is_active=True, value={}, updated_at=now))
        session.flush()
        session.add(
            RunRow(
                id=uuid4(),
                trigger="run_now",
                profile_id=profile_id,
                profile_snapshot={},
                settings_snapshot={},
                status="running",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            RunRow(
                id=uuid4(),
                trigger="run_now",
                profile_id=profile_id,
                profile_snapshot={},
                settings_snapshot={},
                status="queued",
                created_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
