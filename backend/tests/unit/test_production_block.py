from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from clipfactory.assets.candidate_review import SegmentCandidates
from clipfactory.assets.music import select_music
from clipfactory.domain.models import (
    Asset,
    AssetOrigin,
    ContentProfile,
    MusicInfo,
    MusicPolicy,
    Platform,
    Provenance,
    Stage,
)
from clipfactory.evaluation.semantic import (
    SemanticEvaluationResult,
    evaluate_semantics,
    representative_frames,
)
from clipfactory.evaluation.validation import EvaluationContext
from clipfactory.planning.script import (
    GeneratedScript,
    ScriptSegment,
    SocialMetadataDraft,
    VisualDraft,
)
from clipfactory.planning.visuals import build_visual_plan
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMResult
from clipfactory.ports.media_sources import MediaCandidate
from clipfactory.workflow.production_stages import ProductionStageService, production_stage_handlers


def _music(title: str, *, allowed: list[Platform] | None, moods: list[str]) -> Asset:
    return Asset(
        media_type="audio",
        category="music",
        storage_key=f"assets/{title}.mp3",
        sha256=("a" if title == "alpha" else "b") * 64,
        mime_type="audio/mpeg",
        size_bytes=100,
        duration_seconds=120,
        description=title,
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="manual", license="royalty-free"),
        music=MusicInfo(
            title=title,
            artist="Artist",
            genre="news",
            mood=moods,
            energy="low",
            loopable=False,
            allowed_platforms=allowed,
        ),
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-250")
@pytest.mark.req("CF-REQ-251")
@pytest.mark.req("CF-REQ-253")
def test_visual_plan_splits_long_segments_and_normalizes_person_generation() -> None:
    claim_id = uuid4()
    script = GeneratedScript(
        language="en",
        segments=(ScriptSegment(0, "one two three four five six", (claim_id,), None, 12),),
        word_count=6,
        estimated_duration_seconds=12,
        social_metadata=SocialMetadataDraft(title="Title", description="", hashtags=["#a", "#b", "#c"]),
        visuals=(
            VisualDraft(
                objective="Show the subject",
                media_type="image",
                category="photo",
                description="A public figure",
                subjects=["Ada Lovelace"],
                tags=["history"],
                strategy="generate_allowed",
                motion="none",
            ),
        ),
        model="fake",
    )

    plan = build_visual_plan(script, allow_generated_media=True, max_segment_seconds=8)

    assert len(plan) == 2
    assert sum(item.planned_duration_seconds for item in plan) == 12
    assert all(item.requirement["strategy"] == "acquire_only" for item in plan)
    assert all(item.motion == "none" for item in plan)
    assert all(item.motion_reason == "Show the subject" for item in plan)
    animated = replace(script, visuals=(script.visuals[0].model_copy(update={"motion": "pan_right"}),))
    animated_plan = build_visual_plan(animated, allow_generated_media=True, max_segment_seconds=8)
    assert [item.motion for item in animated_plan] == ["pan_right", "none"]
    assert [item.transition_in for item in animated_plan] == ["cut", "cut"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-320")
def test_music_selection_rejects_platform_restricted_track() -> None:
    restricted = _music("alpha", allowed=[Platform.YOUTUBE], moods=["news", "neutral"])
    eligible = _music("beta", allowed=None, moods=["news"])

    selected = select_music(
        [restricted, eligible],
        MusicPolicy(),
        platforms=[Platform.YOUTUBE, Platform.TIKTOK],
        clip_duration_seconds=70,
    )

    assert selected is not None
    assert selected.id == eligible.id


@pytest.mark.unit
@pytest.mark.req("CF-REQ-415")
def test_representative_frames_include_hook_and_are_deterministic() -> None:
    segments = [
        {
            "index": index,
            "start_seconds": index * 10.0,
            "end_seconds": (index + 1) * 10.0,
            "selected_asset_id": str(uuid4()),
        }
        for index in range(8)
    ]

    first = representative_frames(segments, 5)
    second = representative_frames(segments, 5)

    assert first == second
    assert len(first) == 5
    assert first[0]["visual_segment_index"] == 0


class SemanticLLM:
    name = "fake"

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[Any],
        *,
        model_role: str = "default",
        images: list[ImageInput] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[Any]:
        del messages, schema, model_role, temperature
        assert task == "evaluate_clip"
        assert len(images or []) == 1
        result = SemanticEvaluationResult.model_validate(
            {
                "issues": [
                    {
                        "code": "visual_irrelevant",
                        "severity": "blocking",
                        "message": "Frame does not depict the segment",
                        "refs": {"segment_index": 3},
                    }
                ],
                "scores": {"visual_relevance": 1.0},
            }
        )
        return cast(LLMResult[Any], LLMResult(result, "fake", "vision-model"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-405")
@pytest.mark.req("CF-REQ-407")
@pytest.mark.req("CF-REQ-408")
@pytest.mark.asyncio
async def test_semantic_evaluation_routes_blocking_visual_issue_in_code() -> None:
    evaluation = await evaluate_semantics(
        SemanticLLM(),
        EvaluationContext(uuid4(), uuid4(), 1),
        production_data={"script": []},
        frames=[ImageInput(b"jpeg", "image/jpeg", {"visual_segment_index": 3})],
    )

    assert not evaluation.passed
    assert evaluation.actions[0].target_stage == Stage.SELECT_ASSETS
    assert evaluation.actions[0].refs == {"segment_index": 3}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-410")
def test_production_handler_map_covers_the_executable_block() -> None:
    service = cast(ProductionStageService, object())
    handlers = production_stage_handlers(service)
    assert set(handlers) == {
        Stage.BUILD_STORY_PACKAGE,
        Stage.WRITE_SCRIPT,
        Stage.PLAN_VISUALS,
        Stage.SELECT_ASSETS,
        Stage.GENERATE_NARRATION,
        Stage.TRANSCRIBE_NARRATION,
        Stage.BUILD_CAPTIONS,
        Stage.COMPOSE_CLIP,
        Stage.VALIDATE_CLIP,
        Stage.EVALUATE_CLIP,
        Stage.PLAN_RETRY,
    }


@pytest.mark.unit
@pytest.mark.req("CF-REQ-209")
@pytest.mark.req("CF-REQ-257")
@pytest.mark.parametrize("case", ["empty", "rejected", "partial", "legacy_card"])
@pytest.mark.asyncio
async def test_automatic_selection_blocks_missing_media_without_plain_cards(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    run_id, package_id = uuid4(), uuid4()
    asset = Asset(
        media_type="image",
        category="title_card" if case == "legacy_card" else "photo",
        storage_key="assets/fixture.png",
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=100,
        width=720,
        height=1280,
        description="Electricity substation",
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="fixture", license="CC0"),
    )
    plan = {
        "version": 1,
        "segments": [
            {
                "index": index,
                "narration_text": "The electricity grid needs repair.",
                "objective": "Show electricity infrastructure",
                "planned_duration_seconds": 5.0,
                "requirement": {
                    "media_type": "image",
                    "category": asset.category,
                    "description": asset.description,
                    "subjects": [],
                    "tags": [],
                },
            }
            for index in range(2)
        ],
    }
    production, runs, assets, evaluations = (MagicMock() for _ in range(4))
    production.current_visual_plan.return_value = plan
    production.package_context.return_value = {"title": "Grid repairs"}
    runs.get.return_value = {
        "attempt": 1,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {"assets": {"reuse_min_match_score": 0}},
    }
    assets.list.return_value = [] if case == "empty" else [asset]

    async def review(llm: Any, segments: list[SegmentCandidates], **kwargs: Any) -> dict[int, list[MediaCandidate]]:
        return {
            segment.segment_index: list(segment.candidates) if case == "partial" and segment.segment_index == 0 else []
            for segment in segments
        }

    monkeypatch.setattr("clipfactory.workflow.production_stages.review_media_candidates", review)
    storage = MagicMock()
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=evaluations,
        storage=storage,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=MagicMock(),
        clock=lambda: datetime(2026, 10, 7, tzinfo=UTC),
        candidate_preview=AsyncMock(),
    )
    result = await service.select_assets(
        {"run_id": str(run_id), "trigger": "run_now", "story_package_id": str(package_id), "attempt": 1}
    )
    evaluation = evaluations.save.call_args.args[0]
    assert not evaluation.passed
    assert all(issue.code == "missing_asset" for issue in evaluation.issues)
    expected_missing = [1] if case == "partial" else [0, 1]
    assert [issue.refs["segment_index"] for issue in evaluation.issues] == expected_missing
    assert all(action.target_stage == Stage.SELECT_ASSETS for action in evaluation.actions)
    assert result["last_evaluation_ids"] == [str(evaluation.id)]
    production.save_visual_plan.assert_called_once()
    assets.save.assert_not_called()
    storage.put_bytes.assert_not_called()
    for index in expected_missing:
        assert plan["segments"][index].get("selected_asset_id") is None
    if case == "partial":
        assert plan["segments"][0]["selected_asset_id"] == str(asset.id)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-209")
@pytest.mark.req("CF-REQ-257")
@pytest.mark.asyncio
async def test_composition_blocks_a_legacy_plain_card_in_a_retained_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id, package_id = uuid4(), uuid4()
    card = Asset(
        media_type="image",
        category="title_card",
        storage_key="assets/plain-card.png",
        sha256="b" * 64,
        mime_type="image/png",
        description="Legacy plain-colour text card",
        size_bytes=100,
        width=720,
        height=1280,
        provenance=Provenance(origin=AssetOrigin.RENDERED, provider="clipfactory_title_card", license="CC0"),
    )
    production, runs, assets, evaluations = (MagicMock() for _ in range(4))
    production.current_visual_plan.return_value = {
        "version": 1,
        "segments": [{"index": 0, "selected_asset_id": str(card.id), "start_seconds": 0.0, "end_seconds": 5.0}],
    }
    production.artifact.return_value = {"duration_seconds": 70.0, "words": []}
    runs.get.return_value = {
        "attempt": 1,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {},
    }
    assets.get.return_value = card
    monkeypatch.setattr(
        "clipfactory.workflow.production_stages.reconcile_visual_timing", lambda segments, words, **kwargs: segments
    )
    media = MagicMock()
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=evaluations,
        storage=MagicMock(),
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=media,
        clock=lambda: datetime(2026, 10, 7, tzinfo=UTC),
    )
    result = await service.compose_clip(
        {"run_id": str(run_id), "trigger": "run_now", "story_package_id": str(package_id), "attempt": 1}
    )
    evaluation = evaluations.save.call_args.args[0]
    assert not evaluation.passed
    assert [issue.code for issue in evaluation.issues] == ["missing_asset"]
    assert result["last_evaluation_ids"] == [str(evaluation.id)]
    production.save_clip.assert_not_called()
    media.ffmpeg.assert_not_called()
