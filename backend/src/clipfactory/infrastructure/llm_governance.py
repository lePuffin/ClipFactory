"""PostgreSQL usage ledger and Dragonfly-only RPM/circuit operational state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from clipfactory.infrastructure.db.models import CostEntryRow, LLMRequestRow, RunRow
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMResult

_TAKE_SLOT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return {-1, redis.call('TTL', KEYS[2])} end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - 60)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
 local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
 return {0, math.ceil(first[2] + 60 - ARGV[1])}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], 65)
return {1, 0}
"""


class DragonflyLLMState:
    def __init__(self, url: str) -> None:
        self.client = Redis.from_url(url, socket_timeout=5, socket_connect_timeout=5, decode_responses=True)
        self.rpm_key = "clipfactory:llm:rpm:openai_compatible"
        self.circuit_key = "clipfactory:llm:circuit:openai_compatible"
        self.failure_key = "clipfactory:llm:circuit-failures:openai_compatible"

    async def seed(self, recent: dict[str, float]) -> None:
        await self.client.ping()
        if recent:
            await self.client.zadd(self.rpm_key, recent)
            await self.client.expire(self.rpm_key, 65)

    async def take(self, now: datetime, limit: int, request_id: UUID) -> tuple[int, int]:
        value = await self.client.execute_command(
            "EVAL",
            _TAKE_SLOT,
            2,
            self.rpm_key,
            self.circuit_key,
            str(now.timestamp()),
            str(limit),
            str(request_id),
        )
        if not isinstance(value, list) or len(value) != 2:
            raise RedisError("Dragonfly returned an invalid limiter response")
        return int(value[0]), int(value[1])

    async def record_result(self, error: str | None, *, seconds: int, threshold: int, open_seconds: int) -> None:
        if error == "llm_budget_exhausted":
            await self.client.set(self.circuit_key, "daily", ex=max(1, seconds))
        elif error in {"rate_limited", "timeout", "network_error", "http_500", "http_502", "http_503"}:
            failures = await self.client.incr(self.failure_key)
            await self.client.expire(self.failure_key, open_seconds)
            if failures >= threshold:
                await self.client.set(self.circuit_key, "transient", ex=open_seconds)
        elif error is None:
            await self.client.delete(self.failure_key)


class GovernedLLMCalls:
    def __init__(
        self,
        sessions: sessionmaker,
        settings: EnvironmentSettings,
        state: Any,
        *,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.state = state
        self.clock = clock
        self.sleep = sleep
        self._seeded = False
        self._lock = asyncio.Lock()

    def _limits(self, run_id: UUID) -> dict[str, Any]:
        now = self.clock()
        with self.sessions() as session:
            run = session.get(RunRow, run_id)
            if run is None:
                raise ProviderError("llm_governance_unavailable", "Run usage context is missing", transient=False)
            policy = run.settings_snapshot.get("llm", {})
            budget = run.settings_snapshot.get("budget", {})
            local = now.astimezone(ZoneInfo(policy.get("daily_reset_timezone", "UTC")))
            day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
            count = (
                session.scalar(select(func.count()).select_from(LLMRequestRow).where(LLMRequestRow.run_id == run_id))
                or 0
            )
            day_count = (
                session.scalar(
                    select(func.count()).select_from(LLMRequestRow).where(LLMRequestRow.started_at >= day_start)
                )
                or 0
            )
            recent = list(
                session.scalars(select(LLMRequestRow).where(LLMRequestRow.started_at > now - timedelta(seconds=60)))
            )
            if count >= int(policy.get("max_requests_per_run", 8)):
                raise ProviderError("llm_budget_exhausted", "Run reached its hard LLM request cap", transient=False)
            if day_count >= int(policy.get("requests_per_day", 50)):
                raise ProviderError("llm_budget_exhausted", "Daily LLM request budget is exhausted", transient=False)
            total = session.scalar(
                select(func.coalesce(func.sum(CostEntryRow.amount), 0)).where(CostEntryRow.run_id == run_id)
            )
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly = session.scalar(
                select(func.coalesce(func.sum(CostEntryRow.amount), 0)).where(CostEntryRow.created_at >= month_start)
            )
            if Decimal(str(total)) >= Decimal(str(budget.get("max_cost_per_clip", 1))) or Decimal(
                str(monthly)
            ) >= Decimal(str(budget.get("max_cost_per_month", 30))):
                raise ProviderError("budget_exceeded", "Recorded Clip/month budget is exhausted", transient=False)
            return {
                "rpm": int(policy.get("requests_per_minute", 20)),
                "recent": {str(row.id): row.started_at.timestamp() for row in recent},
                "reset_seconds": int((day_start + timedelta(days=1) - now).total_seconds()),
                "threshold": int(policy.get("circuit_failure_threshold", 3)),
                "open_seconds": int(policy.get("circuit_open_seconds", 300)),
            }

    async def begin(self, run_id: UUID, task: str, role: Literal["default", "evaluation"]) -> UUID:
        model = self.settings.llm_model_evaluation if role == "evaluation" else self.settings.llm_model
        model = model or self.settings.llm_model
        if not model.endswith(":free"):
            raise ProviderError(
                "budget_exceeded",
                "Paid LLM dispatch requires verified price reservations; select a free model for this rollout",
                transient=False,
            )
        request_id = uuid4()
        async with self._lock:
            while True:
                limits = await asyncio.to_thread(self._limits, run_id)
                try:
                    if not self._seeded:
                        await self.state.seed(limits["recent"])
                        self._seeded = True
                    permitted, wait_seconds = await self.state.take(self.clock(), limits["rpm"], request_id)
                except (TimeoutError, RedisError, OSError) as exc:
                    raise ProviderError(
                        "llm_governance_unavailable",
                        "Dragonfly request limiter is unavailable; no model call was sent",
                        transient=False,
                    ) from exc
                if permitted < 0:
                    raise ProviderError(
                        "llm_unavailable", "LLM circuit is open; no model call was sent", transient=False
                    )
                if permitted == 0:
                    await self.sleep(max(0.1, wait_seconds))
                    continue
                break

            def record() -> None:
                with self.sessions.begin() as session:
                    session.add(
                        LLMRequestRow(
                            id=request_id,
                            run_id=run_id,
                            task=task,
                            provider="openai_compatible",
                            model=model,
                            attempt_kind="call",
                            started_at=self.clock(),
                            outcome="started",
                            rate_limit_headers={},
                        )
                    )

            await asyncio.to_thread(record)
        return request_id

    async def finish(self, request_id: UUID, result: LLMResult[Any] | None, error_code: str | None) -> None:
        def record() -> UUID:
            with self.sessions.begin() as session:
                row = session.get(LLMRequestRow, request_id)
                if row is None or row.run_id is None:
                    raise ValueError("LLM request ledger entry is missing")
                row.finished_at = self.clock()
                row.outcome = "succeeded" if error_code is None else error_code
                if result:
                    row.prompt_tokens, row.completion_tokens = result.prompt_tokens, result.completion_tokens
                    row.cost_reported = result.reported_cost
                return row.run_id

        run_id = await asyncio.to_thread(record)
        try:
            limits = await asyncio.to_thread(self._limits, run_id)
        except ProviderError:
            limits = {
                "reset_seconds": 86400 - (self.clock().hour * 3600 + self.clock().minute * 60),
                "threshold": 3,
                "open_seconds": 300,
            }
        await self.state.record_result(
            error_code,
            seconds=limits["reset_seconds"],
            threshold=limits["threshold"],
            open_seconds=limits["open_seconds"],
        )
