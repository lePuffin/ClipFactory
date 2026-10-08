from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from clipfactory.domain.models import Action, ActionType, Evaluation, EvaluationLayer, IssueSeverity, Stage
from clipfactory.evaluation.retry import plan_retry
from clipfactory.evaluation.validation import (
    EvaluationContext,
    MediaValidationSpec,
    validate_duration,
    validate_media,
)
from clipfactory.infrastructure.media.runner import MediaProcessError


@pytest.mark.req("CF-REQ-400")
@pytest.mark.req("CF-REQ-401")
@pytest.mark.parametrize(
    ("duration_seconds", "passes"),
    [
        (58, False),
        (59, False),
        (60, True),
        (63, True),
        (74, True),
        (75, True),
        (89, True),
        (90, True),
        (91, False),
        (92, False),
    ],
)
def test_duration_validation_uses_inclusive_profile_bounds(duration_seconds: float, passes: bool) -> None:
    evaluation = validate_duration(
        EvaluationContext(run_id=uuid4(), clip_id=uuid4(), attempt=1),
        duration_seconds=duration_seconds,
        min_seconds=60,
        max_seconds=90,
    )

    assert evaluation.passed is passes
    if passes:
        assert evaluation.issues == []
        assert evaluation.actions == []
    else:
        assert [issue.code for issue in evaluation.issues] == ["duration_out_of_range"]
        assert evaluation.issues[0].severity == IssueSeverity.BLOCKING
        assert evaluation.actions[0].type == ActionType.REVISE_SCRIPT
        assert evaluation.actions[0].target_stage == Stage.WRITE_SCRIPT
        assert evaluation.metrics["duration_seconds"] == duration_seconds


@pytest.mark.req("CF-REQ-401")
def test_duration_validation_uses_changed_profile_without_code_changes() -> None:
    context = EvaluationContext(run_id=uuid4(), clip_id=uuid4(), attempt=1)

    assert validate_duration(context, duration_seconds=40, min_seconds=30, max_seconds=45).passed
    assert not validate_duration(context, duration_seconds=60, min_seconds=30, max_seconds=45).passed


def valid_probe() -> dict[str, Any]:
    return {
        "format": {"duration": "75.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 720,
                "height": 1280,
                "display_aspect_ratio": "9:16",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


class FakeMediaRunner:
    def __init__(self, probe: dict[str, Any], *, corrupt: bool = False) -> None:
        self.probe_result = probe
        self.corrupt = corrupt

    async def probe(self, media_path: Path) -> dict[str, Any]:
        del media_path
        return self.probe_result

    async def decode(self, media_path: Path) -> None:
        del media_path
        if self.corrupt:
            raise MediaProcessError("media_process_failed", "decode failed")


@pytest.mark.req("CF-REQ-402")
@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda probe: probe["streams"][0].update(width=640), "resolution_mismatch"),
        (lambda probe: probe["streams"][0].update(display_aspect_ratio="1:1"), "aspect_ratio_mismatch"),
        (lambda probe: probe["streams"][0].update(r_frame_rate="25/1"), "fps_mismatch"),
        (lambda probe: probe["streams"].pop(), "stream_missing"),
        (lambda probe: probe["streams"][0].update(codec_name="vp9"), "codec_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_technical_media_validation_reports_canonical_issue(
    mutate: Any,
    expected_code: str,
) -> None:
    probe = valid_probe()
    mutate(probe)

    evaluation = await validate_media(
        EvaluationContext(run_id=uuid4(), clip_id=uuid4(), attempt=1),
        Path("clip.mp4"),
        runner=FakeMediaRunner(probe),
        spec=MediaValidationSpec(),
    )

    assert [issue.code for issue in evaluation.issues] == [expected_code]


@pytest.mark.req("CF-REQ-402")
@pytest.mark.asyncio
async def test_technical_media_validation_requires_full_decode() -> None:
    evaluation = await validate_media(
        EvaluationContext(run_id=uuid4(), clip_id=uuid4(), attempt=1),
        Path("clip.mp4"),
        runner=FakeMediaRunner(valid_probe(), corrupt=True),
        spec=MediaValidationSpec(),
    )

    assert [issue.code for issue in evaluation.issues] == ["media_corrupt"]


@pytest.mark.req("CF-REQ-410")
def test_retry_plan_reenters_at_earliest_targeted_stage() -> None:
    evaluation = Evaluation(
        run_id=uuid4(),
        attempt=1,
        layer=EvaluationLayer.SEMANTIC,
        issues=[],
        actions=[
            Action(type=ActionType.REPLAN_VISUALS, target_stage=Stage.PLAN_VISUALS),
            Action(type=ActionType.RESELECT_ASSET, target_stage=Stage.SELECT_ASSETS, refs={"segment_index": 2}),
        ],
        evaluator="fake",
    )

    retry = plan_retry(evaluation, revision_retries_used=0, max_revision_retries=3)

    assert retry.reentry_stage == Stage.PLAN_VISUALS
    assert retry.attempt == 2
    assert retry.revision_retries_used == 1
    assert retry.failure_code is None
    assert retry.affected_segments == (2,)


@pytest.mark.req("CF-REQ-411")
def test_retry_plan_fails_when_revision_limit_is_exhausted() -> None:
    evaluation = Evaluation(
        run_id=uuid4(),
        attempt=1,
        layer=EvaluationLayer.SEMANTIC,
        actions=[Action(type=ActionType.REVISE_SCRIPT, target_stage=Stage.WRITE_SCRIPT)],
        evaluator="fake",
    )

    retry = plan_retry(evaluation, revision_retries_used=0, max_revision_retries=0)

    assert retry.reentry_stage is None
    assert retry.attempt == 1
    assert retry.revision_retries_used == 0
    assert retry.failure_code == "evaluation_failed_after_retries"
