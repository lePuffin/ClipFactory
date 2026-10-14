"""Asset library repository contract."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from clipfactory.domain.models import Asset, AssetStatus


class AssetReader(Protocol):
    def get(self, asset_id: UUID) -> Asset | None: ...


class AssetRepository(Protocol):
    def save(self, asset: Asset) -> Asset: ...

    def get(self, asset_id: UUID) -> Asset | None: ...

    def by_hash(self, sha256: str) -> Asset | None: ...

    def list(
        self, *, status: AssetStatus | None = None, limit: int = 100, offset: int = 0, saved_only: bool = False
    ) -> list[Asset]: ...

    def count(self, *, status: AssetStatus | None = None, saved_only: bool = False) -> int: ...

    def external_for_run(self, run_id: UUID) -> list[Asset]: ...

    def update(
        self,
        asset_id: UUID,
        *,
        description: str | None = None,
        tags: list[str] | None = None,
        status: AssetStatus | None = None,
    ) -> Asset | None: ...
