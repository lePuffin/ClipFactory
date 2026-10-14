"""Provider-neutral pre-dispatch request accounting and limit control."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from clipfactory.ports.llm import LLMModelRole, LLMResult


class LLMGovernance(Protocol):
    async def begin(
        self,
        run_id: UUID,
        task: str,
        role: LLMModelRole,
        *,
        on_wait: Callable[[str, float], Awaitable[None]] | None = None,
    ) -> UUID: ...

    async def finish(
        self,
        request_id: UUID,
        result: LLMResult[Any] | None,
        error_code: str | None,
        *,
        retry_after_seconds: float | None = None,
    ) -> None: ...
