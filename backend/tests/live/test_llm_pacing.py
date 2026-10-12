"""Opt-in Lua checks on isolated Dragonfly keys; never calls an LLM."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from clipfactory.infrastructure.llm_governance import DragonflyLLMState

pytestmark = [
    pytest.mark.integration,
    pytest.mark.req("CF-REQ-667"),
    pytest.mark.req("CF-REQ-670"),
    pytest.mark.skipif(os.environ.get("LIVE_TESTS") != "1", reason="Requires explicitly enabled local Dragonfly"),
]
NOW = datetime(2026, 10, 8, tzinfo=UTC)
SCOPE = "https://example.test/api/v1"


@pytest.fixture
async def state() -> AsyncIterator[DragonflyLLMState]:
    service = DragonflyLLMState(os.environ.get("DRAGONFLY_URL", "redis://127.0.0.1:6380/0"))
    namespace = f"clipfactory:test:pacing:{uuid4().hex}"
    service.rpm_key = namespace + ":rpm"
    service.circuit_key = namespace + ":circuit"
    service.failure_key = namespace + ":failures"
    try:
        await service.seed({})
        yield service
    finally:
        keys = [
            service.rpm_key,
            service.circuit_key,
            service.failure_key,
            *(
                service._model_key(model, SCOPE) + suffix
                for model in ("a:free", "b:free", "c:free")
                for suffix in ("", ":circuit", ":failures")
            ),
        ]
        await service.client.delete(*keys)
        await service.client.aclose()


async def take(service: DragonflyLLMState, seconds: float, model: str = "a:free", limit: int = 20) -> tuple[int, int]:
    return await service.take(
        NOW + timedelta(seconds=seconds),
        limit,
        uuid4(),
        model=model,
        provider_scope=SCOPE,
    )


async def feedback(
    service: DragonflyLLMState,
    error: str | None,
    seconds: float,
    *,
    hint: float | None = None,
    maximum: float = 60,
) -> None:
    await service.record_result(
        error,
        now=NOW + timedelta(seconds=seconds),
        model="a:free",
        provider_scope=SCOPE,
        limit=20,
        max_delay=maximum,
        retry_after_seconds=hint,
        seconds=86400,
        threshold=3,
        open_seconds=300,
    )


async def test_model_cadence_slows_on_429_recovers_and_survives_backend_restart(state) -> None:
    assert await take(state, 0) == (1, 0)
    assert await take(state, 2) == (0, 1)
    assert await take(state, 2, "b:free") == (1, 0)
    await feedback(state, "rate_limited", 3)
    assert await take(state, 62) == (0, 1)
    assert await take(state, 5, "b:free") == (1, 0)
    assert float(await state.client.hget(state._model_key("a:free", SCOPE), "interval")) == 6
    assert await take(state, 63) == (1, 0)
    await feedback(state, None, 63)
    assert float(await state.client.hget(state._model_key("a:free", SCOPE), "interval")) == pytest.approx(5.4)
    restarted = DragonflyLLMState(os.environ.get("DRAGONFLY_URL", "redis://127.0.0.1:6380/0"))
    restarted.rpm_key, restarted.circuit_key, restarted.failure_key = (
        state.rpm_key,
        state.circuit_key,
        state.failure_key,
    )
    try:
        assert await take(restarted, 64) == (0, 5)
        for _ in range(30):
            await feedback(restarted, None, 64)
        assert float(await state.client.hget(state._model_key("a:free", SCOPE), "interval")) == 3
        ttl = await state.client.ttl(state._model_key("a:free", SCOPE))
        assert 86390 <= ttl <= 86400
    finally:
        await restarted.client.aclose()


async def test_account_window_cannot_be_bypassed_by_switching_models(state) -> None:
    assert await take(state, 0, "a:free", 2) == (1, 0)
    assert await take(state, 0, "b:free", 2) == (1, 0)
    assert await take(state, 0, "c:free", 2) == (0, 60)
    assert await state.client.zcard(state.rpm_key) == 2
    assert await take(state, 60, "c:free", 2) == (1, 0)


@pytest.mark.req("CF-REQ-671")
async def test_opaque_upstream_rejections_open_no_circuit(state) -> None:
    for seconds in range(5):
        await feedback(state, "upstream_bad_request", seconds)
    assert await state.client.get(state.circuit_key) is None
    assert (await take(state, 10, "a:free"))[0] == 1


@pytest.mark.req("CF-REQ-671")
async def test_model_failures_open_only_that_models_circuit(state) -> None:
    for seconds in range(3):
        await feedback(state, "http_502", seconds)
    assert await state.client.get(state.circuit_key) is None
    status, ttl = await take(state, 10, "a:free")
    assert status == -1
    assert 0 < ttl <= 300
    assert (await take(state, 10, "b:free"))[0] == 1


async def test_durable_recent_model_start_restores_baseline_after_operational_state_loss(state) -> None:
    result = await state.take(
        NOW + timedelta(seconds=1),
        20,
        uuid4(),
        model="a:free",
        provider_scope=SCOPE,
        last_started=NOW.timestamp(),
    )
    assert result == (0, 2)
    assert await state.client.zcard(state.rpm_key) == 0


async def test_endpoint_model_keys_are_isolated_without_exposing_identity(state) -> None:
    first = state._model_key("a:free", SCOPE)
    assert first == state._model_key("a:free", SCOPE + "/")
    assert first != state._model_key("b:free", SCOPE)
    assert first != state._model_key("a:free", "https://another.example.test")
    assert "a:free" not in first
    assert SCOPE not in first


async def test_repeated_limits_cannot_increase_cadence_beyond_configured_maximum(state) -> None:
    for _ in range(10):
        await feedback(state, "rate_limited", 0)
    assert float(await state.client.hget(state._model_key("a:free", SCOPE), "interval")) == 60


@pytest.mark.parametrize(("hint", "maximum", "cooldown"), [(None, 60, 60), (5, 60, 5), (90, 120, 90), (900, 120, 120)])
async def test_provider_cooldown_honours_hint_with_configured_bound(state, hint, maximum, cooldown) -> None:
    assert await take(state, 0) == (1, 0)
    await feedback(state, "rate_limited", 0, hint=hint, maximum=maximum)
    assert await take(state, cooldown - 1) == (0, 1)
    assert await take(state, cooldown) == (1, 0)


@pytest.mark.req("CF-REQ-671")
async def test_adaptation_does_not_bypass_transient_or_daily_circuit(state) -> None:
    for _ in range(3):
        await feedback(state, "rate_limited", 0)
    assert (await take(state, 100, "b:free"))[0] == -1
    await feedback(state, "llm_budget_exhausted", 0)
    assert await state.client.get(state.circuit_key) == "daily"
    assert (await take(state, 100, "b:free"))[0] == -1
