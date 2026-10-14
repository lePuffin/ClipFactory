from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import RenderRevisionRow
from clipfactory.infrastructure.db.render_revision_repository import RenderRevisionRepository
from clipfactory.infrastructure.db.session import create_session_factory


@pytest.mark.unit
@pytest.mark.req("CF-REQ-361")
@pytest.mark.req("CF-REQ-417")
def test_render_revision_is_immutable_and_cannot_claim_approval(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'revisions.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    repository = RenderRevisionRepository(sessions)
    revision_id, clip_id = uuid4(), uuid4()
    value = {"status": "pending_review", "storage_key": "clips/revision.mp4", "openrouter_calls": 0}
    repository.save_revision(revision_id, clip_id, value, datetime(2026, 10, 6, tzinfo=UTC))
    with sessions() as session:
        row = session.get(RenderRevisionRow, revision_id)
        assert row is not None
        assert row.value["status"] == "pending_review"
    with pytest.raises(ValueError, match="immutable"):
        repository.save_revision(revision_id, clip_id, value, datetime(2026, 10, 6, tzinfo=UTC))
    engine.dispose()
