"""Deterministic issue-to-action routing from the specification."""

from __future__ import annotations

from dataclasses import dataclass

from clipfactory.domain.models import ActionType, Stage


@dataclass(frozen=True, slots=True)
class Route:
    target_stage: Stage | None
    action_type: ActionType


ISSUE_ROUTES: dict[str, Route] = {
    **{
        code: Route(Stage.WRITE_SCRIPT, ActionType.REVISE_SCRIPT)
        for code in (
            "script_segment_count",
            "hook_too_long",
            "hook_ungrounded",
            "segment_ungrounded",
            "unknown_claim",
            "missing_attribution",
            "script_too_short",
            "script_too_long",
            "forbidden_content",
            "caption_out_of_bounds",
            "duration_out_of_range",
            "metadata_invalid",
            "attribution_missing",
            "weak_hook",
            "poor_script_quality",
            "editorial_quality",
        )
    },
    "narration_too_short": Route(Stage.WRITE_SCRIPT, ActionType.REVISE_SCRIPT),
    "narration_too_long": Route(Stage.WRITE_SCRIPT, ActionType.REVISE_SCRIPT),
    "narration_invalid": Route(Stage.GENERATE_NARRATION, ActionType.REGENERATE_NARRATION),
    "narration_mismatch": Route(Stage.GENERATE_NARRATION, ActionType.REGENERATE_NARRATION),
    **{
        code: Route(Stage.SELECT_ASSETS, ActionType.RESELECT_ASSET)
        for code in (
            "missing_asset",
            "asset_too_short",
            "asset_render_failed",
            "asset_unavailable",
            "asset_license_missing",
            "visual_irrelevant",
            "misleading_generated_media",
        )
    },
    **{
        code: Route(Stage.PLAN_VISUALS, ActionType.REPLAN_VISUALS)
        for code in ("segment_too_short", "segment_too_long", "visual_timing_drift", "poor_pacing")
    },
    **{
        code: Route(Stage.COMPOSE_CLIP, ActionType.RECOMPOSE)
        for code in (
            "resolution_mismatch",
            "aspect_ratio_mismatch",
            "fps_mismatch",
            "stream_missing",
            "codec_mismatch",
            "media_corrupt",
        )
    },
    "claim_not_supported": Route(Stage.WRITE_SCRIPT, ActionType.REMOVE_CLAIM),
    "unsupported_statement": Route(Stage.WRITE_SCRIPT, ActionType.REMOVE_CLAIM),
    "insufficient_grounding": Route(Stage.GATHER_SOURCES, ActionType.GATHER_MORE_SOURCES),
    "narration_quality": Route(Stage.GENERATE_NARRATION, ActionType.REGENERATE_NARRATION),
    "caption_quality": Route(None, ActionType.ABORT),
    "story_unsuitable": Route(None, ActionType.ABORT),
    "composition_defect": Route(None, ActionType.ABORT),
}


_STAGE_ORDER = {stage: index for index, stage in enumerate(Stage)}


def earliest_reentry(routes: list[Route]) -> Stage | None:
    targets = [route.target_stage for route in routes if route.target_stage is not None]
    return min(targets, key=_STAGE_ORDER.__getitem__) if targets else None
