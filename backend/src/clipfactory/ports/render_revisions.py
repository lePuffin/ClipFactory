"""Durable evidence and output contract for saved-content rendering."""

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class RenderRevisionRepository(Protocol):
    def context(self, clip_id: UUID) -> dict[str, Any]: ...

    def save_revision(self, revision_id: UUID, clip_id: UUID, value: dict[str, Any], now: datetime) -> None: ...
