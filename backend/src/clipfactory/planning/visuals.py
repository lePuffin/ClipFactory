"""Deterministic Visual Plan normalization from the write_script draft."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from clipfactory.planning.script import GeneratedScript, VisualDraft


@dataclass(frozen=True, slots=True)
class VisualSegment:
    index: int
    script_segment_index: int
    narration_text: str
    objective: str
    requirement: dict[str, Any]
    planned_duration_seconds: float
    motion: str
    transition_in: str
    motion_reason: str = ""
    selected_asset_id: str | None = None
    selection_reason: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


def build_visual_plan(
    script: GeneratedScript,
    *,
    allow_generated_media: bool,
    max_segment_seconds: float = 8.0,
) -> tuple[VisualSegment, ...]:
    if max_segment_seconds <= 0 or len(script.visuals) < len(script.segments):
        raise ValueError("visual draft cannot cover the Script")
    output: list[VisualSegment] = []
    for script_segment, draft in zip(script.segments, script.visuals, strict=False):
        pieces = max(1, math.ceil(script_segment.estimated_duration_seconds / max_segment_seconds))
        text_parts = _split_words(script_segment.text, pieces)
        for part_index, part in enumerate(text_parts):
            output.append(
                _normalize_segment(
                    len(output),
                    script_segment.index,
                    part,
                    script_segment.estimated_duration_seconds / len(text_parts),
                    draft,
                    allow_generated_media,
                    continuation=part_index > 0,
                )
            )
    return tuple(output)


def serialize_visual_plan(segments: tuple[VisualSegment, ...]) -> list[dict[str, Any]]:
    return [asdict(segment) for segment in segments]


def _normalize_segment(
    index: int,
    script_index: int,
    narration_text: str,
    duration: float,
    draft: VisualDraft,
    allow_generated_media: bool,
    continuation: bool = False,
) -> VisualSegment:
    strategy = draft.strategy
    if strategy == "generate_allowed" and not allow_generated_media:
        strategy = "reuse_first"
    if strategy == "generate_allowed" and contains_named_person(draft.subjects):
        strategy = "acquire_only"
    motion = "none" if continuation else draft.motion
    return VisualSegment(
        index=index,
        script_segment_index=script_index,
        narration_text=narration_text,
        objective=draft.objective,
        requirement={
            "media_type": "video" if draft.kind != "media" else draft.media_type,
            "category": (
                "chart"
                if draft.graphics_spec and draft.graphics_spec.template in {"comparison", "function_plot"}
                else "graphic"
                if draft.kind != "media"
                else draft.category
            ),
            "description": draft.description,
            "subjects": draft.subjects,
            "tags": draft.tags,
            "strategy": strategy,
            "kind": draft.kind,
            "graphics_spec": draft.graphics_spec.model_dump(mode="json") if draft.graphics_spec else None,
            "fallback_graphics_spec": (
                draft.fallback_graphics_spec.model_dump(mode="json") if draft.fallback_graphics_spec else None
            ),
            "search_queries": draft.search_queries,
        },
        planned_duration_seconds=duration,
        motion=motion,
        transition_in="cut" if index == 0 or continuation else draft.transition_in,
        motion_reason=draft.motion_reason or draft.objective,
    )


def _split_words(text: str, count: int) -> tuple[str, ...]:
    words = text.split()
    count = min(count, len(words))
    return tuple(
        " ".join(words[start:end])
        for index in range(count)
        if (start := round(index * len(words) / count)) < (end := round((index + 1) * len(words) / count))
    )


def contains_named_person(subjects: list[str]) -> bool:
    return any(
        len(subject.split()) >= 2 and all(part[:1].isupper() for part in subject.split()) for subject in subjects
    )
