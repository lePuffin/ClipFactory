from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from faster_whisper.audio import decode_audio

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, VisualInput
from clipfactory.infrastructure.media.runner import MediaRunner


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-351")
@pytest.mark.req("CF-REQ-352")
@pytest.mark.req("CF-REQ-353")
@pytest.mark.req("CF-REQ-354")
@pytest.mark.asyncio
async def test_real_ffmpeg_renders_vertical_captioned_clip_and_full_decode(tmp_path: Path) -> None:
    runner = MediaRunner(timeout_seconds=120)
    image = tmp_path / "blue.png"
    narration = tmp_path / "narration.wav"
    captions = tmp_path / "captions.ass"
    output = tmp_path / "clip.mp4"
    await runner.ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=720x1280:r=30",
            "-frames:v",
            "1",
            str(image),
        ]
    )
    await runner.ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            str(narration),
        ]
    )
    decoded_audio = decode_audio(str(narration), sampling_rate=16_000)
    assert len(decoded_audio) == 32_000
    ass_format = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    )
    captions.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "PlayResX: 720",
                "PlayResY: 1280",
                "[V4+ Styles]",
                ass_format,
                "Style: Default,DejaVu Sans,56,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,3,1,2,2,43,43,128,1",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:00.30,0:00:02.30,Default,,0,0,0,,A tested Clip",
            ]
        ),
        encoding="utf-8",
    )
    spec = CompositionSpec(
        segments=(VisualInput(image, "image", 720, 1280, 3.3, "ken_burns"),),
        narration_path=narration,
        caption_file=captions,
        output_path=output,
        narration_duration_seconds=2,
    )
    await runner.ffmpeg(build_ffmpeg_command(spec), timeout_seconds=120)
    probe: dict[str, Any] = await runner.probe(output)
    await runner.decode(output)

    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert (video["width"], video["height"]) == (720, 1280)
    assert video["codec_name"] == "h264"
    assert video["r_frame_rate"] == "30/1"
    assert audio["codec_name"] == "aac"
    assert audio["sample_rate"] == "48000"
    assert float(probe["format"]["duration"]) == pytest.approx(3.3, abs=1 / 30)

    transitions = replace(
        spec,
        segments=(
            VisualInput(image, "image", 720, 1280, 1.1),
            VisualInput(output, "video", 720, 1280, 1.1, "none", "crossfade"),
            VisualInput(image, "image", 720, 1280, 1.1, "pan_right", "crossfade"),
        ),
        output_path=tmp_path / "transitions.mp4",
    )
    await runner.ffmpeg(build_ffmpeg_command(transitions), timeout_seconds=120)
    transitioned_probe = await runner.probe(transitions.output_path)
    await runner.decode(transitions.output_path)
    transitioned_video = next(stream for stream in transitioned_probe["streams"] if stream["codec_type"] == "video")
    assert float(transitioned_probe["format"]["duration"]) == pytest.approx(3.3, abs=1 / 30)
    assert int(transitioned_video["nb_frames"]) == 99

    jpeg = tmp_path / "blue.jpg"
    await runner.ffmpeg(["-i", str(image), "-frames:v", "1", str(jpeg)])
    jpeg_spec = replace(
        spec,
        segments=(VisualInput(jpeg, "image", 720, 1280, 3.3, "ken_burns"),),
        output_path=tmp_path / "jpeg-source.mp4",
    )
    await runner.ffmpeg(build_ffmpeg_command(jpeg_spec), timeout_seconds=120)
    jpeg_probe = await runner.probe(jpeg_spec.output_path)
    jpeg_video = next(stream for stream in jpeg_probe["streams"] if stream["codec_type"] == "video")
    assert jpeg_video["pix_fmt"] == "yuv420p"
    assert jpeg_video["color_range"] == "tv"
