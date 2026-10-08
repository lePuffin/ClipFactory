"""SQLAlchemy adapter for the reusable Asset library."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import Asset, AssetStatus, MusicInfo, Provenance
from clipfactory.infrastructure.db.models import AssetRow


class AssetRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def save(self, asset: Asset) -> Asset:
        with self.sessions.begin() as session:
            existing = session.scalar(select(AssetRow).where(AssetRow.sha256 == asset.sha256))
            if existing is not None:
                return _to_domain(existing)
            row = AssetRow(
                id=asset.id,
                media_type=asset.media_type,
                category=asset.category,
                storage_key=asset.storage_key,
                sha256=asset.sha256,
                mime_type=asset.mime_type,
                size_bytes=asset.size_bytes,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                description=asset.description,
                tags=asset.tags,
                subjects=asset.subjects,
                provenance=asset.provenance.model_dump(mode="json"),
                music=asset.music.model_dump(mode="json") if asset.music else None,
                reusable=asset.reusable,
                status=asset.status.value,
                usage_count=asset.usage_count,
                last_used_at=asset.last_used_at,
                created_at=asset.created_at,
            )
            session.add(row)
            session.flush()
            return asset

    def get(self, asset_id: UUID) -> Asset | None:
        with self.sessions() as session:
            row = session.get(AssetRow, asset_id)
            return _to_domain(row) if row is not None else None

    def by_hash(self, sha256: str) -> Asset | None:
        with self.sessions() as session:
            row = session.scalar(select(AssetRow).where(AssetRow.sha256 == sha256))
            return _to_domain(row) if row is not None else None

    def list(self, *, status: AssetStatus | None = None, limit: int = 100) -> list[Asset]:
        statement = select(AssetRow).order_by(AssetRow.created_at.desc()).limit(max(1, min(limit, 500)))
        if status is not None:
            statement = statement.where(AssetRow.status == status.value)
        with self.sessions() as session:
            return [_to_domain(row) for row in session.scalars(statement)]

    def update(
        self,
        asset_id: UUID,
        *,
        description: str | None = None,
        tags: list[str] | None = None,
        status: AssetStatus | None = None,
    ) -> Asset | None:
        with self.sessions.begin() as session:
            row = session.scalar(select(AssetRow).where(AssetRow.id == asset_id).with_for_update())
            if row is None:
                return None
            if description is not None:
                row.description = description
            if tags is not None:
                row.tags = sorted({tag.strip().casefold() for tag in tags if tag.strip()})
            if status is not None:
                row.status = status.value
            session.flush()
            return _to_domain(row)


def _to_domain(row: AssetRow) -> Asset:
    provenance: dict[str, Any] = dict(row.provenance)
    return Asset(
        id=row.id,
        media_type=row.media_type,
        category=row.category,
        storage_key=row.storage_key,
        sha256=row.sha256,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        width=row.width,
        height=row.height,
        duration_seconds=row.duration_seconds,
        description=row.description,
        tags=row.tags,
        subjects=row.subjects,
        provenance=Provenance.model_validate(provenance),
        music=MusicInfo.model_validate(row.music) if row.music else None,
        reusable=row.reusable,
        status=AssetStatus(row.status),
        usage_count=row.usage_count,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )
