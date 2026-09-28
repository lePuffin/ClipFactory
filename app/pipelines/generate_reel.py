"""Explicit local pipeline for multi-source story understanding and rough-reel rendering."""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import FFmpegError, NoSuitableClipsError
from app.models.broll import VideoSourceContext
from app.models.job import JobRecord, JobStatus
from app.models.reel import (
    ContentSegment,
    ExtractedContent,
    ReelOutput,
    ReelPlan,
    Scene,
    SceneVisualType,
    SourceMaterial,
    SourceMetadata,
    VisualAsset,
    VisualAssetKind,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.article_ingestion import ArticleIngestionService
from app.services.editorial import EditorialEngine, EditorialOutcome
from app.services.ffmpeg import FFmpegService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.reel_composition import ReelCompositionService
from app.services.reel_narration import (
    NarrationSegmenter,
    NarrationService,
    assign_scene_starts,
    build_reel_narration_service,
    reconcile_scene_timing,
)
from app.services.reel_script_generation import ReelScriptGenerator
from app.services.reel_validation import (
    hydrate_reel_script,
    hydrate_source_analysis,
    hydrate_story_candidate,
)
from app.services.scene_planning import ScenePlanner, validate_scene_planning
from app.services.script_validation import validate_editorial_script
from app.services.source_analysis import SourceAnalyzer
from app.services.story_selection import StorySelector
from app.services.transcription import FasterWhisperTranscriber
from app.services.visual_selection import VisualSelector
from app.services.youtube import YoutubeDownloader

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _ReelSourceContext:
    """Runtime-only paths paired with the persisted normalized source material."""

    material: SourceMaterial
    video: VideoSourceContext | None = None
    image_paths: dict[str, Path] = field(default_factory=dict)
    vision_image_path: Path | None = None


class ReelGenerationPipeline:
    """Coordinates explicit multi-source stages into one silent, text-overlay rough reel."""

    def __init__(
        self,
        settings: Settings,
        files: FileManager,
        jobs: JobStore,
        ffmpeg: FFmpegService,
        article_ingestion: ArticleIngestionService,
        transcriber: FasterWhisperTranscriber,
        source_analyzer: SourceAnalyzer,
        story_selector: StorySelector,
        script_generator: ReelScriptGenerator,
        scene_planner: ScenePlanner,
        visual_selector: VisualSelector,
        composer: ReelCompositionService,
        youtube: YoutubeDownloader,
        editorial_engine: EditorialEngine | None = None,
        narration_factory: Callable[[Settings, FFmpegService, Path], NarrationService] = (
            build_reel_narration_service
        ),
    ) -> None:
        self.settings = settings
        self.files = files
        self.jobs = jobs
        self.ffmpeg = ffmpeg
        self.article_ingestion = article_ingestion
        self.transcriber = transcriber
        self.source_analyzer = source_analyzer
        self.story_selector = story_selector
        self.script_generator = script_generator
        self.scene_planner = scene_planner
        self.visual_selector = visual_selector
        self.composer = composer
        self.youtube = youtube
        self.editorial_engine = editorial_engine
        self.narration_factory = narration_factory

    def run(self, job_id: str) -> JobRecord:
        """Run one persisted reel job synchronously in the local worker thread."""
        completed = False
        try:
            job = self.jobs.get(job_id)
            if not job.is_reel():
                raise ValueError("The reel pipeline can only process reel jobs")
            reel_settings = self._settings_for_job(job)

            contexts = self._extract_sources(job)
            self._analyze_sources(job, contexts)
            self.files.write_reel_sources(
                job.id,
                [context.material.model_dump(mode="json") for context in contexts],
            )
            materials = [
                context.material for context in contexts if context.material.analysis is not None
            ]
            if not materials:
                raise NoSuitableClipsError(
                    "No submitted source could be analyzed into a meaningful story"
                )

            self._set_status(
                job.id,
                JobStatus.STORY_SELECTING,
                48,
                "Generating story candidates...",
            )
            stories = tuple(
                hydrate_story_candidate(story, materials)
                for story in self.story_selector.group(materials)
            )
            if not stories:
                raise NoSuitableClipsError("No coherent story candidates were available")
            editorial_outcome: EditorialOutcome | None = None
            if self.editorial_engine is None:
                story = hydrate_story_candidate(self.story_selector.select(stories), materials)
            else:
                self._set_status(
                    job.id,
                    JobStatus.STORY_SELECTING,
                    56,
                    "Evaluating stories and selecting an editorial angle...",
                )
                editorial_outcome = self.editorial_engine.develop(stories, materials)
                stories = editorial_outcome.story_candidates
                story = editorial_outcome.story
            self.files.write_reel_story_candidates(
                job.id,
                [candidate.model_dump(mode="json") for candidate in stories],
            )

            selected_materials = [
                material for material in materials if material.source.id in set(story.source_ids)
            ]
            self._set_status(
                job.id, JobStatus.SCRIPTING, 62, "Writing a grounded short-form script..."
            )
            if editorial_outcome is None:
                script = hydrate_reel_script(
                    self.script_generator.generate(
                        story,
                        selected_materials,
                        self.settings.reel_min_duration_seconds,
                        self.settings.reel_max_duration_seconds,
                    ),
                    story,
                    selected_materials,
                    self.settings.reel_min_duration_seconds,
                    self.settings.reel_max_duration_seconds,
                )
                editorial = None
            else:
                generated_script = self.script_generator.generate(
                    story,
                    selected_materials,
                    self.settings.reel_min_duration_seconds,
                    self.settings.reel_max_duration_seconds,
                    editorial_outcome.angle,
                    editorial_outcome.hook,
                )
                validated_script = validate_editorial_script(
                    generated_script,
                    story,
                    editorial_outcome.angle,
                    editorial_outcome.hook,
                    selected_materials,
                    self.settings.reel_min_duration_seconds,
                    self.settings.reel_max_duration_seconds,
                    self.settings.reel_words_per_minute,
                )
                script = validated_script.script
                editorial = editorial_outcome.decision.model_copy(
                    update={"script_validation": validated_script.report}
                )
                self.files.write_reel_editorial(job.id, editorial.model_dump(mode="json"))
            self.files.write_reel_script(job.id, script.model_dump(mode="json"))

            self._set_status(
                job.id, JobStatus.PLANNING, 74, "Planning source visuals for the narration..."
            )
            planning = validate_scene_planning(
                self.scene_planner.plan(story, script, selected_materials),
                script,
                story,
                selected_materials,
            )
            scenes = self.visual_selector.select(script, planning, selected_materials)
            narration = None
            narration_path = None
            if reel_settings.tts_enabled:
                self._set_status(
                    job.id,
                    JobStatus.SYNTHESIZING,
                    82,
                    "Generating and measuring AI narration...",
                )
                narration_path = self.files.clip_narration_path(job.id)
                narration_service = self.narration_factory(
                    reel_settings,
                    self.ffmpeg,
                    self.files.tts_cache_dir(),
                )
                narration = narration_service.synthesize(
                    NarrationSegmenter(reel_settings).segment(scenes),
                    self.files.workspace_dir(job.id),
                    narration_path,
                )
                scenes = reconcile_scene_timing(scenes, narration)
                self.files.write_reel_narration(job.id, narration.model_dump(mode="json"))
            else:
                scenes = assign_scene_starts(scenes)
            self.files.write_reel_scenes(
                job.id,
                [scene.model_dump(mode="json") for scene in scenes],
            )

            self._set_status(
                job.id, JobStatus.RENDERING, 88, "Rendering the vertical rough reel..."
            )
            destination = self.files.reel_path(job.id)
            composition_arguments = (
                scenes,
                self._video_sources(contexts, story.source_ids),
                self._image_paths_for_scenes(job.id, scenes, contexts),
                self.files.workspace_dir(job.id),
                destination,
            )
            if narration is None:
                self.composer.compose(*composition_arguments)
            else:
                assert narration_path is not None
                self.composer.compose(*composition_arguments, narration_path, narration)
            metadata = self.ffmpeg.probe(destination)
            self._validate_output(
                metadata.width,
                metadata.height,
                metadata.has_audio,
                metadata.duration,
                narration,
            )
            if narration_path is not None:
                self.files.persist_reel_narration(job.id, narration_path)
            plan = ReelPlan(
                story=story,
                story_candidates=list(stories),
                sources=[context.material for context in contexts],
                script=script,
                scenes=list(scenes),
                editorial=editorial,
                narration=narration,
            )
            self.files.write_reel_plan(job.id, plan.model_dump(mode="json"))

            completed = True
            return self.jobs.update(
                job.id,
                status=JobStatus.COMPLETED,
                progress=100,
                current_step="Complete",
                completed_at=datetime.now(UTC),
                reel=ReelOutput(
                    filename="story_01.mp4",
                    title=story.title,
                    duration=metadata.duration,
                    story_id=story.id,
                    source_count=len(story.source_ids),
                    has_audio=metadata.has_audio,
                    narration_duration=narration.duration if narration is not None else None,
                ),
            )
        except Exception as error:
            logger.exception("Reel generation for job %s failed", job_id)
            return self.jobs.update(
                job_id,
                status=JobStatus.FAILED,
                current_step="Failed",
                error=str(error)[:2_000],
            )
        finally:
            if completed:
                self.files.cleanup_successful_job(job_id)

    def _extract_sources(self, job: JobRecord) -> list[_ReelSourceContext]:
        self._set_status(job.id, JobStatus.INGESTING, 5, "Reading submitted sources...")
        contexts: list[_ReelSourceContext] = []
        total = len(job.sources)
        for index, source in enumerate(job.sources, start=1):
            try:
                if source.type is ClipSourceType.ARTICLE:
                    self._set_status(
                        job.id,
                        JobStatus.EXTRACTING,
                        7 + int(index / total * 18),
                        f"Extracting article {index} of {total}...",
                    )
                    contexts.append(self._extract_article(source))
                elif source.type is ClipSourceType.VIDEO:
                    contexts.append(self._extract_video(job.id, source, index, total))
                elif source.type is ClipSourceType.IMAGE:
                    self._set_status(
                        job.id,
                        JobStatus.EXTRACTING,
                        7 + int(index / total * 18),
                        f"Reading image {index} of {total}...",
                    )
                    contexts.append(self._extract_image(job.id, source))
                else:
                    raise ValueError("Unsupported reel source type")
            except Exception as error:
                logger.warning("Skipping unavailable source %s: %s", source.id, error)
                contexts.append(
                    _ReelSourceContext(
                        material=SourceMaterial(
                            source=source,
                            original_location=source.reference,
                            error=str(error)[:2_000],
                        )
                    )
                )
        return contexts

    def _extract_article(self, source: Source) -> _ReelSourceContext:
        document = self.article_ingestion.ingest(source)
        assets = [
            VisualAsset(
                id=image.id,
                source_id=source.id,
                kind=VisualAssetKind.ARTICLE_IMAGE,
                label=image.alt_text or f"Article image {index}",
                original_url=image.url,
            )
            for index, image in enumerate(document.images, start=1)
        ]
        return _ReelSourceContext(
            material=SourceMaterial(
                source=source,
                original_location=document.url or source.reference,
                metadata=SourceMetadata(
                    mime_type="text/html" if document.url else "text/plain",
                ),
                content=ExtractedContent(
                    segments=[
                        ContentSegment(id=paragraph.id, text=paragraph.text)
                        for paragraph in document.paragraphs
                    ],
                    assets=assets,
                ),
            )
        )

    def _extract_video(
        self,
        job_id: str,
        source: Source,
        index: int,
        total: int,
    ) -> _ReelSourceContext:
        self._set_status(
            job_id,
            JobStatus.ACQUIRING,
            7 + int(index / total * 18),
            f"Acquiring video {index} of {total}...",
        )
        source_path = self._acquire_video_source(job_id, source)
        metadata = self.ffmpeg.probe(source_path)
        self.ffmpeg.validate_decodable(source_path)
        transcript = ()
        error: str | None = None
        if metadata.has_audio:
            self._set_status(job_id, JobStatus.TRANSCRIBING, 28, "Transcribing video sources...")
            audio_path = self.files.reel_source_audio_path(job_id, source.id)
            self.ffmpeg.extract_audio(source_path, audio_path)
            transcript = tuple(self.transcriber.transcribe(audio_path))
            if not transcript:
                error = "Video transcription returned no timestamped spoken content"
        else:
            error = "Video has no audio to transcribe"
        material = SourceMaterial(
            source=source,
            original_location=source.reference,
            local_path=str(source_path),
            metadata=SourceMetadata(
                duration=metadata.duration,
                width=metadata.width,
                height=metadata.height,
                mime_type=mimetypes.guess_type(source_path.name)[0] or "video/*",
            ),
            content=ExtractedContent(
                segments=[
                    ContentSegment(
                        id=f"{source.id}-seg-{segment_index:03d}",
                        text=segment.text,
                        start=segment.start,
                        end=segment.end,
                    )
                    for segment_index, segment in enumerate(transcript, start=1)
                ]
            ),
            error=error,
        )
        return _ReelSourceContext(
            material=material,
            video=VideoSourceContext(
                source_id=source.id,
                path=source_path,
                metadata=metadata,
                transcript=transcript,
            ),
        )

    def _extract_image(self, job_id: str, source: Source) -> _ReelSourceContext:
        source_path = self.files.reel_upload_source_path(job_id, source.id, source.reference)
        if not source_path.is_file():
            raise FileNotFoundError("Uploaded image source is unavailable")
        width, height = self.ffmpeg.probe_image(source_path)
        asset_id = f"{source.id}-asset-01"
        asset = VisualAsset(
            id=asset_id,
            source_id=source.id,
            kind=VisualAssetKind.SOURCE_IMAGE,
            label=source.name,
            content_type=mimetypes.guess_type(source_path.name)[0],
            width=width,
            height=height,
        )
        return _ReelSourceContext(
            material=SourceMaterial(
                source=source,
                original_location=source.reference,
                local_path=str(source_path),
                metadata=SourceMetadata(
                    width=width,
                    height=height,
                    mime_type=asset.content_type,
                ),
                content=ExtractedContent(assets=[asset]),
            ),
            image_paths={asset_id: source_path},
            vision_image_path=source_path,
        )

    def _analyze_sources(self, job: JobRecord, contexts: list[_ReelSourceContext]) -> None:
        self._set_status(job.id, JobStatus.ANALYZING, 32, "Analyzing source material...")
        analyzable = [context for context in contexts if self._is_analyzable(context.material)]
        for index, context in enumerate(analyzable, start=1):
            try:
                analysis = self.source_analyzer.analyze(
                    context.material,
                    context.vision_image_path,
                )
                context.material = context.material.model_copy(
                    update={"analysis": hydrate_source_analysis(analysis, context.material)}
                )
            except Exception as error:
                logger.warning(
                    "Skipping unanalyzable source %s: %s", context.material.source.id, error
                )
                context.material = self._with_error(context.material, error)
            self._set_status(
                job.id,
                JobStatus.ANALYZING,
                32 + int(index / len(analyzable) * 14),
                f"Analyzing source {index} of {len(analyzable)}...",
            )

    def _is_analyzable(self, material: SourceMaterial) -> bool:
        return material.error is None and bool(material.content.segments or material.content.assets)

    def _acquire_video_source(self, job_id: str, source: Source) -> Path:
        if source.origin is ClipSourceOrigin.UPLOAD:
            path = self.files.reel_upload_source_path(job_id, source.id, source.reference)
            if not path.is_file():
                raise FileNotFoundError("Uploaded reel video source is unavailable")
            return path
        if source.origin is ClipSourceOrigin.YOUTUBE:
            return self.youtube.download(
                source.reference,
                self.files.clip_downloaded_source_template(job_id, source.id),
            )
        raise ValueError("Unsupported reel video source")

    def _video_sources(
        self,
        contexts: list[_ReelSourceContext],
        source_ids: list[str],
    ) -> dict[str, VideoSourceContext]:
        selected_ids = set(source_ids)
        return {
            context.video.source_id: context.video
            for context in contexts
            if context.video is not None and context.video.source_id in selected_ids
        }

    def _image_paths_for_scenes(
        self,
        job_id: str,
        scenes: tuple[Scene, ...],
        contexts: list[_ReelSourceContext],
    ) -> dict[str, Path]:
        image_paths = {
            asset_id: path for context in contexts for asset_id, path in context.image_paths.items()
        }
        materials_by_id = {context.material.source.id: context.material for context in contexts}
        for scene in scenes:
            visual = scene.visual
            if visual.type is not SceneVisualType.ARTICLE_IMAGE or visual.asset_id in image_paths:
                continue
            material = materials_by_id.get(visual.source_id or "")
            if material is None:
                continue
            asset = next(
                (
                    candidate
                    for candidate in material.content.assets
                    if candidate.id == visual.asset_id
                ),
                None,
            )
            if asset is None or not asset.original_url:
                continue
            destination = self.files.reel_article_image_path(
                job_id,
                material.source.id,
                asset.id,
            )
            try:
                self.article_ingestion.download_image(asset.original_url, destination)
                image_paths[asset.id] = destination
            except Exception as error:
                logger.warning("Article image %s could not be acquired: %s", asset.id, error)
        return image_paths

    def _with_error(self, material: SourceMaterial, error: Exception) -> SourceMaterial:
        message = str(error)[:2_000]
        if material.error:
            message = f"{material.error}; {message}"[:2_000]
        return material.model_copy(update={"error": message})

    def _settings_for_job(self, job: JobRecord) -> Settings:
        if job.narration_request is None:
            return self.settings
        request = job.narration_request
        return self.settings.model_copy(
            update={
                "tts_enabled": request.enabled,
                "tts_provider": request.provider,
                "tts_voice_id": request.options.voice,
                "tts_language": request.options.language,
                "tts_speed": request.options.speed,
            }
        )

    def _validate_output(
        self,
        width: int,
        height: int,
        has_audio: bool,
        duration: float,
        narration: object | None,
    ) -> None:
        if (width, height) != (self.settings.output_width, self.settings.output_height):
            raise FFmpegError("The final reel does not have the configured vertical dimensions")
        if narration is not None:
            narration_duration = getattr(narration, "duration", 0)
            if not has_audio:
                raise FFmpegError("The final narrated reel does not contain an audio stream")
            if duration + 0.1 < narration_duration:
                raise FFmpegError("The final reel truncates the measured narration")

    def _set_status(self, job_id: str, status: JobStatus, progress: int, step: str) -> JobRecord:
        return self.jobs.update(job_id, status=status, progress=progress, current_step=step)
