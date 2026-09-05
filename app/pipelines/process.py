"""Single-process orchestration for a complete ClipFactory job."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import NoSuitableClipsError
from app.models.clip import RenderedClip
from app.models.job import JobRecord, JobStatus
from app.pipelines.candidates import CandidateGenerator
from app.pipelines.selection import select_non_overlapping
from app.services.crop import SmartCropper
from app.services.ffmpeg import FFmpegService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.llm import ClipSelector
from app.services.transcription import FasterWhisperTranscriber
from app.services.youtube import YoutubeDownloader

logger = logging.getLogger(__name__)


class ProcessingPipeline:
    """Coordinates local tools and persists useful state after each visible job step."""

    def __init__(
        self,
        settings: Settings,
        files: FileManager,
        jobs: JobStore,
        ffmpeg: FFmpegService,
        transcriber: FasterWhisperTranscriber,
        selector: ClipSelector,
        cropper: SmartCropper,
        youtube: YoutubeDownloader,
    ) -> None:
        self.settings = settings
        self.files = files
        self.jobs = jobs
        self.ffmpeg = ffmpeg
        self.transcriber = transcriber
        self.selector = selector
        self.cropper = cropper
        self.youtube = youtube

    def run(self, job_id: str) -> JobRecord:
        """Run a job synchronously; the web layer dispatches it to a local worker thread."""
        completed = False
        try:
            job = self.jobs.get(job_id)
            source_path = self._acquire_source(job)
            metadata = self.ffmpeg.probe(source_path)
            self.ffmpeg.validate_decodable(source_path)
            if not metadata.has_audio:
                raise NoSuitableClipsError("The source video has no audio track to transcribe")

            self._set_status(job_id, JobStatus.TRANSCRIBING, 20, "Extracting audio...")
            audio_path = self.files.workspace_dir(job_id) / "audio.wav"
            self.ffmpeg.extract_audio(source_path, audio_path)
            transcript = self.transcriber.transcribe(audio_path)
            self.files.write_transcript(job_id, [segment.model_dump() for segment in transcript])

            self._set_status(job_id, JobStatus.ANALYZING, 45, "Finding interesting moments...")
            minimum_duration = self.settings.min_clip_duration_seconds
            maximum_duration = self.settings.max_clip_duration_seconds
            candidates = CandidateGenerator(
                min_duration=minimum_duration,
                target_duration=(minimum_duration + maximum_duration) / 2,
                max_duration=maximum_duration,
            ).build(transcript)
            if not candidates:
                raise NoSuitableClipsError(
                    "No transcript windows match the configured clip duration"
                )
            analysis = self.selector.select(candidates, job.requested_clip_count, metadata.duration)
            valid_clips = [
                clip
                for clip in analysis.clips
                if self.settings.min_clip_duration_seconds
                <= clip.duration
                <= self.settings.max_clip_duration_seconds
            ]
            selected = select_non_overlapping(
                valid_clips,
                job.requested_clip_count,
                source_duration=metadata.duration,
            )
            if not selected:
                raise NoSuitableClipsError("No suitable non-overlapping clips were selected")

            rendered_clips: list[RenderedClip] = []
            framing_debug: list[dict[str, object]] = []
            total_clips = len(selected)
            for index, clip in enumerate(selected, start=1):
                progress = 65 + int((index - 1) / total_clips * 30)
                self._set_status(
                    job_id,
                    JobStatus.RENDERING,
                    progress,
                    f"Generating clip {index} of {total_clips}...",
                )
                filename = f"clip_{index:02d}.mp4"
                destination = self.files.output_dir(job_id) / filename
                framing = self.cropper.plan_framing(source_path, metadata, clip.start, clip.end)
                logger.info(
                    "Framing clip %s mode=%s scene_changes=%d",
                    filename,
                    framing.mode,
                    framing.scene_changes,
                )
                if self.settings.smart_crop_debug:
                    framing_debug.append(
                        {
                            "filename": filename,
                            "clip_start": clip.start,
                            "clip_end": clip.end,
                            **framing.debug_payload(),
                        }
                    )
                self.ffmpeg.render_vertical(
                    source_path,
                    destination,
                    clip.start,
                    clip.end,
                    framing.fallback_crop,
                    framing.camera_path,
                )
                rendered_clips.append(RenderedClip(**clip.model_dump(), filename=filename))

            if self.settings.smart_crop_debug:
                self.files.write_framing_debug(job_id, framing_debug)

            completed = True
            return self.jobs.update(
                job_id,
                status=JobStatus.COMPLETED,
                progress=100,
                current_step="Complete",
                completed_at=datetime.now(UTC),
                clips=rendered_clips,
            )
        except Exception as error:
            logger.exception("Processing job %s failed", job_id)
            return self.jobs.update(
                job_id,
                status=JobStatus.FAILED,
                current_step="Failed",
                error=str(error)[:2000],
            )
        finally:
            if completed:
                self.files.cleanup_successful_job(job_id)

    def _acquire_source(self, job: JobRecord) -> Path:
        self._set_status(job.id, JobStatus.ACQUIRING, 5, "Acquiring source video...")
        if job.source_type == "youtube":
            destination_template = self.files.downloaded_source_template(job.id)
            source = self.youtube.download(job.source_name, destination_template)
        else:
            source = self.files.find_upload_source(job.id)
        self._set_status(job.id, JobStatus.ACQUIRING, 15, "Validating source video...")
        return source

    def _set_status(self, job_id: str, status: JobStatus, progress: int, step: str) -> JobRecord:
        return self.jobs.update(job_id, status=status, progress=progress, current_step=step)
