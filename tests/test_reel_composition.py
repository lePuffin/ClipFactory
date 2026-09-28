from pathlib import Path

from app.models.broll import VideoSourceContext
from app.models.media import VideoMetadata
from app.models.reel import (
    EvidenceReference,
    NarrationAudioSegment,
    NarrationMetadata,
    NarrationTimingPolicy,
    Scene,
    SceneVisual,
    SceneVisualType,
    TTSOptions,
)
from app.services.ffmpeg import SourceAudioScene
from app.services.framing import SmartFramingPlanner
from app.services.reel_composition import ReelCompositionService


class FakeFFmpeg:
    def __init__(self) -> None:
        self.video_scenes: list[Path] = []
        self.image_scenes: list[Path] = []
        self.text_scenes: list[Path] = []
        self.composed: tuple[list[Path], Path] | None = None
        self.narrated: tuple[list[Path], Path, Path, list[SourceAudioScene]] | None = None

    def write_overlay_text(self, _: str, destination: Path) -> int:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("text", encoding="utf-8")
        return 48

    def render_vertical_with_overlay(
        self, _: Path, destination: Path, *__: object, **___: object
    ) -> None:
        self.video_scenes.append(destination)

    def render_image_with_overlay(self, _: Path, destination: Path, *__: object) -> None:
        self.image_scenes.append(destination)

    def render_text_card(self, destination: Path, *_: object) -> None:
        self.text_scenes.append(destination)

    def compose_silent_scenes(self, visuals: list[Path], destination: Path) -> None:
        self.composed = visuals, destination

    def compose_narrated_scenes(
        self,
        visuals: list[Path],
        narration: Path,
        destination: Path,
        _: float,
        __: int,
        source_audio_scenes: list[SourceAudioScene],
        *___: object,
    ) -> None:
        self.narrated = visuals, narration, destination, source_audio_scenes


class FakeCropper:
    def plan_framing(self, _: Path, metadata: VideoMetadata, start: float, end: float) -> object:
        return SmartFramingPlanner().plan(metadata, end - start, ())


def _scene(index: int, visual: SceneVisual) -> Scene:
    return Scene(
        id=f"scene_{index:02d}",
        script_section_id=f"section_{index:02d}",
        duration=4,
        narration="The supported story is shown in this scene.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
        visual=visual,
    )


def test_reel_composer_uses_smart_crop_video_images_and_text_fallback(tmp_path: Path) -> None:
    ffmpeg = FakeFFmpeg()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    image_path = tmp_path / "chart.jpg"
    image_path.write_bytes(b"image")
    scenes = [
        _scene(
            1,
            SceneVisual(
                type=SceneVisualType.SOURCE_VIDEO,
                source_id="video-01",
                start=4,
                end=8,
            ),
        ),
        _scene(
            2,
            SceneVisual(
                type=SceneVisualType.SOURCE_IMAGE,
                source_id="image-01",
                asset_id="image-01-asset-01",
            ),
        ),
        _scene(3, SceneVisual(type=SceneVisualType.TEXT_CARD)),
    ]
    video_sources = {
        "video-01": VideoSourceContext(
            source_id="video-01",
            path=source_path,
            metadata=VideoMetadata(duration=20, width=1920, height=1080, has_audio=True),
            transcript=(),
        )
    }

    ReelCompositionService(ffmpeg, FakeCropper()).compose(  # type: ignore[arg-type]
        scenes,
        video_sources,
        {"image-01-asset-01": image_path},
        tmp_path,
        tmp_path / "story_01.mp4",
    )

    assert len(ffmpeg.video_scenes) == 1
    assert len(ffmpeg.image_scenes) == 1
    assert len(ffmpeg.text_scenes) == 1
    assert ffmpeg.composed is not None
    assert len(ffmpeg.composed[0]) == 3


def test_reel_composer_aligns_source_audio_with_narrated_scenes(tmp_path: Path) -> None:
    ffmpeg = FakeFFmpeg()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    narration_path = tmp_path / "narration.wav"
    narration_path.write_bytes(b"narration")
    scene = _scene(
        1,
        SceneVisual(
            type=SceneVisualType.SOURCE_VIDEO,
            source_id="video-01",
            start=4,
            end=6,
        ),
    ).model_copy(update={"duration": 5})
    narration = NarrationMetadata(
        provider="fake",
        model="fake-model",
        options=TTSOptions(voice=None, language="en", speed=1),
        timing_policy=NarrationTimingPolicy.EXTEND_SCENE,
        narration_volume=0.9,
        source_audio_enabled=True,
        source_audio_volume=0.12,
        ducking_enabled=True,
        duration=5,
        segments=[
            NarrationAudioSegment(
                id="narration_01",
                script_section_id="section_01",
                scene_id="scene_01",
                order=1,
                text=scene.narration,
                tts_text=scene.narration,
                evidence=scene.evidence,
                cache_key="a" * 64,
                duration=5,
                start=0,
                end=5,
            )
        ],
    )
    video_sources = {
        "video-01": VideoSourceContext(
            source_id="video-01",
            path=source_path,
            metadata=VideoMetadata(duration=20, width=1920, height=1080, has_audio=True),
            transcript=(),
        )
    }

    ReelCompositionService(ffmpeg, FakeCropper()).compose(  # type: ignore[arg-type]
        [scene],
        video_sources,
        {},
        tmp_path,
        tmp_path / "story_01.mp4",
        narration_path,
        narration,
    )

    assert ffmpeg.narrated is not None
    source_audio_scenes = ffmpeg.narrated[3]
    assert source_audio_scenes[0].duration == 5
    assert source_audio_scenes[0].source_start == 4
    assert source_audio_scenes[0].source_end == 6