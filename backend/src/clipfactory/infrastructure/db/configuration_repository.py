"""Persistence for editable settings and the active Content Profile."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.db.models import AppSettingsRow, ContentProfileRow
from clipfactory.infrastructure.media.profile_branding import allocate_branding_folder, profile_branding_directory
from clipfactory.infrastructure.research_defaults import materialize_research, new_profile_research
from clipfactory.ports.configuration import ActiveProfileDeleteForbidden, ProfileNameConflict, ProfileNotFound


class ConfigurationRepository:
    def __init__(self, sessions: sessionmaker, *, clock: Any, branding_root: Path | None = None) -> None:
        self._sessions = sessions
        self._clock = clock
        self._last_now: datetime | None = None
        self._branding_root = branding_root

    def _ensure_branding(self, row: ContentProfileRow) -> None:
        if self._branding_root is not None:
            folder = row.value.get("branding_folder")
            if folder is None:
                folder = allocate_branding_folder(self._branding_root, row.id, row.name)
            profile_branding_directory(self._branding_root, row.id, folder)
            row.value = {**row.value, "branding_folder": folder}

    def initialize_branding(self) -> None:
        with self._sessions.begin() as session:
            for row in _locked_profiles(session):
                self._ensure_branding(row)

    def initialize_research(self) -> None:
        """Compatibility for existing installations; never touch Run snapshots."""
        with self._sessions.begin() as session:
            legacy = session.get(AppSettingsRow, "research")
            for row in _locked_profiles(session):
                row.value = materialize_research(row.value, legacy.value if legacy else {})

    def _now(self) -> datetime:
        now: datetime = self._clock()
        if self._last_now is not None and now <= self._last_now:
            now = self._last_now + timedelta(microseconds=1)
        self._last_now = now
        return now

    def settings(self, defaults: dict[str, Any]) -> dict[str, Any]:
        result = {key: dict(value) if isinstance(value, dict) else value for key, value in defaults.items()}
        result.pop("research", None)
        with self._sessions() as session:
            for row in session.scalars(select(AppSettingsRow)):
                if row.section == "research":
                    continue
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
            row = session.scalar(
                select(ContentProfileRow)
                .where(ContentProfileRow.is_active.is_(True))
                .order_by(ContentProfileRow.updated_at.desc())
            )
            if row is None:
                row = session.scalar(select(ContentProfileRow).order_by(ContentProfileRow.updated_at.desc()))
                if row is None:
                    raise LookupError("No active Content Profile")
            return _profile(row)

    def active_profiles(self) -> list[ContentProfile]:
        with self._sessions() as session:
            return [
                _profile(row)
                for row in session.scalars(
                    select(ContentProfileRow)
                    .where(ContentProfileRow.is_active.is_(True))
                    .order_by(ContentProfileRow.name)
                )
            ]

    def profiles(self) -> list[dict[str, Any]]:
        with self._sessions() as session:
            return [
                _item(row)
                for row in session.scalars(
                    select(ContentProfileRow).order_by(ContentProfileRow.name, ContentProfileRow.id)
                )
            ]

    def create_profile(self, name: str, profile: ContentProfile, *, activate: bool = False) -> dict[str, Any]:
        profile = new_profile_research(profile)
        now = self._now()
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                _check_name(rows, name)
                row = ContentProfileRow(
                    id=uuid4(), name=name, is_active=activate, updated_at=now, value=profile.model_dump(mode="json")
                )
                row.value = {**row.value, "branding_folder": None}
                session.add(row)
                _sync(row)
                session.flush()
                self._ensure_branding(row)
                return _item(row)
        except IntegrityError as exc:
            self._raise_name_conflict(name, exc)
            raise

    def update_profile(
        self,
        profile_id: UUID,
        *,
        name: str | None = None,
        profile: ContentProfile | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                row = _find_profile(rows, profile_id)
                if name is not None:
                    _check_name(rows, name, excluding=profile_id)
                    row.name = name
                if profile is not None:
                    profile = new_profile_research(profile)
                    row.value = {**profile.model_dump(mode="json"), "branding_folder": row.value.get("branding_folder")}
                if is_active is not None:
                    row.is_active = is_active
                row.updated_at = self._now()
                _sync(row)
                session.flush()
                return _item(row)
        except IntegrityError as exc:
            if name is not None:
                self._raise_name_conflict(name, exc)
            raise

    def activate_profile(self, profile_id: UUID, *, is_active: bool = True) -> dict[str, Any]:
        with self._sessions.begin() as session:
            rows = _locked_profiles(session)
            row = _find_profile(rows, profile_id)
            row.is_active = is_active
            row.updated_at = self._now()
            _sync(row)
            session.flush()
            return _item(row)

    def deactivate_profile(self, profile_id: UUID) -> dict[str, Any]:
        return self.activate_profile(profile_id, is_active=False)

    def delete_profile(self, profile_id: UUID) -> None:
        with self._sessions.begin() as session:
            row = _find_profile(_locked_profiles(session), profile_id)
            if row.is_active:
                raise ActiveProfileDeleteForbidden("The active Content Profile cannot be deleted")
            session.delete(row)

    def replace_active_profile(self, profile: ContentProfile) -> ContentProfile:
        profile = new_profile_research(profile)
        now = self._now()
        try:
            with self._sessions.begin() as session:
                rows = _locked_profiles(session)
                row = max((row for row in rows if row.is_active), key=lambda row: row.updated_at, default=None)
                if row is None:
                    row = ContentProfileRow(id=profile.id, name=profile.name, is_active=True, value={}, updated_at=now)
                    session.add(row)
                _check_name(rows, profile.name, excluding=row.id)
                row.name = profile.name
                row.value = {**profile.model_dump(mode="json"), "branding_folder": row.value.get("branding_folder")}
                row.is_active = True
                row.updated_at = now
                _sync(row)
                session.flush()
                self._ensure_branding(row)
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
