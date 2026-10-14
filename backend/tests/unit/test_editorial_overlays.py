from dataclasses import replace
from pathlib import Path

import pytest

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import AudioInput, CompositionSpec, OverlayInput, VisualInput


def spec():
    return CompositionSpec(
        segments=(VisualInput(Path("photo.jpg"), "image", 720, 1280, 71.3),),
        narration_path=Path("voice.wav"),
        caption_file=Path("subtitles.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=70,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-259")
@pytest.mark.req("CF-REQ-360")
def test_independent_overlay_has_own_timing_and_deterministic_command():
    value = replace(spec(), overlays=(OverlayInput(Path("place.png"), 3, 9, 44, 140, 500, 100),))
    command = build_ffmpeg_command(value)
    graph = command[command.index("-filter_complex") + 1]
    assert "between(t,3,9)" in graph
    assert "overlay=x=44:y=140" in graph
    assert command == build_ffmpeg_command(value)
    assert value.sha256() != spec().sha256()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-261")
@pytest.mark.parametrize(("start", "end", "x"), [(-1, 4, 44), (3, 73, 44), (3, 9, 600)])
def test_invalid_overlay_time_or_bounds_blocks_render(start, end, x):
    value = replace(spec(), overlays=(OverlayInput(Path("place.png"), start, end, x, 140, 500, 100),))
    with pytest.raises(ValueError, match="editorial overlay"):
        build_ffmpeg_command(value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-261")
def test_overlapping_editorial_cues_are_rejected():
    cue = OverlayInput(Path("place.png"), 3, 9, 44, 140, 500, 100)
    value = replace(spec(), overlays=(cue, replace(cue, path=Path("person.png"), start_seconds=5)))
    with pytest.raises(ValueError, match="collide"):
        build_ffmpeg_command(value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-324")
@pytest.mark.req("CF-REQ-325")
def test_overlay_music_and_sfx_input_indexes_and_single_mix_are_stable():
    value = replace(
        spec(),
        music_path=Path("music.wav"),
        overlays=(OverlayInput(Path("place.png"), 3, 9, 44, 140, 500, 100),),
        sound_effects=(AudioInput(Path("whoosh.wav"), 3, 0.5),),
    )
    command = build_ffmpeg_command(value)
    graph = command[command.index("-filter_complex") + 1]
    assert "[3:v]" in graph
    assert "[4:a]" in graph
    assert "amix=inputs=3" in graph
    assert "adelay=3000:all=1" in graph
    assert command.count("[aout]") == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-324")
def test_out_of_span_sound_cue_blocks_render():
    with pytest.raises(ValueError, match="sound cue"):
        build_ffmpeg_command(replace(spec(), sound_effects=(AudioInput(Path("sfx.wav"), 71, 2),)))
