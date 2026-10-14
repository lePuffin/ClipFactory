from pathlib import Path

import pytest

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, VisualInput


def _spec(*segments: VisualInput) -> CompositionSpec:
    return CompositionSpec(
        segments=segments,
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=sum(item.duration_seconds for item in segments) - 1.3,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-256")
def test_continued_piece_seeks_into_the_footage_instead_of_restarting_it() -> None:
    stock = Path("stock.mp4")
    command = build_ffmpeg_command(
        _spec(
            VisualInput(stock, "video", 1080, 1920, 5.0),
            VisualInput(stock, "video", 1080, 1920, 5.0, source_offset_seconds=5.0),
        )
    )
    inputs = [index for index, value in enumerate(command) if value == "-i" and command[index + 1] == str(stock)]
    assert len(inputs) == 2
    assert "-ss" not in command[inputs[0] - 4 : inputs[0]]
    assert command[inputs[1] - 4 : inputs[1]] == ["-ss", "5", "-t", command[inputs[1] - 1]]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-256")
def test_negative_source_offsets_are_rejected() -> None:
    with pytest.raises(ValueError, match="source offsets"):
        build_ffmpeg_command(
            _spec(VisualInput(Path("stock.mp4"), "video", 1080, 1920, 5.0, source_offset_seconds=-1.0))
        )
