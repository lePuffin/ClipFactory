from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.reel import (
    EvidenceReference,
    NarrationAudioSegment,
    NarrationMetadata,
    NarrationTimingPolicy,
    Scene,
    SceneVisual,
    TTSOptions,
)
from app.services.reel_narration import (
    NarrationSegmenter,
    NarrationService,
    assign_scene_starts,
    narration_cache_key,
    preprocess_for_tts,
    reconcile_scene_timing,
)
from app.services.tts import TTSError


class FakeProvider:
    provider_name = "fake"
    model_name = "fake-model"
    speed_applied_by_provider = False
    is_available = True
    unavailable_reason = None

    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str, destination: Path, options: TTSOptions) -> Path:
        self.calls.append(text)
        destination.write_bytes(b"provider-output")
        return destination


class UnavailableProvider(FakeProvider):
    is_available = False
    unavailable_reason = "engine unavailable"


class FakeFFmpeg:
    def __init__(self) -> None:
        self.durations: dict[Path, float] = {}

    def normalize_audio(
        self,
        source_path: Path,
        destination: Path,
        sample_rate: int,
        speed: float,
    ) -> None:
        destination.write_bytes(source_path.read_bytes())
        self.durations[destination] = 1.0 / speed

    def probe_audio_duration(self, path: Path) -> float:
        return self.durations.get(path, 1.0)

    def assemble_narration_audio(
        self,
        audio_paths: list[Path],
        pauses_after: list[float],
        destination: Path,
        sample_rate: int,
    ) -> None:
        destination.write_bytes(b"assembled")
        self.durations[destination] = sum(
            self.durations.get(path, 1.0) + pause
            for path, pause in zip(audio_paths, pauses_after, strict=True)
        )


def _scene(index: int) -> Scene:
    return Scene(
        id=f"scene_{index:02d}",
        script_section_id=f"section_{index:02d}",
        order=index,
        narration=f"NASA reports update {index}.",
        duration=2,
        evidence=[EvidenceReference(source_id="source-01", asset_id="asset-01")],
        visual=SceneVisual(type="text_card", headline="Update"),
    )


def test_segmenter_preserves_scene_provenance_and_preprocesses_acronyms(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")

    segments = NarrationSegmenter(settings).segment([_scene(1), _scene(2)])

    assert [segment.scene_id for segment in segments] == ["scene_01", "scene_02"]
    assert segments[0].script_section_id == "section_01"
    assert segments[0].tts_text == "N A S A reports update 1."
    assert segments[0].evidence[0].asset_id == "asset-01"
    assert preprocess_for_tts("  CPU and NASA  ") == "C P U and N A S A"


def test_cache_key_changes_for_audio_affecting_values() -> None:
    options = TTSOptions(voice=None, language="en", speed=1)
    baseline = narration_cache_key("fake", "model-a", options, "Hello", 48_000)

    assert baseline != narration_cache_key("fake", "model-b", options, "Hello", 48_000)
    assert baseline != narration_cache_key(
        "fake", "model-a", options.model_copy(update={"speed": 1.1}), "Hello", 48_000
    )
    assert baseline != narration_cache_key("fake", "model-a", options, "Hello again", 48_000)


def test_narration_service_reuses_cached_normalized_segments(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        tts_provider="pyttsx3",
        tts_sentence_pause_seconds=0.2,
    )
    provider = FakeProvider()
    service = NarrationService(settings, provider, FakeFFmpeg(), tmp_path / "cache")
    segments = NarrationSegmenter(settings).segment([_scene(1), _scene(2)])

    first = service.synthesize(segments, tmp_path / "first", tmp_path / "first.wav")
    second = service.synthesize(segments, tmp_path / "second", tmp_path / "second.wav")

    assert len(provider.calls) == 2
    assert first.duration == pytest.approx(2.2)
    assert second.duration == pytest.approx(2.2)
    assert [segment.cached for segment in first.segments] == [False, False]
    assert [segment.cached for segment in second.segments] == [True, True]


def test_unavailable_provider_has_an_explicit_error(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", tts_provider="pyttsx3")
    service = NarrationService(settings, UnavailableProvider(), FakeFFmpeg(), tmp_path / "cache")
    segments = NarrationSegmenter(settings).segment([_scene(1)])

    with pytest.raises(TTSError, match="Configured TTS provider 'fake' is unavailable"):
        service.synthesize(segments, tmp_path / "work", tmp_path / "narration.wav")


def test_reconcile_scene_timing_extends_scenes_from_measured_audio() -> None:
    scenes = [_scene(1), _scene(2)]
    options = TTSOptions(voice=None, language="en", speed=1)
    narration = NarrationMetadata(
        provider="fake",
        model="fake-model",
        options=options,
        timing_policy=NarrationTimingPolicy.EXTEND_SCENE,
        narration_volume=0.9,
        source_audio_enabled=True,
        source_audio_volume=0.12,
        ducking_enabled=True,
        duration=3.2,
        segments=[
            NarrationAudioSegment(
                id="narration_01",
                script_section_id="section_01",
                scene_id="scene_01",
                order=1,
                text="One.",
                tts_text="One.",
                evidence=[EvidenceReference(source_id="source-01", asset_id="asset-01")],
                cache_key="a" * 64,
                duration=1.2,
                start=0,
                end=1.2,
                pause_after=0.2,
            ),
            NarrationAudioSegment(
                id="narration_02",
                script_section_id="section_02",
                scene_id="scene_02",
                order=2,
                text="Two.",
                tts_text="Two.",
                evidence=[EvidenceReference(source_id="source-01", asset_id="asset-01")],
                cache_key="b" * 64,
                duration=1.8,
                start=1.4,
                end=3.2,
            ),
        ],
    )

    reconciled = reconcile_scene_timing(scenes, narration)

    assert [scene.start for scene in reconciled] == [0, 1.4]
    assert [scene.duration for scene in reconciled] == [1.4, 1.8]
    assert reconciled[0].narration_segment_ids == ["narration_01"]


def test_assign_scene_starts_preserves_silent_scene_durations() -> None:
    scenes = assign_scene_starts([_scene(1), _scene(2)])

    assert [scene.start for scene in scenes] == [0, 2]
    assert [scene.narration_segment_ids for scene in scenes] == [[], []]


def test_reconcile_scene_timing_keeps_short_measured_speech() -> None:
    scene = _scene(1)
    narration = NarrationMetadata(
        provider="fake",
        model="fake-model",
        options=TTSOptions(voice=None, language="en", speed=1),
        timing_policy=NarrationTimingPolicy.EXTEND_SCENE,
        narration_volume=0.9,
        source_audio_enabled=False,
        source_audio_volume=0,
        ducking_enabled=False,
        duration=0.25,
        segments=[
            NarrationAudioSegment(
                id="narration_01",
                script_section_id=scene.script_section_id,
                scene_id=scene.id,
                order=1,
                text=scene.narration,
                tts_text=scene.narration,
                evidence=scene.evidence,
                cache_key="a" * 64,
                duration=0.25,
                start=0,
                end=0.25,
            )
        ],
    )

    reconciled = reconcile_scene_timing([scene], narration)

    assert reconciled[0].duration == 0.25