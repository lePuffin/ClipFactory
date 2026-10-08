"""Application-facing Run and event repository contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from clipfactory.domain.models import RunTrigger


class ActiveRunConflict(RuntimeError):
    def __init__(self, active_run_id: UUID | None = None) -> None:
        super().__init__("A Run is already queued or running")
        self.active_run_id = active_run_id


class LLMBudgetExhausted(RuntimeError):
    pass


class RunNotFound(LookupError):
    pass


class RunContinuationConflict(RuntimeError):
    pass


class RunReader(Protocol):
    def get(self, run_id: UUID) -> dict[str, Any]: ...

    def active(self) -> dict[str, Any] | None: ...

    def list(
        self, *, limit: int = 50, status: str | None = None, trigger: str | None = None
    ) -> list[dict[str, Any]]: ...

    def events(self, run_id: UUID, *, after_sequence: int = 0) -> list[dict[str, Any]]: ...


class RunCreator(Protocol):
    def create(
        self,
        trigger: RunTrigger,
        *,
        manual_url: str | None,
        settings_snapshot: dict[str, Any],
    ) -> dict[str, Any]: ...


class GenerationReservations(Protocol):
    def reserve_generation_start(
        self, run_id: UUID, *, provider: str, limit: int, segment_index: int, now: datetime
    ) -> bool: ...
