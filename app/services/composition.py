"""Rendering coordination for prepared b-roll, placeholders, and narration audio."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.core.exceptions import FFmpegError
from app.models.broll import BRollClip, BRollKind, VideoSourceContext
from app.services.crop import SmartCropper
from app.services.ffmpeg import FFmpegService
from app.services.tts import NarrationAudio

logger = logging.getLogger(__name__)


class ReelCompositionService:
    """Renders each selected visual, then composes a narration-driven vertical reel."""

    def __init__(
        self,
        ffmpeg: FFmpegService,
        cropper: SmartCropper,
        placeholder_color: str = "#23716e",
    ) -> None:
        self.ffmpeg = ffmpeg
        self.cropper = cropper
        self.placeholder_color = placeholder_color

    def compose(
        self,
        narration: NarrationAudio,
        timeline: Sequence[BRollClip],
        video_sources: Sequence[VideoSourceContext],
        workspace: Path,
        destination: Path,
    ) -> None:
        if not timeline:
            raise FFmpegError("A reel requires a b-roll timeline")
        visual_directory = workspace / "reel-visuals"
        visual_directory.mkdir(parents=True, exist_ok=True)
        sources_by_id = {source.source_id: source for source in video_sources}
        visual_paths: list[Path] = []
        for index, broll in enumerate(timeline):
            destination_path = visual_directory / f"visual-{index:03d}.mp4"
            if broll.kind is BRollKind.VIDEO and self._render_video_visual(
                broll,
                sources_by_id,
                destination_path,
            ):
                visual_paths.append(destination_path)
                continue
            self.ffmpeg.render_placeholder(destination_path, broll.duration, self.placeholder_color)
            visual_paths.append(destination_path)
        self.ffmpeg.compose_reel(visual_paths, narration.path, destination)

    def _render_video_visual(
        self,
        broll: BRollClip,
        sources_by_id: Mapping[str, VideoSourceContext],
        destination: Path,
    ) -> bool:
        if broll.source_id is None or broll.source_start is None or broll.source_end is None:
            return False
        source = sources_by_id.get(broll.source_id)
        if source is None:
            return False
        try:
            framing = self.cropper.plan_framing(
                source.path,
                source.metadata,
                broll.source_start,
                broll.source_end,
            )
            self.ffmpeg.render_vertical(
                source.path,
                destination,
                broll.source_start,
                broll.source_end,
                framing.fallback_crop,
                framing.camera_path,
            )
        except FFmpegError as error:
            logger.warning(
                "B-roll source %s could not render; using a placeholder: %s",
                source.source_id,
                error,
            )
            return False
        return True