from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel
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

    async def seed(self, recent: dict[str, float]) -> None:
        self.seeded = True

    async def take(self, now: datetime, limit: int, request_id: UUID) -> tuple[int, int]:
        self.takes += 1
        return 1, 0

    async def record_result(self, error: str | None, *, seconds: int, threshold: int, open_seconds: int) -> None:
        self.errors.append(error)


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
@pytest.mark.req("CF-REQ-666")
@pytest.mark.asyncio
async def test_governance_blocks_paid_models_without_price_reservation(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'paid.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    settings = _settings(tmp_path / "paid.db", "vendor/paid-model")
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    state = FakeDragonfly()
    service = GovernedLLMCalls(sessions, settings, state, clock=lambda: datetime.now(UTC))

    with pytest.raises(ProviderError, match="verified price reservations") as caught:
        await service.begin(UUID(run["run_id"]), "rank_stories", "default")

    assert caught.value.code == "budget_exceeded"
    assert state.takes == 0
    engine.dispose()
