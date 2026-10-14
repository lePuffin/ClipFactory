import io
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from faster_whisper.audio import decode_audio
from PIL import Image

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, OverlayInput, VisualInput
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.production.editorial import render_brand_mark, render_news_date


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-351")
@pytest.mark.req("CF-REQ-352")
@pytest.mark.req("CF-REQ-353")
@pytest.mark.req("CF-REQ-354")
@pytest.mark.req("CF-REQ-360")
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
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 100), (255, 0, 0, 255)).save(logo)
    logo_bytes, logo_width, logo_height = render_brand_mark(logo, 112, 0.7)
    logo.write_bytes(logo_bytes)
    date_text, date_graphic = render_news_date(
        datetime(2026, 10, 8, tzinfo=UTC),
        "Europe/Lisbon",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        720,
    )
    date_path = tmp_path / "date.png"
    date_path.write_bytes(date_graphic.png_bytes)
    assert date_text == "8 Oct 2026"
    spec = CompositionSpec(
        segments=(VisualInput(image, "image", 720, 1280, 3.3, "ken_burns"),),
        narration_path=narration,
        caption_file=captions,
        output_path=output,
        narration_duration_seconds=2,
        overlays=(
            OverlayInput(logo, 0, 3.3, 584, 24, logo_width, logo_height, 0),
            OverlayInput(date_path, 0, 3.3, date_graphic.x, date_graphic.y, date_graphic.width, date_graphic.height, 0),
        ),
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
    for timestamp in (0.0, 1.5, 3.2):
        frame = await runner.extract_frame(output, timestamp, 720)
        with Image.open(io.BytesIO(frame)) as pixels:
            pixel = pixels.convert("RGB").getpixel((640, 50))
            assert isinstance(pixel, tuple)
            red = pixel[0]
            assert 150 < red < 210
            date_area = pixels.crop(
                (
                    date_graphic.x,
                    date_graphic.y,
                    date_graphic.x + date_graphic.width,
                    date_graphic.y + date_graphic.height,
                )
            ).convert("RGB")
            extrema = date_area.getchannel("R").getextrema()
            assert isinstance(extrema[1], (float, int))
            assert extrema[1] > 180

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

    from clipfactory.composition.render import freeze_end_card
    from clipfactory.infrastructure.media.brand_outro import generate_outro
    from clipfactory.infrastructure.storage import LocalStorageProvider

    card = tmp_path / "card.mp4"
    await generate_outro(
        logo,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        card,
        runner=runner,
        voice=narration,
    )
    frozen, digest = await freeze_end_card(
        card, storage=LocalStorageProvider(tmp_path / "frozen"), runner=runner, key="card.mp4"
    )
    ending = replace(
        spec,
        segments=(replace(spec.segments[0], duration_seconds=5.3),),
        tail_seconds=3,
        end_card_path=frozen,
        end_card_sha256=digest,
        output_path=tmp_path / "with-ending.mp4",
    )
    await runner.ffmpeg(build_ffmpeg_command(ending), timeout_seconds=120)
    await runner.decode(ending.output_path)
    ending_probe = await runner.probe(ending.output_path)
    assert float(ending_probe["format"]["duration"]) == pytest.approx(5.3, abs=1 / 30)
    ending_video = next(s for s in ending_probe["streams"] if s["codec_type"] == "video")
    assert int(ending_video["nb_frames"]) == 159
    for timestamp in (2.6, 4.8):
        frame = await runner.extract_frame(ending.output_path, timestamp, 720)
        with Image.open(io.BytesIO(frame)) as pixels:
            pixel = pixels.convert("RGB").getpixel((640, 50))
            assert isinstance(pixel, tuple)
            assert pixel[0] < 30
    ending_audio = decode_audio(str(ending.output_path), sampling_rate=16000)
    assert max(abs(float(ending_audio[index])) for index in range(int(3.4 * 16000), int(4.8 * 16000))) > 0.01
    card.write_bytes(b"invalid media")
    from clipfactory.infrastructure.media.runner import MediaProcessError

    with pytest.raises(MediaProcessError):
        await freeze_end_card(card, storage=LocalStorageProvider(tmp_path / "invalid"), runner=runner, key="card.mp4")

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
