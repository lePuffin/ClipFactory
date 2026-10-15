"""Reconcile Visual Segment timing from aligned narration words."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise
from math import ceil
from typing import Any, Protocol

from clipfactory.production.alignment import AlignedWord


def reconcile_visual_timing(
    segments: list[dict[str, Any]],
    words: tuple[AlignedWord, ...],
    *,
    narration_duration_seconds: float,
    lead_in_seconds: float,
    tail_seconds: float,
    max_segment_seconds: float = 8.0,
    min_segment_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    if max_segment_seconds <= 0:
        raise ValueError("maximum Visual Segment duration must be positive")
    by_script: dict[int, list[AlignedWord]] = defaultdict(list)
    for word in words:
        by_script[word.script_segment_index].append(word)
    output: list[dict[str, Any]] = []
    cursor = 0.0
    clip_duration = lead_in_seconds + narration_duration_seconds + tail_seconds
    script_indices = sorted({int(item["script_segment_index"]) for item in segments})
    for script_index in script_indices:
        group = [item for item in segments if int(item["script_segment_index"]) == script_index]
        script_words = by_script.get(script_index, [])
        group_start = script_words[0].start_seconds + lead_in_seconds if script_words else cursor
        group_end = script_words[-1].end_seconds + lead_in_seconds if script_words else group_start
        if script_index == script_indices[0]:
            group_start = 0.0
        if script_index == script_indices[-1]:
            group_end = clip_duration
        weights = [float(item["planned_duration_seconds"]) for item in group]
        total = sum(weights) or 1.0
        boundary = group_start
        for index, (item, weight) in enumerate(zip(group, weights, strict=True)):
            end = group_end if index == len(group) - 1 else boundary + (group_end - group_start) * weight / total
            output.append({**item, "start_seconds": boundary, "end_seconds": end})
            boundary = end
        cursor = group_end
    if output:
        output[0]["start_seconds"] = 0.0
        output[-1]["end_seconds"] = clip_duration
        for previous, current in pairwise(output):
            current["start_seconds"] = previous["end_seconds"]
        _lengthen_short_pieces(output, min_segment_seconds)
    bounded: list[dict[str, Any]] = []
    source_cursors: dict[str, float] = {}
    for item in output:
        start = float(item["start_seconds"])
        end = float(item["end_seconds"])
        pieces = max(1, ceil((end - start) / max_segment_seconds))
        source_key = str(item.get("selected_asset_id") or f"plan:{item.get('plan_segment_index', item.get('index'))}")
        offset = source_cursors.get(source_key, 0.0)
        for piece in range(pieces):
            bounded.append(
                {
                    **item,
                    "index": len(bounded),
                    "plan_segment_index": item.get("plan_segment_index", item.get("index")),
                    "planned_duration_seconds": float(item["planned_duration_seconds"]) / pieces,
                    "start_seconds": start + (end - start) * piece / pieces,
                    "end_seconds": end if piece == pieces - 1 else start + (end - start) * (piece + 1) / pieces,
                    # Retry may supply an already-split plan; count all preceding uses of this source.
                    "source_offset_seconds": offset + (end - start) * piece / pieces,
                    "transition_in": item.get("transition_in", "cut") if piece == 0 else "cut",
                }
            )
        source_cursors[source_key] = offset + end - start
    return bounded


def _lengthen_short_pieces(output: list[dict[str, Any]], minimum: float) -> None:
    """CF-REQ-257: borrow time from the longer neighbour so a short spoken mention still meets the minimum."""
    if minimum <= 0:
        return

    def length(index: int) -> float:
        return float(output[index]["end_seconds"]) - float(output[index]["start_seconds"])

    for index in range(len(output)):
        need = minimum - length(index)
        if need <= 0:
            continue
        need += 0.001  # float drift must not leave the piece a hair under the gate minimum
        neighbours = sorted(
            (other for other in (index - 1, index + 1) if 0 <= other < len(output)), key=length, reverse=True
        )
        for other in neighbours:
            give = min(need, length(other) - minimum)
            if give <= 0:
                continue
            if other < index:
                output[index]["start_seconds"] = float(output[index]["start_seconds"]) - give
                output[other]["end_seconds"] = output[index]["start_seconds"]
            else:
                output[index]["end_seconds"] = float(output[index]["end_seconds"]) + give
                output[other]["start_seconds"] = output[index]["end_seconds"]
            need -= give
            if need <= 0:
                break


class _HasDuration(Protocol):
    @property
    def duration_seconds(self) -> float | None: ...


def prefer_covering_footage[C: _HasDuration, S](
    ordered: Sequence[tuple[C, S]], required_seconds: float
) -> list[tuple[C, S]]:
    """CF-REQ-256: stably move video candidates long enough to cover a segment ahead of shorter ones."""
    return sorted(ordered, key=lambda pair: (pair[0].duration_seconds or 0.0) < required_seconds)


def short_footage(duration_seconds: float | None, *, offset_seconds: float, shown_seconds: float) -> bool:
    """True when footage cannot cover its piece from the offset even with the 1.0 s last-frame hold."""
    return duration_seconds is not None and duration_seconds + 1.0 < offset_seconds + shown_seconds
