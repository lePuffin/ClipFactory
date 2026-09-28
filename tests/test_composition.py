from pathlib import Path

from app.models.broll import BRollClip, BRollKind, VideoSourceContext
from app.models.media import VideoMetadata
from app.models.script import NarrationTiming
from app.services.composition import ClipCompositionService
from app.services.ffmpeg import FFmpegService
from app.services.framing import SmartFramingPlanner
from app.services.tts import NarrationAudio


def test_ffmpeg_builds_safe_placeholder_and_clip_composition_commands() -> None:
    service = FFmpegService(output_width=720, output_height=1280)
    placeholder_command = service.build_placeholder_command(Path("placeholder.mp4"), 3.5, "#23716e")
    composition_command = service.build_clip_composition_command(
        [Path("one.mp4"), Path("two.mp4")],
        Path("narration.wav"),
        Path("clip.mp4"),
    )

    assert placeholder_command[0] == "ffmpeg"
    placeholder_filter = placeholder_command[placeholder_command.index("-i") + 1]
    assert "color=c=0x23716e:s=720x1280" in placeholder_filter
    assert "NEWS BRIEF" in placeholder_filter
    filter_graph = composition_command[composition_command.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[video]" in filter_graph
    assert composition_command[composition_command.index("-map") + 1] == "[video]"
    assert "narration.wav" in composition_command


def test_ffmpeg_uses_text_files_for_reel_overlays_and_silent_scene_composition(
    tmp_path: Path,
) -> None:
    service = FFmpegService(output_width=720, output_height=1280)
    overlay = tmp_path / "overlay.txt"
    font_size = service.write_overlay_text(
        "A generated statement: $not a filter expression.", overlay
    )
    command = service.build_text_card_command(
        tmp_path / "scene.mp4",
        3,
        overlay,
        font_size,
    )
    composition = service.build_silent_composition_command(
        [tmp_path / "one.mp4", tmp_path / "two.mp4"],
        tmp_path / "story_01.mp4",
    )

    video_filter = command[command.index("-vf") + 1]
    filter_graph = composition[composition.index("-filter_complex") + 1]
    assert "textfile='" in video_filter
    assert "$not a filter expression" not in video_filter
    assert "concat=n=2:v=1:a=0[video]" in filter_graph
    assert "-an" in composition


def test_ffmpeg_wraps_long_reel_overlay_text_within_the_vertical_safe_width(
    tmp_path: Path,
) -> None:
    service = FFmpegService()
    overlay = tmp_path / "overlay.txt"

    service.write_overlay_text(
        "Berkshire Hathaway recommended a $10 billion investment in Alphabet, with ongoing "
        "discussions between Berkshire and Warren.",
        overlay,
    )

    lines = overlay.read_text(encoding="utf-8").splitlines()
    command = service.build_text_card_command(tmp_path / "scene.mp4", 3, overlay, 53)
    video_filter = command[command.index("-vf") + 1]

    assert all(len(line) <= 24 for line in lines)
    assert [
        (tmp_path / f"overlay-line-{index:02d}.txt").read_text(encoding="utf-8")
        for index in range(1, len(lines) + 1)
    ] == lines
    assert video_filter.count("drawtext=") == len(lines)
    assert "drawbox=x=(iw-952)/2:y=ih-" in video_filter


class FakeFFmpeg:
    def __init__(self) -> None:
        self.rendered: list[Path] = []
        self.placeholders: list[Path] = []
        self.composed: tuple[list[Path], Path, Path] | None = None

    def render_vertical(self, _: Path, destination: Path, *__: object) -> None:
        self.rendered.append(destination)

    def render_placeholder(self, destination: Path, *_: object) -> None:
        self.placeholders.append(destination)

    def compose_clip(self, visuals: list[Path], narration: Path, destination: Path) -> None:
        self.composed = visuals, narration, destination


class FakeCropper:
    def plan_framing(self, _: Path, metadata: VideoMetadata, start: float, end: float) -> object:
        return SmartFramingPlanner().plan(metadata, end - start, ())


def test_composer_uses_video_for_source_broll_and_placeholder_for_remaining_timeline(
    tmp_path: Path,
) -> None:
    ffmpeg = FakeFFmpeg()
    source = VideoSourceContext(
        source_id="video-01",
        path=tmp_path / "source.mp4",
        metadata=VideoMetadata(duration=30, width=1920, height=1080, has_audio=True),
        transcript=(),
    )
    narration = NarrationAudio(
        path=tmp_path / "narration.wav",
        duration=6,
        timings=(NarrationTiming(sentence_index=0, start=0, end=6),),
    )
    timeline = [
        BRollClip(
            kind=BRollKind.VIDEO,
            sentence_index=0,
            timeline_start=0,
            timeline_end=3,
            source_id="video-01",
            source_start=4,
            source_end=7,
            visual_label="Source video",
        ),
        BRollClip(
            kind=BRollKind.PLACEHOLDER,
            sentence_index=1,
            timeline_start=3,
            timeline_end=6,
            visual_label="News brief",
        ),
    ]

    ClipCompositionService(ffmpeg, FakeCropper()).compose(  # type: ignore[arg-type]
        narration,
        timeline,
        [source],
        tmp_path,
        tmp_path / "clip.mp4",
    )

    assert len(ffmpeg.rendered) == 1
    assert len(ffmpeg.placeholders) == 1
    assert ffmpeg.composed is not None
    assert len(ffmpeg.composed[0]) == 2
