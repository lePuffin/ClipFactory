"""Reconcile Visual Segment timing from aligned narration words."""

from __future__ import annotations

from collections import defaultdict
from itertools import pairwise
from math import ceil
from typing import Any

from clipfactory.production.alignment import AlignedWord


def reconcile_visual_timing(
    segments: list[dict[str, Any]],
    words: tuple[AlignedWord, ...],
    *,
    narration_duration_seconds: float,
    lead_in_seconds: float,
    tail_seconds: float,
    max_segment_seconds: float = 8.0,
) -> list[dict[str, Any]]:
    if max_segment_seconds <= 0:
        raise ValueError("maximum Visual Segment duration must be positive")
    by_script: dict[int, list[AlignedWord]] = defaultdict(list)
    for word in words:
        by_script[word.script_segment_index].append(word)
    output: list[dict[str, Any]] = []
    cursor = 0.0
    for script_index in sorted({int(item["script_segment_index"]) for item in segments}):
        group = [item for item in segments if int(item["script_segment_index"]) == script_index]
        script_words = by_script.get(script_index, [])
        group_start = script_words[0].start_seconds + lead_in_seconds if script_words else cursor
        group_end = script_words[-1].end_seconds + lead_in_seconds if script_words else group_start
        weights = [float(item["planned_duration_seconds"]) for item in group]
        total = sum(weights) or 1.0
        boundary = group_start
        for index, (item, weight) in enumerate(zip(group, weights, strict=True)):
            end = group_end if index == len(group) - 1 else boundary + (group_end - group_start) * weight / total
            output.append({**item, "start_seconds": boundary, "end_seconds": end})
            boundary = end
        cursor = group_end
    clip_duration = lead_in_seconds + narration_duration_seconds + tail_seconds
    if output:
        output[0]["start_seconds"] = 0.0
        output[-1]["end_seconds"] = clip_duration
        for previous, current in pairwise(output):
            current["start_seconds"] = previous["end_seconds"]
    bounded: list[dict[str, Any]] = []
    for item in output:
        start = float(item["start_seconds"])
        end = float(item["end_seconds"])
        pieces = max(1, ceil((end - start) / max_segment_seconds))
        for piece in range(pieces):
            bounded.append(
                {
                    **item,
                    "index": len(bounded),
                    "start_seconds": start + (end - start) * piece / pieces,
                    "end_seconds": end if piece == pieces - 1 else start + (end - start) * (piece + 1) / pieces,
                    "transition_in": item.get("transition_in", "cut") if piece == 0 else "cut",
                }
            )
    return bounded
