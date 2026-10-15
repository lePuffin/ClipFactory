import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.spec import CompositionSpec, Motion, OverlayInput, VisualInput
from clipfactory.domain.portrait import FaceBox
from clipfactory.infrastructure.media.runner import MediaRunner


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-255")
@pytest.mark.req("CF-REQ-252")
@pytest.mark.req("CF-REQ-360")
@pytest.mark.parametrize("size", [(400, 1200), (720, 1280), (1200, 1600), (1600, 900)])
@pytest.mark.parametrize("motion", ["zoom_in", "pan_down"])
@pytest.mark.parametrize(
    "face", [FaceBox(0.6, 0.04, 0.12, 0.1), FaceBox(0.4, 0.3, 0.15, 0.15), FaceBox(0.02, 0.02, 0.7, 0.7)]
)
async def test_face_marker_is_visible_below_unchanged_banner(
    tmp_path: Path, size: tuple[int, int], motion: Motion, face: FaceBox
) -> None:
    runner = MediaRunner(timeout_seconds=120)
    photo = tmp_path / "person.png"
    width, height = size
    image = Image.new("RGB", size, (0, 0, 90))
    ImageDraw.Draw(image).rectangle(
        (face.x * width, face.y * height, (face.x + face.width) * width, (face.y + face.height) * height),
        fill=(255, 0, 0),
    )
    image.save(photo)
    banner = tmp_path / "banner.png"
    Image.new("RGB", (540, 240), (0, 255, 0)).save(banner)
    audio = tmp_path / "audio.wav"
    await runner.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)])
    captions = tmp_path / "captions.ass"
    captions.write_text("[Script Info]\nScriptType: v4.00+\n[Events]\n", encoding="utf-8")
    spec = CompositionSpec(
        segments=(VisualInput(photo, "image", width, height, 1, motion=motion, face_box=face),),
        narration_path=audio,
        caption_file=captions,
        output_path=tmp_path / "sample.mp4",
        narration_duration_seconds=1,
        lead_in_seconds=0,
        tail_seconds=0,
        preset="ultrafast",
        motion_intensity="high",
        overlays=(OverlayInput(banner, 0, 1, 48, 112, 540, 240, 0),),
    )
    await runner.ffmpeg(build_ffmpeg_command(spec))
    centers = []
    for timestamp in (0, 0.5, 0.9):
        frame = await runner.extract_frame(spec.output_path, timestamp, 720)
        with Image.open(io.BytesIO(frame)) as rendered:
            pixels = np.asarray(rendered.convert("RGB"))
        # Restrict to the sharp foreground, excluding the blurred background's red copy.
        ys, xs = np.where((pixels[:, :, 0] > 240) & (pixels[:, :, 1] < 20) & (pixels[:, :, 2] < 20))
        assert len(xs) > 100
        assert xs.min() >= 0
        assert xs.max() < 720
        assert xs.max() - xs.min() <= 720 * 0.6 + 2
        assert ys.min() > 352 + 1280 * 0.03
        assert ys.max() < 1280 * 0.8 + 2
        assert ys.max() - ys.min() <= 1280 * 0.32 + 2
        expected_ratio = face.width * width / (face.height * height)
        assert (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1) == pytest.approx(expected_ratio, rel=0.08)
        centers.append((float(xs.mean()), float(ys.mean())))
        green = pixels[120:344, 56:580, 1]
        assert float(green.mean()) > 240
        if size == (1200, 1600) and face.y == 0.3:
            assert pixels[700, 10, 2] > 75
            assert pixels[700, 710, 2] > 75
    assert centers[0] == pytest.approx(centers[-1], abs=2)


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-255")
@pytest.mark.parametrize("size", [(400, 1200), (720, 1280), (1600, 900)])
async def test_undetected_portrait_is_entirely_below_banner_without_motion(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    runner = MediaRunner(timeout_seconds=120)
    photo, banner = tmp_path / "portrait.png", tmp_path / "banner.png"
    Image.new("RGB", size, (255, 0, 0)).save(photo)
    Image.new("RGB", (540, 240), (0, 255, 0)).save(banner)
    audio = tmp_path / "audio.wav"
    await runner.ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)])
    captions = tmp_path / "captions.ass"
    captions.write_text("[Script Info]\nScriptType: v4.00+\n[Events]\n", encoding="utf-8")
    spec = CompositionSpec(
        segments=(VisualInput(photo, "image", *size, 1, motion="pan_up", is_person_still=True),),
        narration_path=audio,
        caption_file=captions,
        output_path=tmp_path / "fallback.mp4",
        narration_duration_seconds=1,
        lead_in_seconds=0,
        tail_seconds=0,
        preset="ultrafast",
        overlays=(OverlayInput(banner, 0, 1, 48, 112, 540, 240, 0),),
    )
    await runner.ffmpeg(build_ffmpeg_command(spec))
    bounds = []
    for timestamp in (0, 0.9):
        with Image.open(io.BytesIO(await runner.extract_frame(spec.output_path, timestamp, 720))) as frame:
            pixels = np.asarray(frame.convert("RGB"))
        ys, xs = np.where((pixels[:, :, 0] > 240) & (pixels[:, :, 1] < 20) & (pixels[:, :, 2] < 20))
        assert xs.size > 100
        assert ys.min() > 352 + 1280 * 0.03
        assert ys.max() < 1280 * 0.8 + 2
        assert (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1) == pytest.approx(size[0] / size[1], rel=0.05)
        assert pixels[120:344, 56:580, 1].mean() > 240
        bounds.append((xs.min(), xs.max(), ys.min(), ys.max()))
    assert bounds[0] == bounds[1]
