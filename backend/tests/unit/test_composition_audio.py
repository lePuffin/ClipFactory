from pathlib import Path

import pytest

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, VisualInput


@pytest.mark.unit
@pytest.mark.req("CF-REQ-351")
def test_output_audio_is_stereo_aac_at_48khz() -> None:
    spec = CompositionSpec(
        segments=(VisualInput(Path("image.png"), "image", 720, 1280, 71.3),),
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=70,
    )
    command = build_ffmpeg_command(spec)
    assert command[command.index("-ac") + 1] == "2"
    assert command[command.index("-ar") + 1] == "48000"
    assert command[command.index("-c:a") + 1] == "aac"
