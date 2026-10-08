from pathlib import Path

import pytest
from PIL import Image

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import AudioInput, CompositionSpec, OverlayInput, VisualInput
from clipfactory.infrastructure.media.runner import MediaRunner


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-259")
@pytest.mark.req("CF-REQ-324")
@pytest.mark.req("CF-REQ-325")
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_real_editorial_layer_and_three_audio_inputs_render_one_stereo_output(tmp_path: Path):
    runner = MediaRunner(timeout_seconds=120)
    photo = tmp_path / "photo.png"
    label = tmp_path / "label.png"
    narration = tmp_path / "voice.wav"
    music = tmp_path / "music.wav"
    effect = tmp_path / "effect.wav"
    captions = tmp_path / "captions.ass"
    output = tmp_path / "news.mp4"
    Image.new("RGB", (720, 1280), "blue").save(photo)
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(label)
    for path, frequency, duration in ((narration, 440, 3), (music, 220, 5), (effect, 1200, 0.5)):
        await runner.ffmpeg(
            ["-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}", "-ar", "48000", str(path)]
        )
    captions.write_text(
        "".join(
            [
                "[Script Info]\n",
                "ScriptType: v4.00+\n",
                "PlayResX: 720\n",
                "PlayResY: 1280\n",
                "[V4+ Styles]\n",
                "Format: Name, Fontname, Fontsize, PrimaryColour, Bold, Alignment\n",
                "Style: Default,DejaVu Sans,40,&H00FFFFFF,-1,2\n",
                "[Events]\n",
                "Format: Layer, Start, End, Style, Text\n",
            ]
        ),
        encoding="utf-8",
    )
    spec = CompositionSpec(
        segments=(VisualInput(photo, "image", 720, 1280, 4.3),),
        narration_path=narration,
        caption_file=captions,
        output_path=output,
        narration_duration_seconds=3,
        music_path=music,
        overlays=(OverlayInput(label, 1, 3, 44, 140, 200, 100),),
        sound_effects=(AudioInput(effect, 1, 0.5),),
    )
    await runner.ffmpeg(build_ffmpeg_command(spec), timeout_seconds=120)
    probe = await runner.probe(output)
    await runner.decode(output)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    audio = next(stream for stream in probe["streams"] if stream["codec_type"] == "audio")
    assert len([stream for stream in probe["streams"] if stream["codec_type"] == "audio"]) == 1
    assert audio["channels"] == 2
    assert float(video["duration"]) == pytest.approx(4.3, abs=1 / 30)
    for timestamp, expected in ((0.5, "blue"), (2.0, "red")):
        frame = tmp_path / f"frame-{timestamp}.png"
        await runner.ffmpeg(["-ss", str(timestamp), "-i", str(output), "-frames:v", "1", str(frame)])
        with Image.open(frame) as image:
            pixel = image.convert("RGB").getpixel((100, 180))
            assert isinstance(pixel, tuple)
            red, _, blue = pixel
        assert red > blue if expected == "red" else blue > red
