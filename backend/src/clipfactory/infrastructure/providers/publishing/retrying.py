"""Bounded retry decorator for Publisher calls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.publishing import PlatformMetrics, PublicationRequest, PublicationResult, Publisher

ResultT = TypeVar("ResultT")


class RetryingPublisher:
    def __init__(
        self,
        publisher: Publisher,
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 2.0,
        max_delay_seconds: float = 60.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._publisher = publisher
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._max_delay_seconds = max_delay_seconds
        self._sleep = sleep
        self.platform = publisher.platform
        self.name = publisher.name

    def is_configured(self) -> bool:
        return self._publisher.is_configured()

    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult:
        return await self._retry(lambda: self._publisher.publish(request, clip_file))

    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics:
        return await self._retry(lambda: self._publisher.fetch_metrics(platform_post_id))

    async def _retry(self, call: Callable[[], Awaitable[ResultT]]) -> ResultT:
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await call()
            except ProviderError as exc:
                if not exc.transient or attempt == self._max_attempts:
                    raise
                delay = min(self._base_delay_seconds * (2 ** (attempt - 1)), self._max_delay_seconds)
                await self._sleep(delay)
        raise RuntimeError("unreachable")
