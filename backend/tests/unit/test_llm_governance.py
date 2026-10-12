import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import create_engine

from clipfactory.domain.models import RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import LLMRequestRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.llm_governance import GovernedLLMCalls
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMResult


class Answer(BaseModel):
    answer: str


def _settings(database: Any, model: str) -> EnvironmentSettings:
    values: dict[str, Any] = {"DATABASE_URL": f"sqlite:///{database}", "LLM_MODEL": model}
    return EnvironmentSettings(**values)


class FakeDragonfly:
    def __init__(self) -> None:
        self.seeded = False
        self.takes = 0
        self.errors: list[str | None] = []
        self.models: list[str] = []
        self.feedback: list[dict[str, Any]] = []

    async def seed(self, recent: dict[str, float]) -> None:
        self.seeded = True

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
        self.takes += 1
        self.models.append(model)
        return 1, 0

    async def record_result(self, error: str | None, **kwargs: Any) -> None:
        self.errors.append(error)
        self.feedback.append(kwargs)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-667")
@pytest.mark.req("CF-REQ-669")
@pytest.mark.asyncio
async def test_governance_persists_a_request_before_dispatch_and_its_result(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'governance.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "governance.db", "nvidia/nemotron-3-super-120b-a12b:free")
    snapshot = {
        "llm": {"requests_per_day": 50, "requests_per_minute": 20, "max_requests_per_run": 8},
        "budget": {"max_cost_per_clip": 1, "max_cost_per_month": 30},
    }
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot=snapshot)
    run_id = UUID(run["run_id"])
    state = FakeDragonfly()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: datetime.now(UTC))

    request_id = await service.begin(run_id, "rank_stories", "default")
    with sessions() as session:
        row = session.get(LLMRequestRow, request_id)
        assert row is not None
        assert row.outcome == "started"
        assert row.run_id == run_id
        assert row.task == "rank_stories"
    assert state.seeded
    assert state.takes == 1

    result = LLMResult(Answer(answer="ok"), "openai_compatible", settings.llm_model, 12, 3)
    await service.finish(request_id, result, None)
    with sessions() as session:
        row = session.get(LLMRequestRow, request_id)
        assert row is not None
        assert row.outcome == "succeeded"
        assert row.prompt_tokens == 12
        assert row.completion_tokens == 3
    assert state.errors == [None]
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-667")
@pytest.mark.parametrize("failure", ["unavailable", "cancelled"])
async def test_failed_or_cancelled_pacing_records_no_dispatch(tmp_path, failure) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'blocked.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "blocked.db", "vendor/free:free")
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})

    class BlockedState(FakeDragonfly):
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
            if failure == "unavailable":
                raise RedisError("Not available")
            return 0, 60

    async def cancelled_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    service = GovernedLLMCalls(
        sessions,
        settings,
        BlockedState(),
        clock=lambda: datetime.now(UTC),
        sleep=cancelled_sleep,
    )
    if failure == "unavailable":
        with pytest.raises(ProviderError) as caught:
            await service.begin(UUID(run["run_id"]), "evaluate_clip", "evaluation")
        assert caught.value.code == "llm_governance_unavailable"
    else:
        with pytest.raises(asyncio.CancelledError):
            await service.begin(UUID(run["run_id"]), "evaluate_clip", "evaluation")
    with sessions() as session:
        assert list(session.query(LLMRequestRow)) == []
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-666")
@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["vendor/paid-model", "openrouter/auto", "openrouter/free-but-paid", "free"])
async def test_governance_blocks_paid_models_without_price_reservation(tmp_path, model) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'paid.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "paid.db", model)
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    state = FakeDragonfly()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: datetime.now(UTC))

    with pytest.raises(ProviderError, match="verified price reservations") as caught:
        await service.begin(UUID(run["run_id"]), "rank_stories", "default")

    assert caught.value.code == "budget_exceeded"
    assert state.takes == 0
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-666")
@pytest.mark.asyncio
async def test_openrouter_free_router_is_dispatched_as_a_free_model(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'router.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "router.db", "openrouter/free")
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    state = FakeDragonfly()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: datetime.now(UTC))

    request_id = await service.begin(UUID(run["run_id"]), "rank_stories", "default")

    assert state.takes == 1
    with sessions() as session:
        row = session.get(LLMRequestRow, request_id)
        assert row is not None
        assert row.model == "openrouter/free"
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-667")
@pytest.mark.req("CF-REQ-669")
async def test_rpm_wait_records_no_outbound_attempt_until_slot_is_available(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'paced.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "paced.db", "vendor/free:free")
    run = RunRepository(sessions).create(
        RunTrigger.RUN_NOW,
        manual_url=None,
        settings_snapshot={"llm": {"requests_per_minute": 2}},
    )
    now = datetime(2026, 10, 8, tzinfo=UTC)
    delays = []

    class FullWindow(FakeDragonfly):
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
            assert limit == 2
            self.takes += 1
            return (0, 60) if self.takes == 1 else (1, 0)

    async def advance(seconds: float) -> None:
        nonlocal now
        with sessions() as session:
            assert list(session.query(LLMRequestRow)) == []
        delays.append(seconds)
        now += timedelta(seconds=seconds)

    state = FullWindow()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: now, sleep=advance)
    notices = []

    async def notice(model: str, seconds: float) -> None:
        notices.append((model, seconds))

    request_id = await service.begin(UUID(run["run_id"]), "review_media_candidates", "default", on_wait=notice)
    assert delays == [60]
    assert notices == [(settings.llm_model, 60)]
    assert state.takes == 2
    with sessions() as session:
        row = session.get(LLMRequestRow, request_id)
        assert row is not None
        assert row.started_at.replace(tzinfo=UTC) == now
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-667")
@pytest.mark.req("CF-REQ-669")
@pytest.mark.req("CF-REQ-670")
async def test_feedback_uses_dispatched_model_and_saved_policy_even_at_hard_cap(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'feedback.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "feedback.db", "vendor/default:free")
    settings.llm_model_evaluation = "vendor/vision:free"
    run = RunRepository(sessions).create(
        RunTrigger.RUN_NOW,
        manual_url=None,
        settings_snapshot={
            "llm": {"requests_per_minute": 5, "max_requests_per_run": 1},
            "providers": {"call_retry_max_delay_seconds": 120},
        },
    )
    state = FakeDragonfly()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: datetime.now(UTC))
    request_id = await service.begin(UUID(run["run_id"]), "evaluate_clip", "evaluation")
    settings.llm_model_evaluation = "vendor/changed:free"
    await service.finish(request_id, None, "rate_limited", retry_after_seconds=90)
    assert state.models == ["vendor/vision:free"]
    assert state.feedback[0]["model"] == "vendor/vision:free"
    assert state.feedback[0]["max_delay"] == 120
    assert state.feedback[0]["limit"] == 5
    assert state.feedback[0]["retry_after_seconds"] == 90
    with sessions() as session:
        row = session.get(LLMRequestRow, request_id)
        assert row is not None
        assert row.rate_limit_headers == {"Retry-After": "90"}
    with pytest.raises(ProviderError) as caught:
        await service.begin(UUID(run["run_id"]), "evaluate_clip", "evaluation")
    assert caught.value.code == "llm_budget_exhausted"
    assert state.takes == 1
    engine.dispose()
