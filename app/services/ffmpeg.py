"""Safe FFmpeg and FFprobe integration for video inspection and rendering."""

import json
import logging
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import FFmpegError
from app.models.media import VideoMetadata
from app.services.framing import CameraPath, CropBox

logger = logging.getLogger(__name__)
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_OVERLAY_FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/lato/Lato-Heavy.ttf"),
)


@dataclass(frozen=True, slots=True)
class SourceAudioScene:
    """A source-video audio interval aligned to one rendered scene."""

    duration: float
    source_path: Path | None = None
    source_start: float | None = None
    source_end: float | None = None

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("Source audio scene duration must be positive")
        if self.source_path is None:
            if self.source_start is not None or self.source_end is not None:
                raise ValueError("Silent source audio scenes cannot include a source interval")
            return
        if self.source_start is None or self.source_end is None:
            raise ValueError("Source audio scenes require a source interval")
        if self.source_end <= self.source_start:
            raise ValueError("Source audio scene end must be after start")


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

    def probe_image(self, source_path: Path) -> tuple[int, int]:
        """Read still-image dimensions without treating an image as a timed video stream."""
        self.require_available()
        result = self._run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height",
                "-of",
                "json",
                str(source_path),
            ]
        )
        try:
            payload = json.loads(result.stdout)
            stream = next(item for item in payload["streams"] if item.get("codec_type") == "video")
            return int(stream["width"]), int(stream["height"])
        except (KeyError, TypeError, ValueError, StopIteration) as error:
            raise FFmpegError("Could not read usable image metadata") from error

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

    def probe_audio_duration(self, source_path: Path) -> float:
        """Measure a usable audio stream without assuming a video stream exists."""
        self.require_available()
        result = self._run(
            [
                self.ffprobe_binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(source_path),
            ]
        )
        try:
            payload = json.loads(result.stdout)
            has_audio = any(
                stream.get("codec_type") == "audio" for stream in payload.get("streams", [])
            )
            duration = float(payload["format"]["duration"])
            if not has_audio or duration <= 0:
                raise ValueError("missing usable audio stream")
            return duration
        except (KeyError, TypeError, ValueError) as error:
            raise FFmpegError("Could not read usable audio metadata") from error

    def normalize_audio(
        self,
        source_path: Path,
        destination: Path,
        sample_rate: int,
        speed: float = 1.0,
    ) -> None:
        """Normalize provider output to mono PCM WAV and apply a modest requested speed."""
        if sample_rate < 8_000 or sample_rate > 48_000:
            raise FFmpegError("Narration sample rate must be between 8000 and 48000 Hz")
        if not 0.75 <= speed <= 1.25:
            raise FFmpegError("Narration speed must be between 0.75 and 1.25")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        filters = [f"aresample={sample_rate}", "aformat=channel_layouts=mono"]
        if speed != 1:
            filters.append(f"atempo={speed:.6f}")
        self._run(
            [
                self.ffmpeg_binary,
                "-v",
                "error",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-af",
                ",".join(filters),
                "-c:a",
                "pcm_s16le",
                "-y",
                str(destination),
            ]
        )

    def assemble_narration_audio(
        self,
        audio_paths: list[Path],
        pauses_after: list[float],
        destination: Path,
        sample_rate: int,
    ) -> None:
        """Concatenate normalized narration units with deterministic inter-segment silence."""
        if not audio_paths:
            raise FFmpegError("Narration requires at least one audio segment")
        if len(audio_paths) != len(pauses_after):
            raise FFmpegError("Narration audio segments and pauses must have matching lengths")
        if sample_rate < 8_000 or sample_rate > 48_000:
            raise FFmpegError("Narration sample rate must be between 8000 and 48000 Hz")
        if any(pause < 0 or pause > 5 for pause in pauses_after):
            raise FFmpegError("Narration pauses must be between zero and five seconds")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        input_arguments = [argument for path in audio_paths for argument in ("-i", str(path))]
        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, pause_after in enumerate(pauses_after):
            filters.append(
                f"[{index}:a]aresample={sample_rate},aformat=channel_layouts=mono,"
                f"asetpts=PTS-STARTPTS[audio{index}]"
            )
            concat_inputs.append(f"[audio{index}]")
            if pause_after:
                filters.append(
                    f"anullsrc=r={sample_rate}:cl=mono,atrim=duration={pause_after:.6f},"
                    f"asetpts=N/SR/TB[pause{index}]"
                )
                concat_inputs.append(f"[pause{index}]")
        filters.append(
            f"{''.join(concat_inputs)}concat=n={len(concat_inputs)}:v=0:a=1[narration]"
        )
        self._run(
            [
                self.ffmpeg_binary,
                "-v",
                "error",
                *input_arguments,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[narration]",
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

    def write_overlay_text(self, text: str, destination: Path) -> int:
        """Write wrapped narration text for drawtext without interpolating it into a filter."""
        normalized = " ".join(text.split())
        if not normalized:
            raise FFmpegError("Narration overlay text cannot be empty")
        lines = textwrap.wrap(
            normalized,
            width=max(16, self.output_width // 45),
            break_long_words=True,
            break_on_hyphens=False,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(lines), encoding="utf-8")
        for index, line in enumerate(lines, start=1):
            self._overlay_line_path(destination, index).write_text(line, encoding="utf-8")
        return max(32, min(64, int(64 * min(1, 5 / len(lines)))))

    def render_vertical_with_overlay(
        self,
        source_path: Path,
        destination: Path,
        start: float,
        end: float,
        crop: CropBox,
        overlay_text_path: Path,
        overlay_font_size: int,
        camera_path: CameraPath | None = None,
        output_duration: float | None = None,
    ) -> None:
        """Render a cropped video interval with readable narration text and no TTS audio."""
        if end <= start:
            raise FFmpegError("Clip end must be later than clip start")
        if output_duration is not None and output_duration <= 0:
            raise FFmpegError("Scene output duration must be positive")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._run(
                self.build_vertical_overlay_command(
                    source_path,
                    destination,
                    start,
                    end,
                    crop,
                    overlay_text_path,
                    overlay_font_size,
                    camera_path,
                    output_duration,
                )
            )
        except FFmpegError:
            if not self._uses_dynamic_camera_path(crop, camera_path):
                raise
            logger.warning("Dynamic reel framing render failed; retrying with static crop")
            self._run(
                self.build_vertical_overlay_command(
                    source_path,
                    destination,
                    start,
                    end,
                    crop,
                    overlay_text_path,
                    overlay_font_size,
                    output_duration=output_duration,
                )
            )

    def render_image_with_overlay(
        self,
        source_path: Path,
        destination: Path,
        duration: float,
        overlay_text_path: Path,
        overlay_font_size: int,
    ) -> None:
        """Render a still image into a vertical scene with source-safe narration text."""
        if duration <= 0:
            raise FFmpegError("Image scene duration must be positive")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            self.build_image_overlay_command(
                source_path,
                destination,
                duration,
                overlay_text_path,
                overlay_font_size,
            )
        )

    def render_text_card(
        self,
        destination: Path,
        duration: float,
        overlay_text_path: Path,
        overlay_font_size: int,
        color: str = "#23716e",
    ) -> None:
        """Render a non-black readable fallback scene when no source visual can be used."""
        if duration <= 0:
            raise FFmpegError("Text card duration must be positive")
        if not _HEX_COLOR.fullmatch(color):
            raise FFmpegError("Text card color must be a six-digit hex color")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            self.build_text_card_command(
                destination,
                duration,
                overlay_text_path,
                overlay_font_size,
                color,
            )
        )

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

    def compose_clip(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
    ) -> None:
        """Concatenate prepared vertical visuals and attach the local narration track."""
        if not visual_paths:
            raise FFmpegError("A clip requires at least one visual segment")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(self.build_clip_composition_command(visual_paths, narration_path, destination))

    def compose_silent_scenes(self, visual_paths: list[Path], destination: Path) -> None:
        """Concatenate prepared reel scenes into one silent H.264 MP4."""
        if not visual_paths:
            raise FFmpegError("A reel requires at least one visual scene")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(self.build_silent_composition_command(visual_paths, destination))

    def compose_narrated_scenes(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
        narration_volume: float,
        audio_sample_rate: int,
        source_audio_scenes: list[SourceAudioScene] | None = None,
        source_audio_volume: float = 0.12,
        ducking_enabled: bool = True,
    ) -> None:
        """Concatenate rendered scenes and mix measured narration with optional source audio."""
        if not visual_paths:
            raise FFmpegError("A reel requires at least one visual scene")
        if not narration_path.is_file():
            raise FFmpegError("Narration audio file is unavailable")
        self.require_available()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            self.build_narrated_scene_composition_command(
                visual_paths,
                narration_path,
                destination,
                narration_volume,
                audio_sample_rate,
                source_audio_scenes,
                source_audio_volume,
                ducking_enabled,
            )
        )

    def build_clip_composition_command(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
    ) -> list[str]:
        input_arguments = [argument for path in visual_paths for argument in ("-i", str(path))]
        input_arguments.extend(("-i", str(narration_path)))
        prepared = [
            f"[{index}:v]setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.25[v{index}]"
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

    def build_narrated_scene_composition_command(
        self,
        visual_paths: list[Path],
        narration_path: Path,
        destination: Path,
        narration_volume: float,
        audio_sample_rate: int,
        source_audio_scenes: list[SourceAudioScene] | None = None,
        source_audio_volume: float = 0.12,
        ducking_enabled: bool = True,
    ) -> list[str]:
        """Build a deterministic final reel command without accepting generated filter text."""
        if not visual_paths:
            raise FFmpegError("A reel requires at least one visual scene")
        if not 0 < narration_volume <= 2:
            raise FFmpegError("Narration volume must be greater than zero and no more than two")
        if not 0 <= source_audio_volume <= 1:
            raise FFmpegError("Source audio volume must be between zero and one")
        if audio_sample_rate < 8_000 or audio_sample_rate > 48_000:
            raise FFmpegError("Narration sample rate must be between 8000 and 48000 Hz")
        audio_scenes = source_audio_scenes or []
        if audio_scenes and len(audio_scenes) != len(visual_paths):
            raise FFmpegError("Source audio scenes must align with rendered visual scenes")

        input_arguments = [argument for path in visual_paths for argument in ("-i", str(path))]
        narration_index = len(visual_paths)
        input_arguments.extend(("-i", str(narration_path)))
        source_input_indexes: dict[int, int] = {}
        for scene_index, scene in enumerate(audio_scenes):
            if scene.source_path is None:
                continue
            source_input_indexes[scene_index] = narration_index + 1 + len(source_input_indexes)
            input_arguments.extend(("-i", str(scene.source_path)))

        visual_filters = [
            f"[{index}:v]setpts=PTS-STARTPTS[video{index}]"
            for index in range(len(visual_paths))
        ]
        visual_inputs = "".join(f"[video{index}]" for index in range(len(visual_paths)))
        filters = [
            *visual_filters,
            f"{visual_inputs}concat=n={len(visual_paths)}:v=1:a=0[video]",
            f"[{narration_index}:a]aresample={audio_sample_rate},"
            f"aformat=channel_layouts=mono,asetpts=PTS-STARTPTS,"
            f"volume={narration_volume:.6f}[narration]",
        ]
        if audio_scenes:
            narration_mix_label = "narration"
            if ducking_enabled:
                filters.append("[narration]asplit=2[narrationduck][narrationmix]")
                narration_mix_label = "narrationmix"
            source_labels: list[str] = []
            for scene_index, scene in enumerate(audio_scenes):
                label = f"sourceaudio{scene_index}"
                source_labels.append(f"[{label}]")
                source_input_index = source_input_indexes.get(scene_index)
                if source_input_index is None:
                    filters.append(
                        f"anullsrc=r={audio_sample_rate}:cl=mono,"
                        f"atrim=duration={scene.duration:.6f},asetpts=N/SR/TB[{label}]"
                    )
                    continue
                assert scene.source_start is not None
                assert scene.source_end is not None
                filters.append(
                    f"[{source_input_index}:a]atrim=start={scene.source_start:.6f}:"
                    f"end={scene.source_end:.6f},asetpts=PTS-STARTPTS,"
                    f"aresample={audio_sample_rate},aformat=channel_layouts=mono,"
                    f"volume={source_audio_volume:.6f},apad,"
                    f"atrim=duration={scene.duration:.6f}[{label}]"
                )
            filters.append(
                f"{''.join(source_labels)}concat=n={len(audio_scenes)}:v=0:a=1[sourceaudio]"
            )
            source_label = "sourceaudio"
            if ducking_enabled:
                filters.append(
                    "[sourceaudio][narrationduck]sidechaincompress=threshold=0.02:ratio=8:"
                    "attack=50:release=400[duckedsource]"
                )
                source_label = "duckedsource"
            filters.append(
                f"[{source_label}][{narration_mix_label}]amix=inputs=2:duration=longest:"
                "normalize=0[audio]"
            )
        else:
            filters.append("[narration]anull[audio]")

        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            *input_arguments,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[video]",
            "-map",
            "[audio]",
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

    def build_vertical_overlay_command(
        self,
        source_path: Path,
        destination: Path,
        start: float,
        end: float,
        crop: CropBox,
        overlay_text_path: Path,
        overlay_font_size: int,
        camera_path: CameraPath | None = None,
        output_duration: float | None = None,
    ) -> list[str]:
        source_duration = end - start
        duration = output_duration if output_duration is not None else source_duration
        if duration <= 0:
            raise FFmpegError("Scene output duration must be positive")
        rendered_duration = min(source_duration, duration)
        video_filter = self._overlay_filter(
            self._duration_adjusted_video_filter(
                self._build_video_filter(crop, camera_path),
                source_duration,
                duration,
            ),
            overlay_text_path,
            overlay_font_size,
        )
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{rendered_duration:.3f}",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-vf",
            video_filter,
            "-an",
            *self._video_output_arguments(destination),
        ]

    def build_image_overlay_command(
        self,
        source_path: Path,
        destination: Path,
        duration: float,
        overlay_text_path: Path,
        overlay_font_size: int,
    ) -> list[str]:
        image_filter = (
            f"scale={self.output_width}:{self.output_height}:force_original_aspect_ratio=decrease,"
            f"pad={self.output_width}:{self.output_height}:(ow-iw)/2:(oh-ih):color=0x14211e,"
            "setsar=1"
        )
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(source_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            self._overlay_filter(image_filter, overlay_text_path, overlay_font_size),
            "-an",
            *self._video_output_arguments(destination),
        ]

    def build_text_card_command(
        self,
        destination: Path,
        duration: float,
        overlay_text_path: Path,
        overlay_font_size: int,
        color: str = "#23716e",
    ) -> list[str]:
        color_value = f"0x{color.removeprefix('#')}"
        return [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color_value}:s={self.output_width}x{self.output_height}:r=30:d={duration:.3f}",
            "-vf",
            self._overlay_filter("setsar=1", overlay_text_path, overlay_font_size),
            "-an",
            *self._video_output_arguments(destination),
        ]

    def build_silent_composition_command(
        self,
        visual_paths: list[Path],
        destination: Path,
    ) -> list[str]:
        input_arguments = [argument for path in visual_paths for argument in ("-i", str(path))]
        prepared = [
            f"[{index}:v]setpts=PTS-STARTPTS[v{index}]" for index in range(len(visual_paths))
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
            "-an",
            *self._video_output_arguments(destination),
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

    def _duration_adjusted_video_filter(
        self,
        video_filter: str,
        source_duration: float,
        output_duration: float,
    ) -> str:
        if output_duration <= source_duration:
            return video_filter
        return (
            f"{video_filter},tpad=stop_mode=clone:"
            f"stop_duration={output_duration - source_duration:.3f}"
        )

    def _overlay_filter(
        self,
        base_filter: str,
        overlay_text_path: Path,
        overlay_font_size: int,
    ) -> str:
        if overlay_font_size < 20 or overlay_font_size > 96:
            raise FFmpegError("Narration overlay font size must be between 20 and 96")
        if not overlay_text_path.is_file():
            raise FFmpegError("Narration overlay text file is unavailable")
        lines = overlay_text_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise FFmpegError("Narration overlay text file is empty")
        font_path = next((path for path in _OVERLAY_FONT_CANDIDATES if path.is_file()), None)
        font_option = ""
        if font_path is not None:
            font_option = f"fontfile='{self._escape_filter_path(font_path)}':"
        text_height = len(lines) * overlay_font_size + (len(lines) - 1) * 10
        panel_width = self.output_width - 128
        panel_height = text_height + 48
        panel = (
            f"drawbox=x=(iw-{panel_width})/2:y=ih-{panel_height}-126:"
            f"w={panel_width}:h={panel_height}:color=black@0.72:t=fill"
        )
        drawtexts: list[str] = []
        for index in range(len(lines)):
            line_path = self._overlay_line_path(overlay_text_path, index + 1)
            if not line_path.is_file():
                raise FFmpegError("Narration overlay line file is unavailable")
            text_path = self._escape_filter_path(line_path.resolve())
            y_offset = index * (overlay_font_size + 10)
            drawtexts.append(
                f"drawtext={font_option}textfile='{text_path}':expansion=none:"
                f"fontcolor=white:fontsize={overlay_font_size}:"
                f"x=(w-text_w)/2:y=h-{text_height}-150+{y_offset}:fix_bounds=1"
            )
        return ",".join((base_filter, panel, *drawtexts, "format=yuv420p"))

    def _overlay_line_path(self, overlay_text_path: Path, index: int) -> Path:
        return overlay_text_path.with_name(
            f"{overlay_text_path.stem}-line-{index:02d}{overlay_text_path.suffix}"
        )

    def _video_output_arguments(self, destination: Path) -> list[str]:
        return [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(destination),
        ]

    def _escape_filter_path(self, path: Path) -> str:
        return str(path).replace("\\", r"\\").replace("'", r"\'").replace(":", r"\:")

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
            expression += f"+({change})*clip((t-{current.timestamp:.3f})/{duration:.3f},0,1)"
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
