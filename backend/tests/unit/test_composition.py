from pathlib import Path

import pytest

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, VisualInput


def make_spec() -> CompositionSpec:
    return CompositionSpec(
        segments=(
            VisualInput(Path("/data/assets/portrait.png"), "image", 720, 1280, 35.65, "ken_burns"),
            VisualInput(
                Path("/data/assets/news footage.mp4"),
                "video",
                1920,
                1080,
                35.65,
                "none",
                "crossfade",
            ),
        ),
        narration_path=Path("/data/work/narration.wav"),
        caption_file=Path("/data/work/captions.ass"),
        output_path=Path("/data/clips/final.mp4"),
        narration_duration_seconds=70,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-350")
@pytest.mark.req("CF-REQ-357")
def test_composition_spec_hash_and_command_are_deterministic() -> None:
    first = make_spec()
    second = make_spec()
    assert first.sha256() == second.sha256()
    assert build_ffmpeg_command(first) == build_ffmpeg_command(second)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-255")
@pytest.mark.req("CF-REQ-314")
def test_command_fits_landscape_over_blur_and_burns_captions() -> None:
    command = build_ffmpeg_command(make_spec())
    graph = command[command.index("-filter_complex") + 1]
    assert "boxblur=24:2" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph
    assert "subtitles=filename='/data/work/captions.ass'" in graph
    assert "xfade=transition=fade" in graph
    assert "-movflags" in command
    assert "+faststart" in command


@pytest.mark.unit
@pytest.mark.req("CF-REQ-350")
def test_composition_rejects_visual_duration_drift() -> None:
    spec = make_spec()
    invalid = CompositionSpec(
        segments=(VisualInput(Path("/data/assets/a.png"), "image", 720, 1280, 1, "none"),),
        narration_path=spec.narration_path,
        caption_file=spec.caption_file,
        output_path=spec.output_path,
        narration_duration_seconds=70,
    )
    with pytest.raises(ValueError, match="cover Clip duration"):
        build_ffmpeg_command(invalid)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-254")
@pytest.mark.req("CF-REQ-256")
def test_crossfade_overlap_is_compensated_and_video_does_not_loop() -> None:
    command = build_ffmpeg_command(make_spec())
    graph = command[command.index("-filter_complex") + 1]
    assert "offset=35.65" in graph
    assert "trim=duration=36.05" in graph
    assert "-stream_loop" not in command
    assert "tpad=stop_mode=clone:stop_duration=1" in graph


@pytest.mark.unit
@pytest.mark.req("CF-REQ-262")
def test_motion_crop_uses_supersampled_full_chroma_coordinates() -> None:
    command = build_ffmpeg_command(make_spec())
    graph = command[command.index("-filter_complex") + 1]
    assert "scale=w=4*iw:h=4*ih:flags=lanczos,format=yuv444p,zoompan=" in graph
