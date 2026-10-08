"""Load frozen Clip evidence and retain revisions without changing failed Runs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from clipfactory.infrastructure.db.models import ClipRow, RenderRevisionRow, RunRow
from clipfactory.infrastructure.db.production_repository import ProductionRepository
from clipfactory.infrastructure.db.research_repository import ResearchRepository


class RenderRevisionRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def context(self, clip_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            clip = session.get(ClipRow, clip_id)
            if clip is None:
                raise LookupError("Base Clip does not exist")
            run = session.get(RunRow, clip.run_id)
            if run is None:
                raise LookupError("Base Run does not exist")
            run_id, package_id = clip.run_id, clip.story_package_id
            result = {"run_id": run_id, "profile": run.profile_snapshot, "settings": run.settings_snapshot}
        production = ProductionRepository(self.sessions)
        result["clip"] = production.clip(clip_id)
        result["package"] = production.package_context(package_id)
        result["sources"] = ResearchRepository(self.sessions).selected_story_context(run_id).sources
        return result

    def save_revision(self, revision_id: UUID, clip_id: UUID, value: dict[str, Any], now: datetime) -> None:
        if value.get("status") != "pending_review":
            raise ValueError("New render revision must remain pending review")
        with self.sessions.begin() as session:
            if session.get(RenderRevisionRow, revision_id) is not None:
                raise ValueError("Render revisions are immutable")
            session.add(RenderRevisionRow(id=revision_id, base_clip_id=clip_id, value=value, created_at=now))

    def get_revision(self, revision_id: UUID) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(RenderRevisionRow, revision_id)
            return dict(row.value) if row is not None else None
