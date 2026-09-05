"""Deterministic validation, ranking, and overlap removal for LLM selections."""

from app.models.clip import ClipCandidate


def rank_clips(clips: list[ClipCandidate]) -> list[ClipCandidate]:
    """Order clips by semantic score, preserving earliest timestamps as a tie breaker."""
    return sorted(clips, key=lambda clip: (-clip.score, clip.start, clip.end))


def clips_overlap(first: ClipCandidate, second: ClipCandidate) -> bool:
    """Return whether two ranges share any media time."""
    return max(first.start, second.start) < min(first.end, second.end)


def select_non_overlapping(
    clips: list[ClipCandidate],
    clip_count: int,
    source_duration: float | None = None,
) -> list[ClipCandidate]:
    """Keep the best valid non-overlapping clips, ordered chronologically for rendering."""
    if clip_count < 1:
        raise ValueError("clip_count must be at least one")
    if source_duration is not None and source_duration <= 0:
        raise ValueError("source_duration must be positive")

    selected: list[ClipCandidate] = []
    for clip in rank_clips(clips):
        if source_duration is not None and clip.end > source_duration:
            continue
        if any(clips_overlap(clip, chosen) for chosen in selected):
            continue
        selected.append(clip)
        if len(selected) == clip_count:
            break

    return sorted(selected, key=lambda clip: (clip.start, clip.end))
