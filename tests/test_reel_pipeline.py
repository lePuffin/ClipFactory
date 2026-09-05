import json
from pathlib import Path

from app.core.config import Settings
from app.models.broll import VideoSourceContext
from app.models.job import JobRecord, JobStatus
from app.models.media import VideoMetadata
from app.models.script import NarrationTiming, ReelScript, ScriptSentence
from app.models.source import ReelSourceOrigin, ReelSourceType, Source
from app.models.transcript import TranscriptSegment
from app.pipelines.dispatch import JobDispatcher
from app.pipelines.generate_reel import ReelGenerationPipeline
from app.services.article_ingestion import ArticleIngestionService
from app.services.broll_selection import BRollSelector
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.tts import NarrationAudio


class FakeFFmpeg:
    def probe(self, source_path: Path) -> VideoMetadata:
        if source_path.name == "reel.mp4":
            return VideoMetadata(duration=6, width=1080, height=1920, has_audio=True)
        assert source_path.is_file()
        return VideoMetadata(duration=60, width=1920, height=1080, has_audio=True)

    def validate_decodable(self, source_path: Path) -> None:
        assert source_path.is_file()

    def extract_audio(self, _: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class FakeTranscriber:
    def transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        assert audio_path.read_bytes() == b"audio"
        return [TranscriptSegment(start=10, end=16, text="Markets changed after the announcement.")]


class FakeScriptGenerator:
    def generate(
        self,
        articles: object,
        video_transcripts: dict[str, tuple[TranscriptSegment, ...]],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
    ) -> ReelScript:
        assert list(articles)
        assert "video-01" in video_transcripts
        assert (minimum_duration_seconds, maximum_duration_seconds) == (30, 300)
        return ReelScript(
            title="Market report",
            summary="A test reel.",
            sentences=[
                ScriptSentence(
                    text="Markets changed after the announcement.",
                    duration_seconds=6,
                    source_ids=["video-01", "article-01"],
                )
            ],
        )


class FakeTTS:
    def synthesize(self, _: ReelScript, destination: Path) -> NarrationAudio:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"wav")
        return NarrationAudio(
            path=destination,
            duration=6,
            timings=(NarrationTiming(sentence_index=0, start=0, end=6),),
        )


class FakeComposer:
    def __init__(self) -> None:
        self.timeline: tuple[object, ...] = ()
        self.sources: tuple[VideoSourceContext, ...] = ()

    def compose(
        self,
        narration: NarrationAudio,
        timeline: tuple[object, ...],
        video_sources: list[VideoSourceContext],
        workspace: Path,
        destination: Path,
    ) -> None:
        assert narration.duration > 0
        assert workspace.name == "reel-job"
        self.timeline = timeline
        self.sources = tuple(video_sources)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"reel-mp4")


class UnusedYoutubeDownloader:
    def download(self, *_: object) -> Path:
        raise AssertionError("Uploaded sources should not call yt-dlp")


def test_reel_pipeline_completes_a_pasted_article_and_uploaded_video_job(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
    )
    files = FileManager(settings)
    files.initialize()
    jobs = JobStore(settings.data_dir)
    video = Source(
        id="video-01",
        type=ReelSourceType.VIDEO,
        origin=ReelSourceOrigin.UPLOAD,
        name="talk.mp4",
        reference="talk.mp4",
    )
    article = Source(
        id="article-01",
        type=ReelSourceType.ARTICLE,
        origin=ReelSourceOrigin.ARTICLE_TEXT,
        name="Market article",
        reference="The article reports a major market change after an official announcement. " * 3,
    )
    job = jobs.create(
        JobRecord(
            id="reel-job",
            job_type="reel",
            source_type="reel",
            source_name="Two-source reel",
            sources=[video, article],
        )
    )
    uploaded_source = files.reel_upload_source_path(job.id, video.id, video.reference)
    uploaded_source.parent.mkdir(parents=True, exist_ok=True)
    uploaded_source.write_bytes(b"source")

    composer = FakeComposer()
    pipeline = ReelGenerationPipeline(
        settings,
        files,
        jobs,
        FakeFFmpeg(),  # type: ignore[arg-type]
        ArticleIngestionService(),
        FakeTranscriber(),  # type: ignore[arg-type]
        FakeScriptGenerator(),
        FakeTTS(),  # type: ignore[arg-type]
        BRollSelector(),
        composer,  # type: ignore[arg-type]
        UnusedYoutubeDownloader(),  # type: ignore[arg-type]
    )

    result = pipeline.run(job.id)

    assert result.status is JobStatus.COMPLETED
    assert result.reel is not None
    assert result.reel.filename == "reel.mp4"
    assert files.reel_path(job.id).read_bytes() == b"reel-mp4"
    assert len(composer.timeline) == 1
    assert len(composer.sources) == 1
    source_data = json.loads((files.job_data_dir(job.id) / "reel_sources.json").read_text())
    assert source_data[0]["source"]["id"] == "video-01"
    assert (files.job_data_dir(job.id) / "reel_script.json").is_file()
    assert (files.job_data_dir(job.id) / "narration.json").is_file()
    assert (files.job_data_dir(job.id) / "broll_timeline.json").is_file()
    assert not files.workspace_dir(job.id).exists()


def test_dispatcher_routes_clip_and_reel_jobs_to_the_correct_processor(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    clip_job = store.create(
        JobRecord(id="clip-job", source_type="upload", source_name="source.mp4")
    )
    reel_job = store.create(
        JobRecord(
            id="reel-job",
            job_type="reel",
            source_type="reel",
            source_name="Reel",
            sources=[
                Source(
                    id="article-01",
                    type=ReelSourceType.ARTICLE,
                    origin=ReelSourceOrigin.ARTICLE_TEXT,
                    name="Article",
                    reference="A valid long enough article source for the routed job model." * 3,
                )
            ],
        )
    )

    class Processor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, job_id: str) -> JobRecord:
            self.calls.append(job_id)
            return store.get(job_id)

    clip_processor = Processor()
    reel_processor = Processor()
    dispatcher = JobDispatcher(store, clip_processor, reel_processor)

    assert dispatcher.run(clip_job.id) == clip_job
    assert dispatcher.run(reel_job.id) == reel_job
    assert clip_processor.calls == [clip_job.id]
    assert reel_processor.calls == [reel_job.id]