from app.models.clip import ClipCandidate
from app.pipelines.selection import select_non_overlapping


def clip(start: float, end: float, score: int) -> ClipCandidate:
    return ClipCandidate(
        start=start,
        end=end,
        score=score,
        title=f"Clip {score}",
        reason="A complete and engaging thought.",
    )


def test_selection_prefers_high_scores_and_removes_overlaps() -> None:
    selected = select_non_overlapping(
        [clip(0, 30, 80), clip(10, 40, 95), clip(42, 70, 90), clip(72, 100, 85)],
        clip_count=3,
        source_duration=100,
    )

    assert [(item.start, item.score) for item in selected] == [(10, 95), (42, 90), (72, 85)]


def test_selection_ignores_ranges_outside_the_source() -> None:
    selected = select_non_overlapping([clip(80, 120, 99), clip(10, 40, 80)], 2, source_duration=100)

    assert selected == [clip(10, 40, 80)]
