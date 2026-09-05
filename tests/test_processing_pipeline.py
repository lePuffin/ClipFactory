import json
from pathlib import Path

from app.core.config import Settings
from app.models.clip import ClipAnalysis, ClipCandidate
from app.models.job import JobRecord, JobStatus
from app.models.media import VideoMetadata
from app.models.transcript import TranscriptSegment
from app.pipelines.process import ProcessingPipeline
from app.services.files import FileManager
from app.services.framing import SmartFramingPlanner
from app.services.jobs import JobStore


class FakeFFmpeg:
    def __init__(self) -> None:
        self.camera_paths: list[object] = []

    def probe(self, source_path: Path) -> VideoMetadata:
        assert source_path.is_file()
        return VideoMetadata(duration=120, width=1920, height=1080, has_audio=True)

    def validate_decodable(self, source_path: Path) -> None:
        assert source_path.is_file()

    def extract_audio(self, source_path: Path, destination: Path) -> None:
        destination.write_bytes(b"audio")

    def render_vertical(
        self,
        source_path: Path,
        destination: Path,
        start: float,
        end: float,
        crop: object,
        camera_path: object | None = None,
    ) -> None:
        self.camera_paths.append(camera_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"mp4")


class FakeTranscriber:
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        assert audio_path.read_bytes() == b"audio"
        return [
            TranscriptSegment(start=0, end=30, text="First complete thought."),
            TranscriptSegment(start=30, end=60, text="Second complete thought."),
            TranscriptSegment(start=60, end=90, text="Third complete thought."),
        ]


class FakeSelector:
    def select(self, candidates: object, clip_count: int, source_duration: float) -> ClipAnalysis:
        assert clip_count == 2
        assert source_duration == 120
        return ClipAnalysis(
            clips=[
                ClipCandidate(
                    start=0,
                    end=30,
                    score=90,
                    title="First",
                    reason="A strong complete opening thought.",
                ),
                ClipCandidate(
                    start=30,
                    end=60,
                    score=85,
                    title="Second",
                    reason="A useful complete follow-up thought.",
                ),
            ]
        )


class FakeCropper:
    def plan_framing(
        self,
        source_path: Path,
        metadata: VideoMetadata,
        clip_start: float,
        clip_end: float,
    ) -> object:
        assert source_path.is_file()
        return SmartFramingPlanner().plan(metadata, clip_end - clip_start, ())


class UnusedYoutubeDownloader:
    def download(self, *arguments: object) -> Path:
        raise AssertionError("Upload jobs should not invoke yt-dlp")


def test_pipeline_completes_upload_job_and_retains_output_and_transcript(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
        default_clip_count=2,
        smart_crop_debug=True,
    )
    files = FileManager(settings)
    files.initialize()
    store = JobStore(settings.data_dir)
    job = store.create(
        JobRecord(
            id="job-one",
            source_type="upload",
            source_name="source.mp4",
            requested_clip_count=2,
        )
    )
    files.upload_source_path(job.id, "source.mp4").parent.mkdir(parents=True, exist_ok=True)
    files.upload_source_path(job.id, "source.mp4").write_bytes(b"source")

    ffmpeg = FakeFFmpeg()
    pipeline = ProcessingPipeline(
        settings,
        files,
        store,
        ffmpeg,  # type: ignore[arg-type]
        FakeTranscriber(),  # type: ignore[arg-type]
        FakeSelector(),
        FakeCropper(),  # type: ignore[arg-type]
        UnusedYoutubeDownloader(),  # type: ignore[arg-type]
    )

    result = pipeline.run(job.id)

    assert result.status == JobStatus.COMPLETED
    assert result.progress == 100
    assert [clip.filename for clip in result.clips] == ["clip_01.mp4", "clip_02.mp4"]
    assert files.clip_path(job.id, "clip_01.mp4").read_bytes() == b"mp4"
    assert (files.job_data_dir(job.id) / "transcript.json").is_file()
    framing_debug = json.loads((files.job_data_dir(job.id) / "framing.json").read_text())
    assert [item["mode"] for item in framing_debug] == ["fallback", "fallback"]
    assert len(ffmpeg.camera_paths) == 2
    assert not files.workspace_dir(job.id).exists()
