"""Persistence for editable settings and the active Content Profile."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.db.models import AppSettingsRow, ContentProfileRow
from clipfactory.ports.configuration import ActiveProfileDeleteForbidden, ProfileNameConflict, ProfileNotFound


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
            return _profile(row)

    def profiles(self) -> list[dict[str, Any]]:
        with self._sessions() as session:
            return [
                _item(row)
                for row in session.scalars(
                    select(ContentProfileRow).order_by(ContentProfileRow.name, ContentProfileRow.id)
                )
            ]

    def create_profile(self, name: str, profile: ContentProfile, *, activate: bool = False) -> dict[str, Any]:
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                _check_name(rows, name)
                row = ContentProfileRow(
                    id=uuid4(), name=name, is_active=False, updated_at=now, value=profile.model_dump(mode="json")
                )
                session.add(row)
                if activate:
                    _activate(session, rows, row, now)
                _sync(row)
                session.flush()
                return _item(row)
        except IntegrityError as exc:
            self._raise_name_conflict(name, exc)
            raise

    def update_profile(
        self, profile_id: UUID, *, name: str | None = None, profile: ContentProfile | None = None
    ) -> dict[str, Any]:
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                row = _find_profile(rows, profile_id)
                if name is not None:
                    _check_name(rows, name, excluding=profile_id)
                    row.name = name
                if profile is not None:
                    row.value = profile.model_dump(mode="json")
                row.updated_at = self._clock()
                _sync(row)
                session.flush()
                return _item(row)
        except IntegrityError as exc:
            if name is not None:
                self._raise_name_conflict(name, exc)
            raise

    def activate_profile(self, profile_id: UUID) -> dict[str, Any]:
        with self._sessions.begin() as session:
            rows = _locked_profiles(session)
            row = _find_profile(rows, profile_id)
            _activate(session, rows, row, self._clock())
            session.flush()
            return _item(row)

    def delete_profile(self, profile_id: UUID) -> None:
        with self._sessions.begin() as session:
            row = _find_profile(_locked_profiles(session), profile_id)
            if row.is_active:
                raise ActiveProfileDeleteForbidden("The active Content Profile cannot be deleted")
            session.delete(row)

    def replace_active_profile(self, profile: ContentProfile) -> ContentProfile:
        now = self._clock()
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                row = next((row for row in rows if row.is_active), None)
                if row is None:
                    row = ContentProfileRow(id=profile.id, name=profile.name, is_active=False, value={}, updated_at=now)
                    session.add(row)
                _check_name(rows, profile.name, excluding=row.id)
                row.name = profile.name
                row.value = profile.model_dump(mode="json")
                _activate(session, rows, row, now)
                session.flush()
                return _profile(row)
        except IntegrityError as exc:
            self._raise_name_conflict(profile.name, exc)
            raise

    def _raise_name_conflict(self, name: str, error: IntegrityError) -> None:
        with self._sessions() as session:
            if session.scalar(select(ContentProfileRow.id).where(ContentProfileRow.name == name)) is not None:
                raise ProfileNameConflict("A Content Profile with that name already exists") from error


def _locked_profiles(session: Session) -> list[ContentProfileRow]:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("LOCK TABLE content_profile IN SHARE ROW EXCLUSIVE MODE"))
    return list(session.scalars(select(ContentProfileRow).order_by(ContentProfileRow.id).with_for_update()))


def _find_profile(rows: list[ContentProfileRow], profile_id: UUID) -> ContentProfileRow:
    for row in rows:
        if row.id == profile_id:
            return row
    raise ProfileNotFound("Content Profile was not found")


def _check_name(rows: list[ContentProfileRow], name: str, *, excluding: UUID | None = None) -> None:
    if any(row.name == name and row.id != excluding for row in rows):
        raise ProfileNameConflict("A Content Profile with that name already exists")


def _profile(row: ContentProfileRow) -> ContentProfile:
    return ContentProfile.model_validate(row.value).model_copy(
        update={
            "id": row.id,
            "name": row.name,
            "is_active": row.is_active,
            "updated_at": row.updated_at.replace(tzinfo=UTC) if row.updated_at.tzinfo is None else row.updated_at,
        }
    )


def _sync(row: ContentProfileRow) -> None:
    row.value = _profile(row).model_dump(mode="json")


def _item(row: ContentProfileRow) -> dict[str, Any]:
    value = _profile(row).model_dump(mode="json")
    return {
        "id": value["id"],
        "name": value["name"],
        "is_active": value["is_active"],
        "updated_at": value["updated_at"],
        "profile": value,
    }


def _activate(session: Session, rows: list[ContentProfileRow], target: ContentProfileRow, now: datetime) -> None:
    for row in rows:
        if row.id != target.id and row.is_active:
            row.is_active = False
            row.updated_at = now
            _sync(row)
    # Release the partial unique index before activating another row.
    session.flush()
    target.is_active = True
    target.updated_at = now
    _sync(target)
