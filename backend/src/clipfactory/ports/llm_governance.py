"""Provider-neutral pre-dispatch request accounting and limit control."""

from typing import Any, Literal, Protocol
from uuid import UUID

from clipfactory.ports.llm import LLMResult


class LLMGovernance(Protocol):
    async def begin(self, run_id: UUID, task: str, role: Literal["default", "evaluation"]) -> UUID: ...

    async def finish(self, request_id: UUID, result: LLMResult[Any] | None, error_code: str | None) -> None: ...
