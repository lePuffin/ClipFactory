"""Safe FFmpeg and FFprobe integration for video inspection and rendering."""

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

from app.core.exceptions import FFmpegError
from app.models.media import VideoMetadata
from app.services.framing import CameraPath, CropBox

logger = logging.getLogger(__name__)
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class FFmpegService:
    """Constructs all media commands from trusted application values and arguments."""

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        output_width: int = 1080,
        output_height: int = 1920,
    ) -> None:
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.output_width = output_width
        self.output_height = output_height

    @property
    def is_available(self) -> bool:
        return (
            shutil.which(self.ffmpeg_binary) is not None
            and shutil.which(self.ffprobe_binary) is not None
        )

    def require_available(self) -> None:
        if not self.is_available:
            raise FFmpegError(
                "FFmpeg and FFprobe are required. Install FFmpeg and ensure both commands are on "
                "PATH."
            )

    def probe(self, source_path: Path) -> VideoMetadata:
        self.require_available()
        result = self._run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(source_path),
            ]
        )
        try:
            payload = json.loads(result.stdout)
            video_stream = next(
                stream for stream in payload["streams"] if stream.get("codec_type") == "video"
            )
            return VideoMetadata(
                duration=float(payload["format"]["duration"]),
                width=int(video_stream["width"]),
                height=int(video_stream["height"]),
                has_audio=any(
                    stream.get("codec_type") == "audio" for stream in payload.get("streams", [])
                ),
            )
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            raise FFmpegError("Could not read usable video metadata") from error

    def validate_decodable(self, source_path: Path) -> None:
        self.require_available()
        self._run(
            [
                self.ffmpeg_binary,
                "-v",
                "error",
                "-t",
                "3",
                "-i",
                str(source_path),
                "-map",
                "0:v:0?",
                "-f",
                "null",
                "-",
            ]
        )

    def extract_audio(self, source_path: Path, destination: Path) -> None:
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg_binary,
                "-v",
                "error",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(destination),
            ]
        )

    def render_vertical(
        self,
        source_path: Path,
        destination: Path,
        start: float,
        end: float,
        crop: CropBox,
        camera_path: CameraPath | None = None,
    ) -> None:
        if end <= start:
            raise FFmpegError("Clip end must be later than clip start")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._run(
                self.build_render_command(source_path, destination, start, end, crop, camera_path)
            )
        except FFmpegError:
            if not self._uses_dynamic_camera_path(crop, camera_path):
                raise
            logger.warning("Dynamic framing render failed; retrying with static crop")
            self._run(self.build_render_command(source_path, destination, start, end, crop))

    def render_placeholder(self, destination: Path, duration: float, color: str) -> None:
        """Render a fixed-label vertical visual without accepting untrusted filter text."""
        if duration <= 0:
            raise FFmpegError("Placeholder duration must be positive")
        if not _HEX_COLOR.fullmatch(color):
            raise FFmpegError("Placeholder color must be a six-digit hex color")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(self.build_placeholder_command(destination, duration, color))

    def build_placeholder_command(
        self,
        destination: Path,
        duration: float,
        color: str,
    ) -> list[str]:
        color_value = f"0x{color.removeprefix('#')}"
        source_filter = (
            f"color=c={color_value}:s={self.output_width}x{self.output_height}:"
            f"r=30:d={duration:.3f},"
            "drawtext=fontcolor=white:fontsize=52:text=NEWS BRIEF:"
            "x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p"
        )
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source_filter,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(destination),
        ]

    def compose_reel(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
    ) -> None:
        """Concatenate prepared vertical visuals and attach the local narration track."""
        if not visual_paths:
            raise FFmpegError("A reel requires at least one visual segment")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(self.build_reel_composition_command(visual_paths, narration_path, destination))

    def build_reel_composition_command(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
    ) -> list[str]:
        input_arguments = [argument for path in visual_paths for argument in ("-i", str(path))]
        input_arguments.extend(("-i", str(narration_path)))
        prepared = [
            f"[{index}:v]setpts=PTS-STARTPTS,"
            "tpad=stop_mode=clone:stop_duration=0.25"
            f"[v{index}]"
            for index in range(len(visual_paths))
        ]
        concat_inputs = "".join(f"[v{index}]" for index in range(len(visual_paths)))
        filter_graph = ";".join(
            [*prepared, f"{concat_inputs}concat=n={len(visual_paths)}:v=1:a=0[video]"]
        )
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            *input_arguments,
            "-filter_complex",
            filter_graph,
            "-map",
            "[video]",
            "-map",
            f"{len(visual_paths)}:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            "-y",
            str(destination),
        ]

    def build_render_command(
        self,
        source_path: Path,
        destination: Path,
        start: float,
        end: float,
        crop: CropBox,
        camera_path: CameraPath | None = None,
    ) -> list[str]:
        duration = end - start
        video_filter = self._build_video_filter(crop, camera_path)
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(source_path),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            str(destination),
        ]

    def _build_video_filter(self, crop: CropBox, camera_path: CameraPath | None) -> str:
        if not self._uses_dynamic_camera_path(crop, camera_path):
            return self._scale_filter(crop.filter_expression)

        assert camera_path is not None
        compact_path = camera_path.compact()
        x_expression = self._coordinate_expression(compact_path, "x")
        y_expression = self._coordinate_expression(compact_path, "y")
        dynamic_crop = f"crop={crop.width}:{crop.height}:{x_expression}:{y_expression}"
        return f"setpts=PTS-STARTPTS,{self._scale_filter(dynamic_crop)}"

    def _uses_dynamic_camera_path(self, crop: CropBox, camera_path: CameraPath | None) -> bool:
        return (
            camera_path is not None
            and camera_path.is_dynamic
            and camera_path.width == crop.width
            and camera_path.height == crop.height
        )

    def _scale_filter(self, crop_filter: str) -> str:
        return (
            f"{crop_filter},scale={self.output_width}:{self.output_height}:flags=lanczos,setsar=1"
        )

    def _coordinate_expression(self, camera_path: CameraPath, coordinate: str) -> str:
        keyframes = camera_path.keyframes
        expression = str(getattr(keyframes[0], coordinate))
        segments = zip(keyframes[:-1], keyframes[1:], strict=True)
        for current, following in segments:
            start_value = getattr(current, coordinate)
            end_value = getattr(following, coordinate)
            duration = following.timestamp - current.timestamp
            change = end_value - start_value
            if duration <= 0 or change == 0:
                continue
            expression += (
                f"+({change})*clip((t-{current.timestamp:.3f})/{duration:.3f},0,1)"
            )
        return expression.replace(",", r"\,")

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                arguments,
                check=False,
                capture_output=True,
                text=True,
                timeout=60 * 60,
            )
        except FileNotFoundError as error:
            raise FFmpegError("FFmpeg executable was not found") from error
        except subprocess.TimeoutExpired as error:
            raise FFmpegError("FFmpeg operation timed out") from error

        if result.returncode != 0:
            details = (result.stderr or result.stdout).strip()[-2000:]
            raise FFmpegError(f"FFmpeg failed: {details or 'unknown error'}")
        return result
