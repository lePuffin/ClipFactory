"""PostgreSQL usage ledger and Dragonfly-only RPM/circuit operational state."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from clipfactory.infrastructure.db.models import CostEntryRow, LLMRequestRow, RunRow
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMModelRole, LLMResult

_TAKE_SLOT = """
if redis.call('EXISTS', KEYS[2]) == 1 then return {-1, redis.call('TTL', KEYS[2])} end
if redis.call('EXISTS', KEYS[4]) == 1 then return {-1, redis.call('TTL', KEYS[4])} end
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - 60)
local baseline = 60 / tonumber(ARGV[2])
local interval = math.max(baseline, tonumber(redis.call('HGET', KEYS[3], 'interval') or baseline))
local next_allowed = math.max(
 tonumber(redis.call('HGET', KEYS[3], 'next_allowed') or 0),
 tonumber(ARGV[4]) + interval
)
if next_allowed > tonumber(ARGV[1]) then
 return {0, math.ceil(next_allowed - tonumber(ARGV[1]))}
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
 local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
 return {0, math.ceil(first[2] + 60 - ARGV[1])}
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], 65)
redis.call('HSET', KEYS[3], 'interval', interval, 'next_allowed', tonumber(ARGV[1]) + interval)
redis.call('EXPIRE', KEYS[3], 86400)
return {1, 0}
"""

_ADAPT_MODEL = """
local baseline = 60 / tonumber(ARGV[2])
local interval = math.max(baseline, tonumber(redis.call('HGET', KEYS[1], 'interval') or baseline))
if ARGV[3] == 'rate_limited' then
 interval = math.min(math.max(baseline, tonumber(ARGV[4])), interval * 2)
 local cooldown = tonumber(ARGV[5])
 if cooldown <= 0 then cooldown = tonumber(ARGV[4]) end
 cooldown = math.min(cooldown, tonumber(ARGV[4]))
 local next_allowed = math.max(
  tonumber(redis.call('HGET', KEYS[1], 'next_allowed') or 0),
  tonumber(ARGV[1]) + cooldown
 )
 redis.call('HSET', KEYS[1], 'next_allowed', next_allowed)
elseif ARGV[3] == '' then
 interval = math.max(baseline, interval * 0.9)
