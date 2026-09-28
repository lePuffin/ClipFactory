import json
from pathlib import Path

from app.core.config import Settings
from app.models.broll import VideoSourceContext
from app.models.job import JobRecord, JobStatus
from app.models.media import VideoMetadata
from app.models.reel import (
    EvidenceReference,
    ReelScript,
    ReelScriptSection,
    ScenePlanning,
    SceneProposal,
    SceneVisual,
    SceneVisualType,
    ScriptSectionRole,
    SourceAnalysis,
    StoryCandidate,
    StoryKeyPoint,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.pipelines.generate_reel import ReelGenerationPipeline
from app.services.article_ingestion import ArticleIngestionService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.visual_selection import VisualSelector


class FakeFFmpeg:
    def probe(self, source_path: Path) -> VideoMetadata:
        if source_path.name == "story_01.mp4":
            return VideoMetadata(duration=20, width=1080, height=1920, has_audio=False)
        assert source_path.is_file()
        return VideoMetadata(duration=40, width=1920, height=1080, has_audio=True)

    def probe_image(self, source_path: Path) -> tuple[int, int]:
        assert source_path.is_file()
        return 1200, 800

    def validate_decodable(self, source_path: Path) -> None:
        assert source_path.is_file()

    def extract_audio(self, _: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")


class FakeTranscriber:
    def transcribe(self, audio_path: Path) -> list[object]:
        assert audio_path.read_bytes() == b"audio"
        from app.models.transcript import TranscriptSegment

        return [
            TranscriptSegment(
                start=8,
                end=15,
                text="The company raised its annual revenue outlook after strong sales.",
            )
        ]


class FakeSourceAnalyzer:
    def analyze(self, material: object, image_path: Path | None = None) -> SourceAnalysis:
        from app.models.reel import SourceMaterial

        assert isinstance(material, SourceMaterial)
        if material.source.type is ClipSourceType.IMAGE:
            assert image_path is not None
            return SourceAnalysis(
                summary="The image shows a revenue chart.",
                topics=["earnings"],
                important_evidence=[
                    EvidenceReference(source_id=material.source.id, asset_id="image-01-asset-01")
                ],
            )
        segment = material.content.segments[0]
        return SourceAnalysis(
            summary="The source reports a raised annual revenue outlook.",
            topics=["earnings"],
            important_evidence=[
                EvidenceReference(source_id=material.source.id, segment_id=segment.id)
            ],
        )


class FakeStorySelector:
    def group(self, _: list[object]) -> tuple[StoryCandidate, ...]:
        return (
            StoryCandidate(
                id="story_01",
                title="Company raises outlook",
                topic="company earnings outlook",
                importance=0.94,
                source_ids=["video-01", "article-01", "image-01"],
                key_points=[
                    StoryKeyPoint(
                        text="The company raised its annual revenue outlook after strong sales.",
                        evidence=[
                            EvidenceReference(
                                source_id="video-01",
                                segment_id="video-01-seg-001",
                            ),
                            EvidenceReference(
                                source_id="article-01",
                                segment_id="article-01-p-001",
                            ),
                        ],
                    )
                ],
                visual_availability=0.9,
            ),
        )

    def select(self, stories: tuple[StoryCandidate, ...]) -> StoryCandidate:
        return stories[0].model_copy(
            update={"selection_reason": "It has supporting sources and visuals."}
        )


class FakeScriptGenerator:
    def generate(self, *_: object) -> ReelScript:
        return ReelScript(
            story_id="story_01",
            title="Company raises outlook",
            hook="The outlook just changed.",
            sections=[
                ReelScriptSection(
                    id="section_01",
                    role=ScriptSectionRole.HOOK,
                    text="The company raised its annual revenue outlook after strong sales.",
                    duration_seconds=10,
                    evidence=[
                        EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")
                    ],
                ),
                ReelScriptSection(
                    id="section_02",
                    role=ScriptSectionRole.TAKEAWAY,
                    text="The chart gives the announcement useful context.",
                    duration_seconds=10,
                    evidence=[
                        EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                    ],
                ),
            ],
        )


class FakeScenePlanner:
    def plan(self, *_: object) -> ScenePlanning:
        return ScenePlanning(
            scenes=[
                SceneProposal(
                    script_section_id="section_01",
                    visual=SceneVisual(
                        type=SceneVisualType.SOURCE_VIDEO,
                        source_id="video-01",
                        start=8,
                        end=15,
                    ),
                ),
                SceneProposal(
                    script_section_id="section_02",
                    visual=SceneVisual(
                        type=SceneVisualType.SOURCE_IMAGE,
                        source_id="image-01",
                        asset_id="image-01-asset-01",
                    ),
                ),
            ]
        )


class FakeComposer:
    def __init__(self) -> None:
        self.scenes: tuple[object, ...] = ()
        self.video_sources: dict[str, VideoSourceContext] = {}
        self.image_paths: dict[str, Path] = {}

    def compose(
        self,
        scenes: tuple[object, ...],
        video_sources: dict[str, VideoSourceContext],
        image_paths: dict[str, Path],
        _: Path,
        destination: Path,
    ) -> None:
        self.scenes = scenes
        self.video_sources = video_sources
        self.image_paths = image_paths
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"reel-mp4")


class UnusedYoutubeDownloader:
    def download(self, *_: object) -> Path:
        raise AssertionError("Uploaded test sources should not call yt-dlp")


class NoAudioVideoFFmpeg(FakeFFmpeg):
    def probe(self, source_path: Path) -> VideoMetadata:
        if source_path.name == "video-01.mp4":
            return VideoMetadata(duration=40, width=1920, height=1080, has_audio=False)
        return super().probe(source_path)


class RemainingSourceStorySelector:
    def group(self, _: list[object]) -> tuple[StoryCandidate, ...]:
        return (
            StoryCandidate(
                id="story_01",
                title="Company raises outlook",
                topic="company earnings outlook",
                importance=0.94,
                source_ids=["article-01", "image-01"],
                key_points=[
                    StoryKeyPoint(
                        text="The company raised its annual revenue outlook after strong sales.",
                        evidence=[
                            EvidenceReference(
                                source_id="article-01",
                                segment_id="article-01-p-001",
                            )
                        ],
                    )
                ],
                visual_availability=0.9,
            ),
        )

    def select(self, stories: tuple[StoryCandidate, ...]) -> StoryCandidate:
        return stories[0].model_copy(
            update={"selection_reason": "The remaining article and image support one story."}
        )


class RemainingSourceScriptGenerator:
    def generate(self, *_: object) -> ReelScript:
        return ReelScript(
            story_id="story_01",
            title="Company raises outlook",
            hook="The outlook just changed.",
            sections=[
                ReelScriptSection(
                    id="section_01",
                    role=ScriptSectionRole.HOOK,
                    text="The company raised its annual revenue outlook after strong sales.",
                    duration_seconds=10,
                    evidence=[
                        EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                    ],
                ),
                ReelScriptSection(
                    id="section_02",
                    role=ScriptSectionRole.TAKEAWAY,
                    text="The source chart gives the announcement useful context.",
                    duration_seconds=10,
                    evidence=[
                        EvidenceReference(source_id="image-01", asset_id="image-01-asset-01")
                    ],
                ),
            ],
        )


class RemainingSourceScenePlanner:
    def plan(self, *_: object) -> ScenePlanning:
        return ScenePlanning(
            scenes=[
                SceneProposal(
                    script_section_id="section_01",
                    visual=SceneVisual(type=SceneVisualType.TEXT_CARD),
                ),
                SceneProposal(
                    script_section_id="section_02",
                    visual=SceneVisual(
                        type=SceneVisualType.SOURCE_IMAGE,
                        source_id="image-01",
                        asset_id="image-01-asset-01",
                    ),
                ),
            ]
        )


def test_reel_pipeline_creates_a_provenanced_multi_source_mp4_plan(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
        tts_enabled=False,
    )
    files = FileManager(settings)
    files.initialize()
    jobs = JobStore(settings.data_dir)
    sources = [
        Source(
            id="video-01",
            type=ClipSourceType.VIDEO,
            origin=ClipSourceOrigin.UPLOAD,
            name="briefing.mp4",
            reference="briefing.mp4",
        ),
        Source(
            id="article-01",
            type=ClipSourceType.ARTICLE,
            origin=ClipSourceOrigin.ARTICLE_TEXT,
            name="Earnings report",
            reference="The company raised its annual revenue outlook after strong sales. " * 4,
        ),
        Source(
            id="image-01",
            type=ClipSourceType.IMAGE,
            origin=ClipSourceOrigin.UPLOAD,
            name="chart.jpg",
            reference="chart.jpg",
        ),
    ]
    job = jobs.create(
        JobRecord(
            id="reel-job",
            job_type="reel",
            source_type="reel",
            source_name="Earnings story",
            sources=sources,
        )
    )
    video_path = files.reel_upload_source_path(job.id, "video-01", "briefing.mp4")
    image_path = files.reel_upload_source_path(job.id, "image-01", "chart.jpg")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video")
    image_path.write_bytes(b"image")

    composer = FakeComposer()
    result = ReelGenerationPipeline(
        settings,
        files,
        jobs,
        FakeFFmpeg(),  # type: ignore[arg-type]
        ArticleIngestionService(),
        FakeTranscriber(),  # type: ignore[arg-type]
        FakeSourceAnalyzer(),  # type: ignore[arg-type]
        FakeStorySelector(),  # type: ignore[arg-type]
        FakeScriptGenerator(),  # type: ignore[arg-type]
        FakeScenePlanner(),  # type: ignore[arg-type]
        VisualSelector(),
        composer,  # type: ignore[arg-type]
        UnusedYoutubeDownloader(),  # type: ignore[arg-type]
    ).run(job.id)

    plan = json.loads(files.reel_plan_path(job.id).read_text(encoding="utf-8"))
    assert result.status is JobStatus.COMPLETED
    assert result.reel is not None
    assert files.reel_path(job.id).read_bytes() == b"reel-mp4"
    assert plan["story"]["selection_reason"] == "It has supporting sources and visuals."
    assert plan["script"]["sections"][0]["evidence"][0]["start"] == 8
    assert [scene["visual"]["type"] for scene in plan["scenes"]] == [
        "source_video",
        "source_image",
    ]
    assert [scene["start"] for scene in plan["scenes"]] == [0, 10]
    assert plan["narration"] is None
    assert set(composer.video_sources) == {"video-01"}
    assert set(composer.image_paths) == {"image-01-asset-01"}
    assert (files.job_data_dir(job.id) / "reel_sources.json").is_file()
    assert (files.job_data_dir(job.id) / "reel_story_candidates.json").is_file()
    assert (files.job_data_dir(job.id) / "reel_script.json").is_file()
    assert (files.job_data_dir(job.id) / "reel_scenes.json").is_file()
    assert not files.workspace_dir(job.id).exists()


def test_reel_pipeline_continues_when_one_video_has_no_audio(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
        tts_enabled=False,
    )
    files = FileManager(settings)
    files.initialize()
    jobs = JobStore(settings.data_dir)
    job = jobs.create(
        JobRecord(
            id="partial-reel-job",
            job_type="reel",
            source_type="reel",
            source_name="Partial source failure",
            sources=[
                Source(
                    id="video-01",
                    type=ClipSourceType.VIDEO,
                    origin=ClipSourceOrigin.UPLOAD,
                    name="silent.mp4",
                    reference="silent.mp4",
                ),
                Source(
                    id="article-01",
                    type=ClipSourceType.ARTICLE,
                    origin=ClipSourceOrigin.ARTICLE_TEXT,
                    name="Earnings report",
                    reference="The company raised its annual revenue outlook after strong sales. "
                    * 4,
                ),
                Source(
                    id="image-01",
                    type=ClipSourceType.IMAGE,
                    origin=ClipSourceOrigin.UPLOAD,
                    name="chart.jpg",
                    reference="chart.jpg",
                ),
            ],
        )
    )
    video_path = files.reel_upload_source_path(job.id, "video-01", "silent.mp4")
    image_path = files.reel_upload_source_path(job.id, "image-01", "chart.jpg")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"silent-video")
    image_path.write_bytes(b"image")

    composer = FakeComposer()
    result = ReelGenerationPipeline(
        settings,
        files,
        jobs,
        NoAudioVideoFFmpeg(),  # type: ignore[arg-type]
        ArticleIngestionService(),
        FakeTranscriber(),  # type: ignore[arg-type]
        FakeSourceAnalyzer(),  # type: ignore[arg-type]
        RemainingSourceStorySelector(),  # type: ignore[arg-type]
        RemainingSourceScriptGenerator(),  # type: ignore[arg-type]
        RemainingSourceScenePlanner(),  # type: ignore[arg-type]
        VisualSelector(),
        composer,  # type: ignore[arg-type]
        UnusedYoutubeDownloader(),  # type: ignore[arg-type]
    ).run(job.id)

    plan = json.loads(files.reel_plan_path(job.id).read_text(encoding="utf-8"))
    failed_video = next(
        source for source in plan["sources"] if source["source"]["id"] == "video-01"
    )
    assert result.status is JobStatus.COMPLETED
    assert "no audio" in failed_video["error"].casefold()
    assert plan["story"]["source_ids"] == ["article-01", "image-01"]
    assert not composer.video_sources
    assert set(composer.image_paths) == {"image-01-asset-01"}
