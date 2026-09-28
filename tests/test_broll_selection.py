from pathlib import Path

from app.models.broll import BRollKind, VideoSourceContext
from app.models.media import VideoMetadata
from app.models.script import ClipScript, NarrationTiming, ScriptSentence
from app.models.transcript import TranscriptSegment
from app.services.broll_selection import BRollSelector


def _video_source(source_id: str, transcript: tuple[TranscriptSegment, ...]) -> VideoSourceContext:
    return VideoSourceContext(
        source_id=source_id,
        path=Path(f"{source_id}.mp4"),
        metadata=VideoMetadata(duration=60, width=1920, height=1080, has_audio=True),
        transcript=transcript,
    )


def test_broll_selection_prefers_script_referenced_relevant_video() -> None:
    script = ClipScript(
        title="Market report",
        sentences=[
            ScriptSentence(
                text="The crypto market rallied after the announcement.",
                duration_seconds=5,
                source_ids=["video-02"],
            )
        ],
    )
    sources = [
        _video_source(
            "video-01",
            (TranscriptSegment(start=10, end=15, text="The crypto market rallied today."),),
        ),
        _video_source(
            "video-02",
            (TranscriptSegment(start=30, end=35, text="Officials announced a policy update."),),
        ),
    ]

    selected = BRollSelector().allocate(
        script,
        [NarrationTiming(sentence_index=0, start=0, end=5)],
        sources,
    )

    assert selected[0].kind is BRollKind.VIDEO
    assert selected[0].source_id == "video-02"
    assert selected[0].source_start == 30
    assert selected[0].source_end == 35


def test_broll_selection_fills_an_article_only_clip_with_placeholders() -> None:
    script = ClipScript(
        title="Article report",
        sentences=[
            ScriptSentence(
                text="A report explains an important new development.",
                duration_seconds=4,
            )
        ],
    )

    selected = BRollSelector().allocate(
        script,
        [NarrationTiming(sentence_index=0, start=0, end=4)],
        [],
    )

    assert selected[0].kind is BRollKind.PLACEHOLDER
    assert selected[0].duration == 4


def test_broll_selection_avoids_reusing_the_same_transcript_window() -> None:
    script = ClipScript(
        title="Video report",
        sentences=[
            ScriptSentence(text="Markets moved during the announcement.", duration_seconds=4),
            ScriptSentence(text="Markets moved during the announcement.", duration_seconds=4),
        ],
    )
    source = _video_source(
        "video-01",
        (
            TranscriptSegment(start=10, end=14, text="Markets moved during the announcement."),
            TranscriptSegment(start=30, end=34, text="Markets moved during the announcement."),
        ),
    )

    selected = BRollSelector().allocate(
        script,
        [
            NarrationTiming(sentence_index=0, start=0, end=4),
            NarrationTiming(sentence_index=1, start=4, end=8),
        ],
        [source],
    )

    assert selected[0].source_start != selected[1].source_start