end
redis.call('HSET', KEYS[1], 'interval', interval)
redis.call('EXPIRE', KEYS[1], 86400)
return 1
"""
logger = logging.getLogger(__name__)


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

    def _model_key(self, model: str, provider_scope: str) -> str:
        identity = hashlib.sha256(f"{provider_scope.rstrip('/')}|{model}".encode()).hexdigest()
        return f"{self.rpm_key}:model:{identity}"

    async def take(
        self,
        now: datetime,
        limit: int,
        request_id: UUID,
        *,
        model: str,
        provider_scope: str,
        last_started: float = 0,
    ) -> tuple[int, int]:
        value = await self.client.execute_command(
            "EVAL",
            _TAKE_SLOT,
            4,
            self.rpm_key,
            self.circuit_key,
            self._model_key(model, provider_scope),
            self._model_key(model, provider_scope) + ":circuit",
            str(now.timestamp()),
            str(limit),
            str(request_id),
            str(last_started),
        )
        if not isinstance(value, list) or len(value) != 2:
            raise RedisError("Dragonfly returned an invalid limiter response")
        return int(value[0]), int(value[1])

    async def record_result(
        self,
        error: str | None,
        *,
        seconds: int,
        threshold: int,
        open_seconds: int,
        now: datetime,
        model: str,
        provider_scope: str,
        limit: int,
        max_delay: float,
        retry_after_seconds: float | None = None,
    ) -> None:
        hint = retry_after_seconds or 0
        if not math.isfinite(hint):
            hint = 0
        await self.client.execute_command(
            "EVAL",
            _ADAPT_MODEL,
            1,
            self._model_key(model, provider_scope),
            str(now.timestamp()),
            str(limit),
            error or "",
            str(max_delay),
            str(hint),
        )
        if error == "llm_budget_exhausted":
            await self.client.set(self.circuit_key, "daily", ex=max(1, seconds))
        elif error in _SHARED_CIRCUIT_ERRORS or error in _MODEL_CIRCUIT_ERRORS:
            # CF-REQ-671: account-wide signals trip the shared circuit; model-identifying ones only that model's.
            model_key = self._model_key(model, provider_scope)
            failure_key, circuit_key = (
                (self.failure_key, self.circuit_key)
                if error in _SHARED_CIRCUIT_ERRORS
                else (model_key + ":failures", model_key + ":circuit")
            )
            failures = await self.client.incr(failure_key)
            await self.client.expire(failure_key, open_seconds)
            if failures >= threshold:
                await self.client.set(circuit_key, "transient", ex=open_seconds)
        elif error is None:
            await self.client.delete(self.failure_key, self._model_key(model, provider_scope) + ":failures")


_SHARED_CIRCUIT_ERRORS = frozenset({"rate_limited", "timeout", "network_error"})
# Opaque `upstream_bad_request` is input-specific moderation, not an outage, so it never trips a circuit.
_MODEL_CIRCUIT_ERRORS = frozenset({"http_500", "http_502", "http_503", "free_router_upstream_rejection"})

# OpenRouter's free router only dispatches to $0 models; other router IDs (e.g. openrouter/auto) may pick paid ones.
FREE_ROUTER_MODELS = frozenset({"openrouter/free"})


def is_free_model(model: str) -> bool:
    return model.endswith(":free") or model in FREE_ROUTER_MODELS


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

    def _limits(self, run_id: UUID, *, check_budget: bool = True) -> dict[str, Any]:
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
            if check_budget and count >= int(policy.get("max_requests_per_run", 8)):
                raise ProviderError("llm_budget_exhausted", "Run reached its hard LLM request cap", transient=False)
            if check_budget and day_count >= int(policy.get("requests_per_day", 50)):
                raise ProviderError("llm_budget_exhausted", "Daily LLM request budget is exhausted", transient=False)
            total = session.scalar(
                select(func.coalesce(func.sum(CostEntryRow.amount), 0)).where(CostEntryRow.run_id == run_id)
            )
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly = session.scalar(
                select(func.coalesce(func.sum(CostEntryRow.amount), 0)).where(CostEntryRow.created_at >= month_start)
            )
            if check_budget and (
                Decimal(str(total)) >= Decimal(str(budget.get("max_cost_per_clip", 1)))
                or Decimal(str(monthly)) >= Decimal(str(budget.get("max_cost_per_month", 30)))
            ):
                raise ProviderError("budget_exceeded", "Recorded Clip/month budget is exhausted", transient=False)
            return {
                "rpm": int(policy.get("requests_per_minute", 20)),
                "recent": {str(row.id): row.started_at.timestamp() for row in recent},
                "model_recent": {
                    model: max(row.started_at.timestamp() for row in recent if row.model == model)
                    for model in {row.model for row in recent}
                },
                "reset_seconds": int((day_start + timedelta(days=1) - now).total_seconds()),
                "threshold": int(policy.get("circuit_failure_threshold", 3)),
                "open_seconds": int(policy.get("circuit_open_seconds", 300)),
                "max_delay": float(run.settings_snapshot.get("providers", {}).get("call_retry_max_delay_seconds", 60)),
            }

    async def begin(
        self,
        run_id: UUID,
        task: str,
        role: LLMModelRole,
        *,
        on_wait: Callable[[str, float], Awaitable[None]] | None = None,
    ) -> UUID:
        model = self.settings.model_for_role(role)
        if not is_free_model(model):
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
                    permitted, wait_seconds = await self.state.take(
                        self.clock(),
                        limits["rpm"],
                        request_id,
                        model=model,
                        provider_scope=self.settings.llm_base_url,
                        last_started=limits["model_recent"].get(model, 0),
                    )
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
                    logger.info("LLM %s for model %s waiting %ss for request pacing", task, model, wait_seconds)
                    if on_wait is not None:
                        await on_wait(model, max(0.1, wait_seconds))
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

    async def finish(
        self,
        request_id: UUID,
        result: LLMResult[Any] | None,
        error_code: str | None,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        def record() -> tuple[UUID, str]:
            with self.sessions.begin() as session:
                row = session.get(LLMRequestRow, request_id)
                if row is None or row.run_id is None:
                    raise ValueError("LLM request ledger entry is missing")
                row.finished_at = self.clock()
                row.outcome = "succeeded" if error_code is None else error_code
                if retry_after_seconds is not None and math.isfinite(retry_after_seconds):
                    row.rate_limit_headers = {"Retry-After": str(max(0, retry_after_seconds))}
                if result:
                    row.prompt_tokens, row.completion_tokens = result.prompt_tokens, result.completion_tokens
                    row.cost_reported = result.reported_cost
                return row.run_id, row.model

        run_id, model = await asyncio.to_thread(record)
        limits = await asyncio.to_thread(self._limits, run_id, check_budget=False)
        try:
            await self.state.record_result(
                error_code,
                seconds=limits["reset_seconds"],
                threshold=limits["threshold"],
                open_seconds=limits["open_seconds"],
                now=self.clock(),
                model=model,
                provider_scope=self.settings.llm_base_url,
                limit=limits["rpm"],
                max_delay=limits["max_delay"],
                retry_after_seconds=retry_after_seconds,
            )
        except (TimeoutError, RedisError, OSError) as exc:
            raise ProviderError(
                "llm_governance_unavailable",
                "LLM result was recorded, but Dragonfly pacing/circuit update failed",
                transient=False,
            ) from exc
