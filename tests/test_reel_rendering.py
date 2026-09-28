import json
import math
import shutil
import subprocess
import wave
from array import array
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.job import JobRecord, JobStatus
from app.models.reel import (
    EditorialAngle,
    EditorialDecision,
    EditorialScores,
    EvidenceReference,
    HookCandidate,
    PreferredVisualType,
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
from app.services.crop import SmartCropper
from app.services.editorial import EditorialOutcome
from app.services.ffmpeg import FFmpegService
from app.services.files import FileManager
from app.services.jobs import JobStore
from app.services.reel_composition import ReelCompositionService
from app.services.reel_narration import NarrationService
from app.services.visual_selection import VisualSelector

_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class FixtureTranscriber:
    def transcribe(self, audio_path: Path) -> list[object]:
        assert audio_path.is_file()
        from app.models.transcript import TranscriptSegment

        return [
            TranscriptSegment(
                start=0,
                end=2,
                text="The company raised its annual outlook after strong sales.",
            )
        ]


class FixtureSourceAnalyzer:
    def analyze(self, material: object, image_path: Path | None = None) -> SourceAnalysis:
        from app.models.reel import SourceMaterial

        assert isinstance(material, SourceMaterial)
        if material.source.type is ClipSourceType.IMAGE:
            assert image_path is not None and image_path.is_file()
            return SourceAnalysis(
                summary="The image is a supporting revenue chart.",
                topics=["earnings"],
                important_evidence=[
                    EvidenceReference(source_id="image-01", asset_id="image-01-asset-01")
                ],
            )
        return SourceAnalysis(
            summary="The source reports a raised annual outlook.",
            topics=["earnings"],
            important_evidence=[
                EvidenceReference(
                    source_id=material.source.id,
                    segment_id=material.content.segments[0].id,
                )
            ],
        )


class FixtureStorySelector:
    def group(self, _: list[object]) -> tuple[StoryCandidate, ...]:
        return (
            StoryCandidate(
                id="story_01",
                title="Company raises outlook",
                topic="company outlook",
                importance=0.9,
                source_ids=["video-01", "article-01", "image-01"],
                key_points=[
                    StoryKeyPoint(
                        text="The company raised its annual outlook after strong sales.",
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
                visual_availability=1,
            ),
        )

    def select(self, stories: tuple[StoryCandidate, ...]) -> StoryCandidate:
        return stories[0].model_copy(
            update={"selection_reason": "Three related sources support it."}
        )


class FixtureEditorialEngine:
    def develop(
        self,
        stories: tuple[StoryCandidate, ...],
        _: list[object],
    ) -> EditorialOutcome:
        story = stories[0].model_copy(
            update={
                "editorial_scores": EditorialScores(
                    importance=0.9,
                    novelty=0.7,
                    audience_interest=0.8,
                    clarity=0.9,
                    storytelling_potential=0.8,
                    factual_support=1,
                    visual_potential=1,
                    source_coverage=1,
                ),
                "overall_score": 0.9,
                "selection_reason": "Three related sources support a clear, useful development.",
            }
        )
        evidence = [EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")]
        angle = EditorialAngle(
            id="angle_01",
            angle="Why the outlook changed",
            rationale="It connects the announcement to the supplied sales result.",
            audience_interest_rationale="It quickly explains why the change matters.",
            evidence=evidence,
            editorial_scores=story.editorial_scores,
            overall_score=0.9,
            selection_reason="It has the strongest evidence and available visual support.",
        )
        hook = HookCandidate(
            id="hook_01",
            text="The company raised its annual outlook.",
            rationale="It opens with the directly supported development.",
            evidence=evidence,
            score=0.9,
            selection_reason="It is concise, factual, and leads into the story.",
        )
        decision = EditorialDecision(
            angles=[angle],
            selected_angle=angle,
            hooks=[hook],
            selected_hook=hook,
        )
        return EditorialOutcome((story,), story, angle, hook, decision)


class FixtureScriptGenerator:
    def generate(self, *_: object) -> ReelScript:
        return ReelScript(
            story_id="story_01",
            angle_id="angle_01",
            hook_id="hook_01",
            title="Company raises outlook",
            hook="The company raised its annual outlook.",
            sections=[
                ReelScriptSection(
                    id="section_01",
                    role=ScriptSectionRole.HOOK,
                    text="The company raised its annual outlook.",
                    duration_seconds=2,
                    evidence=[
                        EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")
                    ],
                    visual_intent="Show the company representative while the outlook changes.",
                    preferred_visual_type=PreferredVisualType.SOURCE_VIDEO,
                ),
                ReelScriptSection(
                    id="section_02",
                    role=ScriptSectionRole.IMPLICATION,
                    text="Strong sales support the outlook change.",
                    duration_seconds=2,
                    evidence=[
                        EvidenceReference(source_id="article-01", segment_id="article-01-p-001")
                    ],
                    visual_intent="Show the source chart supporting the reported sales result.",
                    preferred_visual_type=PreferredVisualType.SOURCE_IMAGE,
                ),
            ],
        )


class FixtureScenePlanner:
    def plan(self, *_: object) -> ScenePlanning:
        return ScenePlanning(
            scenes=[
                SceneProposal(
                    script_section_id="section_01",
                    visual=SceneVisual(
                        type=SceneVisualType.SOURCE_VIDEO,
                        source_id="video-01",
                        start=0,
                        end=2,
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


class UnusedYoutubeDownloader:
    def download(self, *_: object) -> Path:
        raise AssertionError("This fixture uses only local video sources")


class FixtureTTSProvider:
    """A deterministic audible provider used to test the full local audio path offline."""

    provider_name = "fixture"
    model_name = "sine-wave"
    speed_applied_by_provider = True
    is_available = True
    unavailable_reason = None

    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str, destination: Path, _: object) -> Path:
        self.texts.append(text)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 16_000
        duration = 2.1
        frames = round(sample_rate * duration)
        samples = array(
            "h",
            (
                round(5_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
                for index in range(frames)
            ),
        )
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(samples.tobytes())
        return destination


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="FFmpeg and FFprobe are required")
def test_reel_pipeline_renders_a_real_vertical_mp4_from_related_sources(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "temp",
        output_dir=tmp_path / "output",
        download_dir=tmp_path / "downloads",
        reel_min_duration_seconds=2,
        reel_max_duration_seconds=4,
        reel_words_per_minute=200,
    )
    files = FileManager(settings)
    files.initialize()
    jobs = JobStore(settings.data_dir)
    job = jobs.create(
        JobRecord(
            id="render-job",
            job_type="reel",
            source_type="reel",
            source_name="Related fixture sources",
            sources=[
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
                    name="Earnings article",
                    reference="The company raised its annual outlook after strong sales. " * 4,
                ),
                Source(
                    id="image-01",
                    type=ClipSourceType.IMAGE,
                    origin=ClipSourceOrigin.UPLOAD,
                    name="chart.png",
                    reference="chart.png",
                ),
            ],
        )
    )
    video_path = files.reel_upload_source_path(job.id, "video-01", "briefing.mp4")
    image_path = files.reel_upload_source_path(job.id, "image-01", "chart.png")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x247f74:s=1080x1920:r=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            "2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(video_path),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xf1c232:s=1080x1920:r=1",
            "-frames:v",
            "1",
            "-y",
            str(image_path),
        ],
        check=True,
    )

    ffmpeg = FFmpegService(output_width=settings.output_width, output_height=settings.output_height)
    provider = FixtureTTSProvider()
    result = ReelGenerationPipeline(
        settings=settings,
        files=files,
        jobs=jobs,
        ffmpeg=ffmpeg,
        article_ingestion=ArticleIngestionService(),
        transcriber=FixtureTranscriber(),  # type: ignore[arg-type]
        source_analyzer=FixtureSourceAnalyzer(),  # type: ignore[arg-type]
        story_selector=FixtureStorySelector(),  # type: ignore[arg-type]
        script_generator=FixtureScriptGenerator(),  # type: ignore[arg-type]
        scene_planner=FixtureScenePlanner(),  # type: ignore[arg-type]
        visual_selector=VisualSelector(),
        composer=ReelCompositionService(ffmpeg, SmartCropper.from_settings(settings)),
        youtube=UnusedYoutubeDownloader(),  # type: ignore[arg-type]
        editorial_engine=FixtureEditorialEngine(),  # type: ignore[arg-type]
        narration_factory=lambda current_settings, current_ffmpeg, cache_dir: NarrationService(
            current_settings,
            provider,
            current_ffmpeg,
            cache_dir,
        ),
    ).run(job.id)

    output = files.reel_path(job.id)
    plan = json.loads(files.reel_plan_path(job.id).read_text(encoding="utf-8"))
    metadata = ffmpeg.probe(output)
    ffmpeg.validate_decodable(output)
    _assert_nonblank_frames(output, [0.5, 2.5, 4])

    assert result.status is JobStatus.COMPLETED
    assert result.reel is not None
    assert metadata.width == 1080
    assert metadata.height == 1920
    assert 4.15 <= metadata.duration <= 4.45
    assert metadata.has_audio
    assert ffmpeg.probe_audio_duration(output) >= 4.15
    assert result.reel.has_audio
    assert result.reel.narration_duration == pytest.approx(4.35, abs=0.05)
    assert plan["version"] == "0.5.0"
    assert plan["editorial"]["selected_angle"]["id"] == "angle_01"
    assert plan["editorial"]["selected_hook"]["id"] == "hook_01"
    assert plan["script"]["sections"][0]["visual_intent"]
    assert plan["scenes"][0]["evidence"][0]["segment_id"] == "video-01-seg-001"
    assert [scene["start"] for scene in plan["scenes"]] == pytest.approx([0, 2.25], abs=0.05)
    assert plan["scenes"][0]["narration_segment_ids"] == ["narration_01"]
    assert plan["narration"]["provider"] == "fixture"
    assert plan["narration"]["duration"] == pytest.approx(4.35, abs=0.05)
    assert provider.texts == [
        "The company raised its annual outlook.",
        "Strong sales support the outlook change.",
    ]
    assert (files.job_data_dir(job.id) / "reel_editorial.json").is_file()
    assert (files.job_data_dir(job.id) / "reel_narration.json").is_file()
    assert files.reel_narration_path(job.id).is_file()


def _assert_nonblank_frames(video_path: Path, timestamps: list[float]) -> None:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        for timestamp in timestamps:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1_000)
            available, frame = capture.read()
            assert available
            assert frame.mean() > 5
    finally:
        capture.release()
