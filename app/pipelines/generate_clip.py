"""Single-worker orchestration for a multi-source narrated vertical news clip."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import FFmpegError, NoSuitableClipsError
from app.models.article import ArticleDocument
from app.models.broll import VideoSourceContext
from app.models.clip import ClipOutput
from app.models.job import JobRecord, JobStatus
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.models.transcript import TranscriptSegment
from app.services.article_ingestion import ArticleIngestionService
from app.services.broll_selection import BRollSelector
from app.services.composition import ClipCompositionService
from app.services.ffmpeg import FFmpegService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.script_generation import ScriptGenerator
from app.services.transcription import FasterWhisperTranscriber
from app.services.tts import TTSService
from app.services.youtube import YoutubeDownloader

logger = logging.getLogger(__name__)


class ClipGenerationPipeline:
    """Coordinates article/video ingestion through narration-driven clip composition."""

    def __init__(
        self,
        settings: Settings,
        files: FileManager,
        jobs: JobStore,
        ffmpeg: FFmpegService,
        article_ingestion: ArticleIngestionService,
        transcriber: FasterWhisperTranscriber,
        script_generator: ScriptGenerator,
        tts: TTSService,
        broll_selector: BRollSelector,
        composer: ClipCompositionService,
        youtube: YoutubeDownloader,
    ) -> None:
        self.settings = settings
        self.files = files
        self.jobs = jobs
        self.ffmpeg = ffmpeg
        self.article_ingestion = article_ingestion
        self.transcriber = transcriber
        self.script_generator = script_generator
        self.tts = tts
        self.broll_selector = broll_selector
        self.composer = composer
        self.youtube = youtube

    def run(self, job_id: str) -> JobRecord:
        """Run one persisted clip job synchronously in the local worker thread."""
        completed = False
        try:
            job = self.jobs.get(job_id)
            if not job.is_clip():
                raise ValueError("The clip pipeline can only process clip jobs")
            articles, video_sources = self._ingest_sources(job)
            video_transcripts = {
                source.source_id: source.transcript
                for source in video_sources
                if source.transcript
            }
            if not articles and not video_transcripts:
                raise NoSuitableClipsError(
                    "No readable article text or spoken video content was available"
                )

            self._set_status(job.id, JobStatus.SCRIPTING, 40, "Writing the clip narrative...")
            script = self.script_generator.generate(
                articles,
                video_transcripts,
                self.settings.clip_min_duration_seconds,
                self.settings.clip_max_duration_seconds,
            )
            self.files.write_clip_script(job.id, script.model_dump(mode="json"))

            self._set_status(job.id, JobStatus.SYNTHESIZING, 55, "Generating local narration...")
            narration = self.tts.synthesize(script, self.files.clip_narration_path(job.id))
            self.files.write_narration_timing(
                job.id,
                {
                    "duration": narration.duration,
                    "timings": [timing.model_dump(mode="json") for timing in narration.timings],
                },
            )

            self._set_status(job.id, JobStatus.ASSEMBLING, 68, "Selecting source visuals...")
            timeline = self.broll_selector.allocate(script, narration.timings, video_sources)
            self.files.write_broll_timeline(
                job.id,
                [segment.model_dump(mode="json") for segment in timeline],
            )

            self._set_status(job.id, JobStatus.COMPOSING, 80, "Composing the final clip...")
            destination = self.files.clip_path(job.id)
            self.composer.compose(
                narration,
                timeline,
                video_sources,
                self.files.workspace_dir(job.id),
                destination,
            )
            output_metadata = self.ffmpeg.probe(destination)
            self._validate_output(
                output_metadata.width,
                output_metadata.height,
                output_metadata.has_audio,
            )

            completed = True
            return self.jobs.update(
                job.id,
                status=JobStatus.COMPLETED,
                progress=100,
                current_step="Complete",
                completed_at=datetime.now(UTC),
                clip=ClipOutput(
                    filename="clip.mp4",
                    title=script.title,
                    duration=output_metadata.duration,
                    source_count=len(job.sources),
                ),
            )
        except Exception as error:
            logger.exception("Clip generation for job %s failed", job_id)
            return self.jobs.update(
                job_id,
                status=JobStatus.FAILED,
                current_step="Failed",
                error=str(error)[:2000],
            )
        finally:
            if completed:
                self.files.cleanup_successful_job(job_id)

    def _ingest_sources(
        self,
        job: JobRecord,
    ) -> tuple[list[ArticleDocument], list[VideoSourceContext]]:
        self._set_status(job.id, JobStatus.INGESTING, 5, "Reading clip sources...")
        articles: list[ArticleDocument] = []
        video_sources: list[VideoSourceContext] = []
        persisted_sources: list[dict[str, object]] = []
        total_sources = len(job.sources)
        for index, source in enumerate(job.sources, start=1):
            if source.type is ClipSourceType.ARTICLE:
                article = self.article_ingestion.ingest(source)
                articles.append(article)
                persisted_sources.append(
                    {
                        "source": source.model_dump(mode="json"),
                        "article": article.model_dump(mode="json"),
                    }
                )
                continue

            progress = 8 + int(index / total_sources * 17)
            self._set_status(
                job.id,
                JobStatus.ACQUIRING,
                progress,
                f"Acquiring video source {index} of {total_sources}...",
            )
            video, transcript = self._ingest_video_source(job.id, source)
            video_sources.append(video)
            persisted_sources.append(
                {
                    "source": source.model_dump(mode="json"),
                    "metadata": {
                        "duration": video.metadata.duration,
                        "width": video.metadata.width,
                        "height": video.metadata.height,
                        "has_audio": video.metadata.has_audio,
                    },
                    "transcript": [
                        segment.model_dump(mode="json") for segment in transcript
                    ],
                }
            )
        self.files.write_clip_sources(job.id, persisted_sources)
        return articles, video_sources

    def _ingest_video_source(
        self,
        job_id: str,
        source: Source,
    ) -> tuple[VideoSourceContext, tuple[TranscriptSegment, ...]]:
        source_path = self._acquire_video_source(job_id, source)
        metadata = self.ffmpeg.probe(source_path)
        self.ffmpeg.validate_decodable(source_path)
        transcript: tuple[TranscriptSegment, ...] = ()
        if metadata.has_audio:
            self._set_status(job_id, JobStatus.TRANSCRIBING, 30, "Transcribing video sources...")
            audio_path = self.files.clip_source_audio_path(job_id, source.id)
            self.ffmpeg.extract_audio(source_path, audio_path)
            transcript = tuple(self.transcriber.transcribe(audio_path))
        return (
            VideoSourceContext(
                source_id=source.id,
                path=source_path,
                metadata=metadata,
                transcript=transcript,
            ),
            transcript,
        )

    def _acquire_video_source(self, job_id: str, source: Source) -> Path:
        if source.origin is ClipSourceOrigin.UPLOAD:
            path = self.files.clip_upload_source_path(job_id, source.id, source.reference)
            if not path.is_file():
                raise FileNotFoundError("Uploaded clip source is unavailable")
            return path
        if source.origin is ClipSourceOrigin.YOUTUBE:
            return self.youtube.download(
                source.reference,
                self.files.clip_downloaded_source_template(job_id, source.id),
            )
        raise ValueError("Unsupported clip video source")

    def _validate_output(self, width: int, height: int, has_audio: bool) -> None:
        if (width, height) != (self.settings.output_width, self.settings.output_height):
            raise FFmpegError(
                "The final clip does not have the configured vertical output dimensions"
            )
        if not has_audio:
            raise FFmpegError("The final clip does not contain the narration audio track")

    def _set_status(self, job_id: str, status: JobStatus, progress: int, step: str) -> JobRecord:
        return self.jobs.update(job_id, status=status, progress=progress, current_step=step)