import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest
from PIL import Image

from clipfactory.composition.ffmpeg_commands import build_ffmpeg_command
from clipfactory.composition.framing import portrait_framing
from clipfactory.composition.spec import CompositionSpec, OverlayInput, VisualInput
from clipfactory.domain.portrait import FaceBox
from clipfactory.infrastructure.media.portraits import detect_portrait_face


@pytest.mark.req("CF-REQ-255")
@pytest.mark.req("CF-REQ-350")
def test_face_bounds_change_hash_and_fill_width_without_changing_overlays() -> None:
    base = CompositionSpec(
        segments=(VisualInput(Path("portrait.png"), "image", 720, 1280, 71.3),),
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=70,
    )
    face = FaceBox(0.2, 0.05, 0.2, 0.15)
    spec = replace(base, segments=(replace(base.segments[0], duration_seconds=71.3, face_box=face),))
    graph = build_ffmpeg_command(spec)[build_ffmpeg_command(spec).index("-filter_complex") + 1]
    assert "[fg0]scale=720:1280" in graph
    assert "overlay=x=0:" in graph
    assert "boxblur=24:2" in graph
    assert spec.overlays == base.overlays
    assert replace(spec, segments=(replace(spec.segments[0], face_box=None),)).sha256() != spec.sha256()
    assert build_ffmpeg_command(spec) == build_ffmpeg_command(spec)
    assert replace(spec, portrait_framing_version="face-centered-v1").sha256() != spec.sha256()


@pytest.mark.req("CF-REQ-255")
def test_safe_cover_uses_no_blurred_background_and_no_motion() -> None:
    spec = CompositionSpec(
        segments=(
            VisualInput(
                Path("person.png"), "image", 1200, 1600, 1, motion="pan_down", face_box=FaceBox(0.4, 0.4, 0.15, 0.15)
            ),
        ),
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=1,
        lead_in_seconds=0,
        tail_seconds=0,
    )
    command = build_ffmpeg_command(spec)
    graph = command[command.index("-filter_complex") + 1]
    assert "scale=960:1280,crop=720:1280:" in graph
    assert "boxblur" not in graph
    assert "zoompan" not in graph


@pytest.mark.req("CF-REQ-255")
@pytest.mark.parametrize("banner_height", [176, 240, 480])
def test_active_banner_height_controls_face_safe_area(banner_height: int) -> None:
    spec = CompositionSpec(
        segments=(
            VisualInput(Path("person.png"), "image", 720, 1280, 1, face_box=FaceBox(0.4, 0.04, 0.15, 0.1)),
            VisualInput(Path("second.png"), "image", 720, 1280, 2),
        ),
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=3,
        lead_in_seconds=0,
        tail_seconds=0,
        overlays=(
            OverlayInput(Path("banner.png"), 0, 1, 44, 112, 536, banner_height),
            OverlayInput(Path("later.png"), 2, 3, 44, 112, 536, 1000),
        ),
    )
    command = build_ffmpeg_command(spec)
    graph = command[command.index("-filter_complex") + 1]
    match = re.search(r"\[blur0\]\[fit0\]overlay=x=0:y=(\d+)", graph)
    assert match is not None
    face_top = int(match[1]) + 0.04 * 1280
    assert face_top >= 112 + banner_height + 0.03 * 1280 + 0.3 * 0.1 * 1280 - 1
    assert "geq=" in graph


@pytest.mark.req("CF-REQ-255")
@pytest.mark.parametrize("box", [(-0.1, 0, 0.2, 0.2), (0, 0, 0, 0.2), (0.9, 0, 0.2, 0.2), (0, float("nan"), 0.2, 0.2)])
def test_invalid_face_bounds_are_rejected(box: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError, match="normalized"):
        FaceBox(*box)


@pytest.mark.req("CF-REQ-255")
def test_face_position_is_not_applied_to_video() -> None:
    spec = CompositionSpec(
        segments=(VisualInput(Path("video.mp4"), "video", 720, 1280, 1, face_box=FaceBox(0.2, 0.1, 0.2, 0.2)),),
        narration_path=Path("narration.wav"),
        caption_file=Path("captions.ass"),
        output_path=Path("clip.mp4"),
        narration_duration_seconds=1,
        lead_in_seconds=0,
        tail_seconds=0,
    )
    with pytest.raises(ValueError, match="still images"):
        build_ffmpeg_command(spec)


