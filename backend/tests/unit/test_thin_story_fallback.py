from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select

from clipfactory.domain.models import (
    Claim,
    ClaimStatus,
    ContentProfile,
    Issue,
    IssueSeverity,
    RunTrigger,
    Stage,
    SupportLevel,
)
from clipfactory.evaluation.validation import EvaluationContext, build_evaluation
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import StoryRow
from clipfactory.infrastructure.db.production_repository import ProductionRepository
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.research_repository import ResearchRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.ports.research import ResearchSnapshot, ResearchSourceRecord, ResearchStoryRecord
from clipfactory.research.pipeline import ResearchFailure
from clipfactory.research.service import ResearchUseCase
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.graph import WorkflowState
from clipfactory.workflow.production_stages import ProductionStageService
from clipfactory.workflow.research_stages import ResearchStageUseCase


@pytest.mark.req("CF-REQ-117")
@pytest.mark.req("CF-REQ-410")
@pytest.mark.parametrize(
    ("trigger", "has_script", "thin", "used", "expected"),
    [
        ("run_now", False, 2, 0, "research"),
        ("scheduled", False, 2, 1, "research"),
        ("manual_url", False, 2, 0, "write_script"),
        ("run_now", True, 2, 0, "write_script"),
        ("run_now", False, 1, 0, "write_script"),
        ("run_now", False, 2, 2, "insufficient_claims"),
    ],
)
async def test_thin_story_retry_preserves_limits_and_owner_selection(trigger, has_script, thin, used, expected):
    run_id, story_id, package_id = uuid4(), uuid4(), uuid4()
    evaluation = build_evaluation(
        EvaluationContext(run_id, None, 3),
        issues=[
            Issue(
                code="script_too_short",
                stage=Stage.WRITE_SCRIPT,
                severity=IssueSeverity.BLOCKING,
                message="Not enough grounded narration",
            ),
        ],
    )
    runs = MagicMock()
    runs.get.return_value = {
        "revision_retries_used": 2,
        "settings_snapshot": {"workflow": {"max_revision_retries": 10}},
    }
    production = MagicMock()
    if not has_script:
        production.current_script.side_effect = LookupError("no passing Script")
    evaluations = MagicMock()
    evaluations.get.return_value = evaluation
    service = ProductionStageService(
        production=production,
        runs=runs,
        evaluations=evaluations,
        assets=MagicMock(),
        storage=MagicMock(),
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=MagicMock(),
        clock=lambda: datetime(2026, 10, 14, tzinfo=UTC),
    )
    state: WorkflowState = {
        "run_id": str(run_id),
        "story_id": str(story_id),
        "story_package_id": str(package_id),
        "trigger": trigger,
        "last_evaluation_ids": [str(evaluation.id)],
        "thin_story_attempts": thin,
        "story_fallbacks_used": used,
    }
    if expected == "insufficient_claims":
        with pytest.raises(StageFailure, match="allowance") as caught:
            await service.plan_retry(state)
        assert caught.value.code == expected
        runs.apply_retry.assert_not_called()
    else:
        result = await service.plan_retry(state)
        assert result["reentry_stage"] == expected
        assert result["attempt"] == 4
        assert result["revision_retries_used"] == 3
        if expected == "research":
            assert result["pending_actions"] == []
            assert result["rejected_story_id"] == str(story_id)
        else:
            assert result["rejected_story_id"] is None


