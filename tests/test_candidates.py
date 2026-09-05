from app.models.transcript import TranscriptSegment
from app.pipelines.candidates import CandidateGenerator


def test_candidate_generator_keeps_transcript_boundaries() -> None:
    segments = [
        TranscriptSegment(start=0, end=11, text="First thought."),
        TranscriptSegment(start=11, end=22, text="Second thought."),
        TranscriptSegment(start=22, end=34, text="Third thought."),
        TranscriptSegment(start=34, end=45, text="Fourth thought."),
    ]

    generator = CandidateGenerator(min_duration=20, target_duration=30, max_duration=45)
    candidates = generator.build(segments)

    assert candidates
    assert candidates[0].start == 0
    assert candidates[0].end == 34
    assert candidates[0].text == "First thought. Second thought. Third thought."
    assert all(20 <= candidate.duration <= 45 for candidate in candidates)


def test_candidate_generator_rejects_invalid_duration_settings() -> None:
    try:
        CandidateGenerator(min_duration=45, target_duration=30, max_duration=90)
    except ValueError as error:
        assert "min <= target <= max" in str(error)
    else:
        raise AssertionError("Expected invalid durations to fail")


def test_candidate_generator_samples_across_a_long_transcript() -> None:
    segments = [
        TranscriptSegment(start=index * 10, end=(index + 1) * 10, text=f"Segment {index}")
        for index in range(500)
    ]

    candidates = CandidateGenerator(
        min_duration=30,
        target_duration=60,
        max_duration=90,
        max_candidates=10,
    ).build(segments)

    assert len(candidates) <= 10
    assert candidates[0].start == 0
    assert max(candidate.start for candidate in candidates) > 4000


def test_candidate_generator_supports_a_single_candidate_limit() -> None:
    segments = [
        TranscriptSegment(start=index * 10, end=(index + 1) * 10, text=f"Segment {index}")
        for index in range(10)
    ]

    candidates = CandidateGenerator(
        min_duration=20,
        target_duration=30,
        max_duration=40,
        max_candidates=1,
    ).build(segments)

    assert len(candidates) == 1
    assert candidates[0].start == 0
