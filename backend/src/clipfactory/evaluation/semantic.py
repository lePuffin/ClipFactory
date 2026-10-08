"""Single-call semantic Clip evaluation over metadata and optional frames."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from clipfactory.domain.models import Evaluation, EvaluationLayer, Issue, IssueSeverity, Stage
from clipfactory.evaluation.validation import EvaluationContext, build_evaluation
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMProvider

SemanticIssueCode = Literal[
    "claim_not_supported",
    "unsupported_statement",
    "insufficient_grounding",
    "weak_hook",
    "poor_script_quality",
    "editorial_quality",
    "visual_irrelevant",
    "misleading_generated_media",
    "poor_pacing",
    "narration_quality",
    "caption_quality",
    "story_unsuitable",
]


class SemanticIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SemanticIssueCode
    severity: Literal["blocking", "warning"]
    message: str = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    refs: dict[str, Any] = Field(default_factory=dict)
    instructions: str = ""


class SemanticEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issues: list[SemanticIssue]
    scores: dict[str, float] = Field(default_factory=dict)


def representative_frames(segments: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not segments:
        return []
    selected_count = min(count, len(segments))
    indexes = sorted(
        {round(index * (len(segments) - 1) / max(1, selected_count - 1)) for index in range(selected_count)}
    )
    frames = [
        {
            "timestamp_seconds": (float(segments[index]["start_seconds"]) + float(segments[index]["end_seconds"])) / 2,
            "visual_segment_index": int(segments[index]["index"]),
            "asset_id": segments[index].get("selected_asset_id"),
        }
        for index in indexes
    ]
    if len(frames) < count:
        clip_end = float(segments[-1]["end_seconds"])
        for index in range(count - len(frames)):
            frames.append(
                {
                    "timestamp_seconds": clip_end * (index + 1) / (count - len(frames) + 1),
                    "visual_segment_index": None,
                    "asset_id": None,
                }
            )
    return frames


async def evaluate_semantics(
    provider: LLMProvider,
    context: EvaluationContext,
    *,
    production_data: dict[str, Any],
    frames: list[ImageInput] | None = None,
) -> Evaluation:
    messages = [
        LLMMessage(
            "system",
            "Evaluate this source-grounded Clip. Return only canonical issue codes. "
            "Scores are diagnostic and never determine pass/fail. Cite segment/frame evidence for every issue.",
        ),
        LLMMessage(
            "user",
            "<untrusted-production-data>\n"
            + json.dumps(production_data, ensure_ascii=False, sort_keys=True)
            + "\n</untrusted-production-data>",
        ),
    ]
    response = await provider.generate_structured(
        "evaluate_clip",
        messages,
        SemanticEvaluationResult,
        model_role="evaluation",
        images=frames,
    )
    issues: list[Issue] = []
    warnings: list[Issue] = []
    for finding in response.value.issues:
        issue = Issue(
            code=finding.code,
            severity=IssueSeverity(finding.severity),
            stage=Stage.EVALUATE_CLIP,
            message=finding.instructions or finding.message,
            evidence=finding.evidence,
            refs=finding.refs,
        )
        (issues if issue.severity == IssueSeverity.BLOCKING else warnings).append(issue)
    return build_evaluation(
        context,
        issues=issues,
        warnings=warnings,
        metrics={"scores": response.value.scores, "frame_count": len(frames or [])},
        evaluator=response.model,
        layer=EvaluationLayer.SEMANTIC,
    )
