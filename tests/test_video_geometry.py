from pathlib import Path
from subprocess import CompletedProcess

from app.core.exceptions import FFmpegError
from app.services.crop import CropBox
from app.services.ffmpeg import FFmpegService, VideoMetadata
from app.services.framing import CameraKeyframe, CameraPath


def test_center_crop_for_landscape_video_is_vertical_and_even() -> None:
    crop = CropBox.centered(VideoMetadata(duration=60, width=1920, height=1080, has_audio=True))

    assert crop.width * 16 == crop.height * 9
    assert crop.x == 662
    assert crop.y == 12
    assert crop.width % 2 == crop.height % 2 == 0


def test_face_targeted_crop_is_clamped_to_source_bounds() -> None:
    metadata = VideoMetadata(duration=60, width=1920, height=1080, has_audio=True)
    crop = CropBox.centered(metadata).around_point(1900, 540, metadata)

    assert crop.x + crop.width <= metadata.width
    assert crop.y + crop.height <= metadata.height


def test_render_command_has_fixed_codecs_and_no_shell_interpolation() -> None:
    crop = CropBox(x=100, y=0, width=606, height=1080)
    command = FFmpegService().build_render_command(
        Path("source video.mp4"),
        Path("output clip.mp4"),
        12.4,
        42.9,
        crop,
    )

    assert command[0] == "ffmpeg"
    assert "libx264" in command
    assert "aac" in command
    assert any("crop=606:1080:100:0" in argument for argument in command)
    assert "source video.mp4" in command


def test_render_command_uses_a_compact_time_based_crop_for_dynamic_camera_paths() -> None:
    crop = CropBox(x=100, y=0, width=606, height=1080)
    camera_path = CameraPath(
        width=606,
        height=1080,
        keyframes=(
            CameraKeyframe(timestamp=0, x=100, y=0),
            CameraKeyframe(timestamp=1, x=300, y=0),
            CameraKeyframe(timestamp=2, x=500, y=0),
        ),
    )
    command = FFmpegService().build_render_command(
        Path("source.mp4"),
        Path("output.mp4"),
        12.4,
        42.9,
        crop,
        camera_path,
    )
    video_filter = command[command.index("-vf") + 1]

    assert video_filter.startswith("setpts=PTS-STARTPTS,crop=606:1080:")
    assert "(200)*clip((t-0.000)/1.000\\,0\\,1)" in video_filter
    assert "if(" not in video_filter
    assert "scale=1080:1920:flags=lanczos,setsar=1" in video_filter


def test_dynamic_camera_expression_starts_at_the_first_keyframe() -> None:
    path = CameraPath(
        width=606,
        height=1080,
        keyframes=(
            CameraKeyframe(timestamp=0, x=100, y=0),
            CameraKeyframe(timestamp=1, x=300, y=0),
            CameraKeyframe(timestamp=2, x=500, y=0),
        ),
    )

    expression = FFmpegService()._coordinate_expression(path, "x")
    expected_expression = (
        "100+(200)*clip((t-0.000)/1.000\\,0\\,1)"
        "+(200)*clip((t-1.000)/1.000\\,0\\,1)"
    )

    assert expression == expected_expression


def test_render_command_uses_flat_expressions_for_maximum_dynamic_path_length() -> None:
    crop = CropBox(x=0, y=0, width=606, height=1080)
    camera_path = CameraPath(
        width=606,
        height=1080,
        keyframes=tuple(
            CameraKeyframe(
                timestamp=index * 0.5,
                x=(index * 22) % 1_314,
                y=(index * 6) % 12,
            )
            for index in range(121)
        ),
    )
    command = FFmpegService().build_render_command(
        Path("source.mp4"),
        Path("output.mp4"),
        0,
        61,
        crop,
        camera_path,
    )
    video_filter = command[command.index("-vf") + 1]

    assert "if(" not in video_filter
    assert video_filter.count("clip(") > 100
    assert len(video_filter) < 12_000


def test_dynamic_render_failure_retries_with_static_crop(monkeypatch) -> None:
    service = FFmpegService()
    crop = CropBox(x=100, y=0, width=606, height=1080)
    camera_path = CameraPath(
        width=606,
        height=1080,
        keyframes=(CameraKeyframe(0, 100, 0), CameraKeyframe(1, 300, 0)),
    )
    commands: list[list[str]] = []

    monkeypatch.setattr(service, "require_available", lambda: None)

    def fake_run(command: list[str]) -> CompletedProcess[str]:
        commands.append(command)
        if len(commands) == 1:
            raise FFmpegError("dynamic filter unsupported")
        return CompletedProcess(command, 0)

    monkeypatch.setattr(service, "_run", fake_run)

    service.render_vertical(Path("source.mp4"), Path("output.mp4"), 0, 1, crop, camera_path)

    assert len(commands) == 2
    assert "setpts=PTS-STARTPTS" in commands[0][commands[0].index("-vf") + 1]
    assert "setpts=PTS-STARTPTS" not in commands[1][commands[1].index("-vf") + 1]


def test_render_command_uses_configured_vertical_output_dimensions() -> None:
    command = FFmpegService(output_width=720, output_height=1280).build_render_command(
        Path("source.mp4"),
        Path("output.mp4"),
        0,
        30,
        CropBox(x=100, y=0, width=606, height=1080),
    )

    assert "scale=720:1280:flags=lanczos,setsar=1" in command[command.index("-vf") + 1]
