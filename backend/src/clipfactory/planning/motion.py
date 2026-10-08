"""Deterministic per-shot motion so still images never sit frozen on screen (CF-REQ-253)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from clipfactory.composition.spec import Motion

_TEXT_BEARING = frozenset({"title_card", "map", "chart", "diagram", "graphic"})
_REVERSE: dict[str, Motion] = {
    "zoom_in": "zoom_out",
    "zoom_out": "zoom_in",
    "ken_burns": "zoom_out",
    "pan_left": "pan_right",
    "pan_right": "pan_left",
    "pan_up": "pan_down",
    "pan_down": "pan_up",
}


@dataclass(frozen=True, slots=True)
class ShotMedia:
    media_type: str
    category: str
    width: int
    height: int
    requested_motion: str
    asset_id: str
    script_segment_index: int | None = None
    requested_reason: str = ""


@dataclass(frozen=True, slots=True)
class ShotMotion:
    motion: Motion
    reason: str


def choose_shot_motions(shots: Sequence[ShotMedia]) -> list[ShotMotion]:
    chosen: list[ShotMotion] = []
    for index, shot in enumerate(shots):
        previous = shots[index - 1] if index else None
        recent: set[Motion] = {item.motion for item in chosen[-2:]}
        if shot.media_type == "video":
            chosen.append(ShotMotion(_motion(shot.requested_motion), shot.requested_reason or "native video movement"))
        elif (
            previous is not None
            and previous.asset_id == shot.asset_id
            and previous.script_segment_index == shot.script_segment_index
            and chosen[-1].motion in _REVERSE
        ):
            chosen.append(ShotMotion(_REVERSE[chosen[-1].motion], "continues the previous move on the same image"))
        elif shot.requested_motion != "none":
            chosen.append(ShotMotion(_motion(shot.requested_motion), shot.requested_reason or "scripted move"))
        elif shot.category in _TEXT_BEARING:
            motion = _first_fresh(("zoom_in", "zoom_out"), recent)
            chosen.append(ShotMotion(motion, "gentle push keeps text and graphics readable"))
        elif shot.width >= shot.height:
            motion = _first_fresh(("zoom_in", "pan_right", "zoom_out", "pan_left"), recent)
            chosen.append(ShotMotion(motion, "slow move across a wide still holds attention"))
        else:
            motion = _first_fresh(("zoom_in", "pan_up", "zoom_out", "pan_down"), recent)
            chosen.append(ShotMotion(motion, "slow push toward the subject of a tall still"))
    return chosen


def _first_fresh(candidates: tuple[Motion, ...], recent: set[Motion]) -> Motion:
    for candidate in candidates:
        if candidate not in recent:
            return candidate
    return candidates[0]


def _motion(value: str) -> Motion:
    if value not in {*_REVERSE, "none"}:
        raise ValueError(f"unsupported motion {value!r}")
    return cast(Motion, value)
