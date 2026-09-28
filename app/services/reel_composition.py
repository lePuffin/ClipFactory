"""Render source-grounded reel scenes into a silent vertical rough reel."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.core.exceptions import FFmpegError
from app.models.broll import VideoSourceContext
from app.models.reel import NarrationMetadata, Scene, SceneVisualType
from app.services.crop import SmartCropper
from app.services.ffmpeg import FFmpegService, SourceAudioScene

logger = logging.getLogger(__name__)


class ReelCompositionService:
    """Prepares every scene before concatenation so unavailable media cannot create black gaps."""

    def __init__(self, ffmpeg: FFmpegService, cropper: SmartCropper) -> None:
        self.ffmpeg = ffmpeg
        self.cropper = cropper

    def compose(
        self,
        scenes: Sequence[Scene],
        video_sources: Mapping[str, VideoSourceContext],
        image_paths: Mapping[str, Path],
        workspace: Path,
        destination: Path,
        narration_path: Path | None = None,
        narration: NarrationMetadata | None = None,
    ) -> None:
        if not scenes:
            raise FFmpegError("A reel requires at least one scene")
        if (narration_path is None) != (narration is None):
            raise FFmpegError("Reel narration audio and metadata must be provided together")
        scene_directory = workspace / "reel-scenes"
        overlay_directory = workspace / "reel-overlays"
        scene_directory.mkdir(parents=True, exist_ok=True)
        visual_paths: list[Path] = []
        for index, scene in enumerate(scenes, start=1):
            visual_path = scene_directory / f"scene-{index:02d}.mp4"
            overlay_path = overlay_directory / f"scene-{index:02d}.txt"
            font_size = self.ffmpeg.write_overlay_text(scene.narration, overlay_path)
            if not self._render_scene(
                scene,
                visual_path,
                overlay_path,
                font_size,
                video_sources,
                image_paths,
            ):
                self.ffmpeg.render_text_card(visual_path, scene.duration, overlay_path, font_size)
            visual_paths.append(visual_path)
        if narration is None:
            self.ffmpeg.compose_silent_scenes(visual_paths, destination)
            return
        assert narration_path is not None
        source_audio_scenes = (
            self._source_audio_scenes(scenes, video_sources)
            if narration.source_audio_enabled
            else None
        )
        self.ffmpeg.compose_narrated_scenes(
            visual_paths,
            narration_path,
            destination,
            narration.narration_volume,
            narration.sample_rate,
            source_audio_scenes,
            narration.source_audio_volume,
            narration.ducking_enabled,
        )

    def _render_scene(
        self,
        scene: Scene,
        destination: Path,
        overlay_path: Path,
        font_size: int,
        video_sources: Mapping[str, VideoSourceContext],
        image_paths: Mapping[str, Path],
    ) -> bool:
        visual = scene.visual
        if visual.type is SceneVisualType.SOURCE_VIDEO:
            return self._render_video(
                scene,
                destination,
                overlay_path,
                font_size,
                video_sources,
            )
        if visual.type in {SceneVisualType.SOURCE_IMAGE, SceneVisualType.ARTICLE_IMAGE}:
            return self._render_image(scene, destination, overlay_path, font_size, image_paths)
        return False

    def _render_video(
        self,
        scene: Scene,
        destination: Path,
        overlay_path: Path,
        font_size: int,
        video_sources: Mapping[str, VideoSourceContext],
    ) -> bool:
        visual = scene.visual
        source = video_sources.get(visual.source_id or "")
        if source is None or visual.start is None or visual.end is None:
            return False
        try:
            framing = self.cropper.plan_framing(
                source.path,
                source.metadata,
                visual.start,
                visual.end,
            )
            self.ffmpeg.render_vertical_with_overlay(
                source.path,
                destination,
                visual.start,
                visual.end,
                framing.fallback_crop,
                overlay_path,
                font_size,
                framing.camera_path,
                output_duration=scene.duration,
            )
        except (FFmpegError, ValueError) as error:
            logger.warning("Could not render source video scene %s: %s", scene.id, error)
            return False
        return True

    def _source_audio_scenes(
        self,
        scenes: Sequence[Scene],
        video_sources: Mapping[str, VideoSourceContext],
    ) -> list[SourceAudioScene]:
        audio_scenes: list[SourceAudioScene] = []
        for scene in scenes:
            visual = scene.visual
            source = video_sources.get(visual.source_id or "")
            if (
                visual.type is SceneVisualType.SOURCE_VIDEO
                and source is not None
                and source.metadata.has_audio
                and visual.start is not None
                and visual.end is not None
            ):
                audio_scenes.append(
                    SourceAudioScene(scene.duration, source.path, visual.start, visual.end)
                )
            else:
                audio_scenes.append(SourceAudioScene(scene.duration))
        return audio_scenes

    def _render_image(
        self,
        scene: Scene,
        destination: Path,
        overlay_path: Path,
        font_size: int,
        image_paths: Mapping[str, Path],
    ) -> bool:
        asset_path = image_paths.get(scene.visual.asset_id or "")
        if asset_path is None or not asset_path.is_file():
            return False
        try:
            self.ffmpeg.render_image_with_overlay(
                asset_path,
                destination,
                scene.duration,
                overlay_path,
                font_size,
            )
        except FFmpegError as error:
            logger.warning("Could not render source image scene %s: %s", scene.id, error)
            return False
        return True