@pytest.mark.req("CF-REQ-255")
async def test_retained_framing_reuses_evidence_and_nonperson_does_not_detect() -> None:
    detector = AsyncMock(return_value=FaceBox(0.3, 0.1, 0.2, 0.2))
    face, retained = await portrait_framing(Path("person.jpg"), is_person_still=True, retained=None, detector=detector)
    assert face == FaceBox(0.3, 0.1, 0.2, 0.2)
    assert retained is not None
    assert retained["status"] == "detected"
    assert retained["version"] == "face-safe-v3"
    again = await portrait_framing(Path("person.jpg"), is_person_still=True, retained=retained, detector=detector)
    assert again == (face, retained)
    assert (await portrait_framing(Path("landscape.jpg"), is_person_still=False, retained=None, detector=detector)) == (
        None,
        None,
    )
    detector.assert_awaited_once()


@pytest.mark.req("CF-REQ-255")
async def test_replaced_source_does_not_reuse_face_evidence() -> None:
    detector = AsyncMock(return_value=FaceBox(0.3, 0.2, 0.2, 0.2))
    retained = {"source_sha256": "old", "face_box": {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1}}
    face, evidence = await portrait_framing(
        Path("replacement.jpg"),
        is_person_still=True,
        retained=retained,
        detector=detector,
        source_sha256="new",
    )
    assert face == FaceBox(0.3, 0.2, 0.2, 0.2)
    assert evidence is not None
    assert evidence["source_sha256"] == "new"
    detector.assert_awaited_once()


@pytest.mark.req("CF-REQ-255")
@pytest.mark.parametrize("error", [None, OSError("bad image"), RuntimeError("missing cascade")])
async def test_unavailable_face_uses_banner_safe_fit_and_logs(error: Exception | None, caplog: Any) -> None:
    detector = AsyncMock(return_value=None, side_effect=error)
    face, evidence = await portrait_framing(
        Path("portrait.jpg"), is_person_still=True, retained=None, detector=detector
    )
    assert face is None
    assert evidence is not None
    assert evidence["fallback"] == "banner_safe_fit"
    assert evidence["status"] == "unavailable"
    assert "portrait_framing_unavailable" in caplog.text


@pytest.mark.req("CF-REQ-255")
async def test_retained_unavailable_face_adopts_safe_fallback_without_inventing_bounds() -> None:
    detector = AsyncMock()
    face, evidence = await portrait_framing(
        Path("araujo.jpg"),
        is_person_still=True,
        retained={"source_sha256": "same", "face_box": None, "fallback": "standard_fit", "version": "face-safe-v2"},
        detector=detector,
        source_sha256="same",
    )
    assert face is None
    assert evidence is not None
    assert evidence["fallback"] == "banner_safe_fit"
    assert evidence["version"] == "face-safe-v3"
    detector.assert_not_awaited()


@pytest.mark.req("CF-REQ-255")
@pytest.mark.parametrize(
    ("boxes", "weights", "expected"),
    [
        ([], [], None),
        ([(20, 10, 40, 40)], [4.9], None),
        ([(20, 10, 40, 40), (70, 10, 35, 35)], [8, 8], None),
        ([(20, 10, 40, 40), (80, 10, 10, 10)], [8, 8], FaceBox(0.1, 0.05, 0.2, 0.2)),
    ],
)
def test_detector_requires_confidence_and_dominant_face(
    tmp_path: Path,
    monkeypatch: Any,
    boxes: list[tuple[int, int, int, int]],
    weights: list[float],
    expected: FaceBox | None,
) -> None:
    class Cascade:
        def empty(self) -> bool:
            return False

        def detectMultiScale3(self, *args: Any, **kwargs: Any) -> tuple[Any, Any, Any]:
            return np.array(boxes), None, np.array(weights)

    monkeypatch.setattr("clipfactory.infrastructure.media.portraits.cv2.CascadeClassifier", lambda _: Cascade())
    path = tmp_path / "portrait.png"
    Image.new("RGB", (200, 200)).save(path)
    assert detect_portrait_face(path) == expected


@pytest.mark.req("CF-REQ-255")
def test_installed_local_cascade_returns_no_face_for_blank_image(tmp_path: Path) -> None:
    path = tmp_path / "blank.png"
    Image.new("RGB", (720, 1280)).save(path)
    assert detect_portrait_face(path) is None