@pytest.mark.req("CF-REQ-117")
@pytest.mark.req("CF-REQ-118")
def test_persisted_fallback_retains_history_and_rebinds_only_unwritten_package(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fallback.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    run_id = UUID(RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    now = datetime(2026, 10, 14, tzinfo=UTC)
    source_id, old_id, skipped_id, next_id = (uuid4() for _ in range(4))
    source = ResearchSourceRecord(
        source_id,
        "https://news.example/one",
        "https://news.example/one",
        "News",
        "News",
        "Source",
        "Retained source evidence",
        "a" * 64,
        "standard",
        now,
        now,
        None,
        None,
    )
    stories = tuple(
        ResearchStoryRecord(
            identifier,
            "selected" if rank == 0 else "rejected",
            f"Story {rank}",
            "Summary",
            "general",
            1 - rank / 10,
            {"candidate_rank": rank},
            "Rating",
            None if rank == 0 else "lower_selection_score",
            () if rank == 1 else (source_id,),
        )
        for rank, identifier in enumerate((old_id, skipped_id, next_id))
    )
    old_claims = tuple(
        Claim(
            story_id=old_id,
            text=f"Accepted old fact {index}.",
            status=ClaimStatus.ACCEPTED,
            support_level=SupportLevel.SINGLE_SOURCE,
        )
        for index in range(3)
    )
    repository = ResearchRepository(sessions)
    repository.persist(
        ResearchSnapshot(run_id, (source,), stories, old_id, old_claims, tuple(claim.id for claim in old_claims))
    )
    production = ProductionRepository(sessions)
    old_package = production.create_story_package(run_id, now)
    assert repository.select_fallback(run_id, old_id, min_sources=1) == (next_id, 1)
    assert repository.select_fallback(run_id, old_id, min_sources=1) == (next_id, 1)
    new_claims = tuple(
        Claim(
            story_id=next_id,
            text=f"Accepted new fact {index}.",
            status=ClaimStatus.ACCEPTED,
            support_level=SupportLevel.SINGLE_SOURCE,
        )
        for index in range(3)
    )
    repository.persist_claims(next_id, new_claims, tuple(claim.id for claim in new_claims), "Next", "Next summary")
    package = production.create_story_package(run_id, now)
    assert package["story_package_id"] == old_package["story_package_id"]
    assert production.package_context(UUID(package["story_package_id"]))["title"] == "Next"
    with sessions() as session:
        old = session.get(StoryRow, old_id)
        skipped = session.get(StoryRow, skipped_id)
        assert old is not None
        assert old.rejection_reason == "insufficient_claims"
        assert skipped is not None
        assert skipped.rejection_reason == "insufficient_sources"
        assert len(list(session.scalars(select(StoryRow)))) == 3
    assert repository.select_fallback(run_id, next_id, min_sources=1) is None
    with sessions.begin() as session:
        for rank in (3, 4):
            session.add(
                StoryRow(
                    id=uuid4(),
                    run_id=run_id,
                    status="rejected",
                    title=f"Extra {rank}",
                    summary="Summary",
                    category="general",
                    selection_score=0.5,
                    score_breakdown={"candidate_rank": rank},
                    rejection_reason="lower_selection_score",
                    key_fact_claim_ids=[],
                )
            )
        # One earlier research fallback plus the retained thin-script rejection exhaust the shared allowance.
        skipped = session.get(StoryRow, skipped_id)
        assert skipped is not None
        skipped.rejection_reason = "grounding_failed"
    assert repository.select_fallback(run_id, next_id, min_sources=0) is None
    engine.dispose()


@pytest.mark.req("CF-REQ-117")
@pytest.mark.parametrize(
    ("remaining", "available", "expected"), [(0, True, "ok"), (1, True, "ok"), (2, True, "limit"), (0, False, "empty")]
)
async def test_fallback_reuses_sources_without_rank_or_collection(remaining, available, expected):
    repository, llm, events = MagicMock(), MagicMock(), MagicMock()
    next_id = uuid4()
    repository.select_fallback.return_value = (next_id, remaining + 1) if available else None
    service = ResearchUseCase(news_sources=(), fetcher=MagicMock(), llm=llm, repository=repository, events=events)
    accepted = [
        Claim(
            story_id=next_id,
            status=ClaimStatus.ACCEPTED,
            text=" ".join(["evidence"] * 70),
            support_level=SupportLevel.SINGLE_SOURCE,
        )
    ]
    extraction = AsyncMock(return_value=SimpleNamespace(claims=accepted))
    with patch("clipfactory.research.service.ManualURLClaimExtractor.execute", extraction):
        if expected == "ok":
            story_id, used = await service.fallback(
                uuid4(), ContentProfile(), uuid4(), remaining, max_claim_input_chars=60000, repository=repository
            )
            assert story_id == next_id
            assert used == remaining + 1
            extraction.assert_awaited_once()
            events.append_event.assert_called_once()
        else:
            with pytest.raises(ResearchFailure) as caught:
                await service.fallback(
                    uuid4(), ContentProfile(), uuid4(), remaining, max_claim_input_chars=60000, repository=repository
                )
            assert caught.value.code == "insufficient_claims"
            extraction.assert_not_called()
    llm.generate_structured.assert_not_called()


@pytest.mark.req("CF-REQ-117")
async def test_restarted_fallback_uses_durable_counter_not_stale_checkpoint():
    repository, llm, events = MagicMock(), MagicMock(), MagicMock()
    repository.select_fallback.return_value = (uuid4(), 2)
    service = ResearchUseCase(news_sources=(), fetcher=MagicMock(), llm=llm, repository=repository, events=events)
    extraction = AsyncMock(return_value=SimpleNamespace(claims=[]))
    with (
        patch("clipfactory.research.service.ManualURLClaimExtractor.execute", extraction),
        pytest.raises(ResearchFailure, match="allowance"),
    ):
        await service.fallback(
            uuid4(), ContentProfile(), uuid4(), 0, max_claim_input_chars=60000, repository=repository
        )
    repository.select_fallback.assert_called_once()
    extraction.assert_awaited_once()


@pytest.mark.req("CF-REQ-117")
@pytest.mark.req("CF-REQ-412")
async def test_research_reentry_selects_persisted_candidate_without_recollecting():
    run_id, old_id, next_id = uuid4(), uuid4(), uuid4()
    research, repository, runs = MagicMock(), MagicMock(), MagicMock()
    research.fallback = AsyncMock(return_value=(next_id, 1))
    repository.summary.return_value = {"story_id": old_id}
    runs.get.return_value = {"profile_snapshot": ContentProfile().model_dump(mode="json"), "settings_snapshot": {}}
    stage = ResearchStageUseCase(research, repository, runs)
    result = await stage.execute(
        {
            "run_id": str(run_id),
            "trigger": "run_now",
            "rejected_story_id": str(old_id),
            "thin_story_attempts": 2,
            "story_fallbacks_used": 0,
        }
    )
    assert result == {
        "story_id": str(next_id),
        "story_fallbacks_used": 1,
        "rejected_story_id": None,
        "thin_story_attempts": 0,
    }
    research.fallback.assert_awaited_once()
    research.execute.assert_not_called()
    repository.recently_covered.assert_not_called()
