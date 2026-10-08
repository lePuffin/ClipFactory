"""Persistence for editable settings and the active Content Profile."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.db.models import AppSettingsRow, ContentProfileRow


class ConfigurationRepository:
    def __init__(self, sessions: sessionmaker, *, clock: Any) -> None:
        self._sessions = sessions
        self._clock = clock

    def settings(self, defaults: dict[str, Any]) -> dict[str, Any]:
        result = {key: dict(value) if isinstance(value, dict) else value for key, value in defaults.items()}
        with self._sessions() as session:
            for row in session.scalars(select(AppSettingsRow)):
                base = result.get(row.section)
                result[row.section] = {**base, **row.value} if isinstance(base, dict) else row.value
        return result

    def update_settings(self, section: str, value: dict[str, Any]) -> dict[str, Any]:
        now: datetime = self._clock()
        with self._sessions.begin() as session:
            row = session.get(AppSettingsRow, section)
            if row is None:
                row = AppSettingsRow(section=section, value=value, updated_at=now)
                session.add(row)
            else:
                row.value = value
                row.updated_at = now
        return value

    def active_profile(self) -> ContentProfile:
        with self._sessions() as session:
            row = session.scalar(select(ContentProfileRow).where(ContentProfileRow.is_active.is_(True)))
            if row is None:
                raise LookupError("No active Content Profile")
            return ContentProfile.model_validate(row.value)

    def replace_active_profile(self, profile: ContentProfile) -> ContentProfile:
        now: datetime = self._clock()
        value = profile.model_copy(update={"is_active": True, "updated_at": now})
        with self._sessions.begin() as session:
            for row in session.scalars(select(ContentProfileRow).with_for_update()):
                row.is_active = row.id == value.id
            row = session.get(ContentProfileRow, value.id)
            if row is None:
                row = ContentProfileRow(
                    id=value.id,
                    name=value.name,
                    is_active=True,
                    value=value.model_dump(mode="json"),
                    updated_at=now,
                )
                session.add(row)
            else:
                row.name = value.name
                row.is_active = True
                row.value = value.model_dump(mode="json")
                row.updated_at = now
        return value
