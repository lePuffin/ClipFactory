"""Targeted, bounded revision planning for failed Evaluations."""

from __future__ import annotations

from dataclasses import dataclass

from clipfactory.domain.models import ActionType, Evaluation, Stage


@dataclass(frozen=True, slots=True)
class RetryPlan:
    reentry_stage: Stage | None
    attempt: int
    revision_retries_used: int
    pending_actions: tuple[dict[str, object], ...]
    affected_segments: tuple[int, ...]
    failure_code: str | None = None


_STAGE_ORDER = {stage: index for index, stage in enumerate(Stage)}


def plan_retry(
    evaluation: Evaluation,
    *,
    revision_retries_used: int,
    max_revision_retries: int,
) -> RetryPlan:
    if max_revision_retries < 0:
        raise ValueError("max_revision_retries must be non-negative")
    serialized_actions = tuple(action.model_dump(mode="json") for action in evaluation.actions)
    affected_segments = tuple(
        sorted(
            {
                segment_index
                for action in evaluation.actions
                if isinstance((segment_index := action.refs.get("segment_index")), int)
            }
        )
    )
    abort = next((action for action in evaluation.actions if action.type == ActionType.ABORT), None)
    if abort is not None:
        issue_code = next((issue.code for issue in evaluation.issues if issue.refs == abort.refs), "evaluation_aborted")
        return RetryPlan(
            None,
            evaluation.attempt,
            revision_retries_used,
            serialized_actions,
            affected_segments,
            issue_code,
        )
    if revision_retries_used >= max_revision_retries:
        return RetryPlan(
            None,
            evaluation.attempt,
            revision_retries_used,
            serialized_actions,
            affected_segments,
            "evaluation_failed_after_retries",
        )
    targets = [action.target_stage for action in evaluation.actions]
    reentry_stage = min(targets, key=_STAGE_ORDER.__getitem__) if targets else None
    if reentry_stage is None:
        return RetryPlan(
            None,
            evaluation.attempt,
            revision_retries_used,
            serialized_actions,
            affected_segments,
            "evaluation_failed_after_retries",
        )
    return RetryPlan(
        reentry_stage,
        evaluation.attempt + 1,
        revision_retries_used + 1,
        serialized_actions,
        affected_segments,
    )
