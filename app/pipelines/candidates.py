"""Build bounded transcript windows for LLM evaluation."""

from dataclasses import dataclass

from app.models.transcript import TranscriptSegment


@dataclass(frozen=True, slots=True)
class CandidateWindow:
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


class CandidateGenerator:
    """Creates timestamp-aligned windows without arbitrarily splitting speech."""

    def __init__(
        self,
        min_duration: float = 30,
        target_duration: float = 60,
        max_duration: float = 90,
        max_candidates: int = 200,
    ) -> None:
        if not 0 < min_duration <= target_duration <= max_duration:
            raise ValueError("candidate durations must satisfy 0 < min <= target <= max")
        if max_candidates < 1:
            raise ValueError("max_candidates must be at least one")
        self.min_duration = min_duration
        self.target_duration = target_duration
        self.max_duration = max_duration
        self.max_candidates = max_candidates

    def build(self, segments: list[TranscriptSegment]) -> list[CandidateWindow]:
        """Return overlapping candidate windows that start and end on speech boundaries."""
        ordered_segments = sorted(segments, key=lambda segment: (segment.start, segment.end))
        candidates: list[CandidateWindow] = []

        for start_index in _sample_indices(len(ordered_segments), self.max_candidates):
            first_segment = ordered_segments[start_index]
            text_parts: list[str] = []
            best_window: CandidateWindow | None = None
            closest_duration = float("inf")
            for end_index in range(start_index, len(ordered_segments)):
                current_segment = ordered_segments[end_index]
                duration = current_segment.end - first_segment.start
                if duration > self.max_duration:
                    break

                text_parts.append(current_segment.text)
                if duration < self.min_duration:
                    continue

                window = CandidateWindow(
                    start=first_segment.start,
                    end=current_segment.end,
                    text=" ".join(text_parts),
                )
                if abs(duration - self.target_duration) < closest_duration:
                    best_window = window
                    closest_duration = abs(duration - self.target_duration)
                if duration >= self.target_duration:
                    break

            if best_window is not None:
                candidates.append(best_window)

        return candidates


def _sample_indices(length: int, maximum: int) -> list[int]:
    if length <= maximum:
        return list(range(length))
    if maximum == 1:
        return [0]
    return sorted({round(index * (length - 1) / (maximum - 1)) for index in range(maximum)})
