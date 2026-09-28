import pytest

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    ContentSegment,
    EvidenceReference,
    ExtractedContent,
    ReelScript,
    ReelScriptSection,
    ScenePlanning,
    SceneProposal,
    SceneVisual,
    SceneVisualType,
    ScriptSectionRole,
    SourceMaterial,
    SourceMetadata,
    StoryCandidate,
    StoryKeyPoint,
    VisualAsset,
    VisualAssetKind,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.scene_planning import OpenRouterScenePlanner, validate_scene_planning
from app.services.visual_selection import VisualSelector


def _story() -> StoryCandidate:
    return StoryCandidate(
        id="story_01",
        title="Outlook changes",
        topic="earnings outlook",
        importance=0.9,
        source_ids=["video-01", "image-01"],
        key_points=[
            StoryKeyPoint(
                text="The company changed its annual outlook.",
                evidence=[EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")],
            )
        ],
        visual_availability=0.9,
    )


def _script() -> ReelScript:
    return ReelScript(
        story_id="story_01",
        title="Outlook changes",
        hook="The outlook just changed.",
        sections=[
            ReelScriptSection(
                id="section_01",
                role=ScriptSectionRole.HOOK,
                text="The company changed its annual outlook after new results.",
                duration_seconds=5,
                evidence=[
                    EvidenceReference(
                        source_id="video-01",
                        segment_id="video-01-seg-001",
                        start=10,
                        end=14,
                    )
                ],
            )
        ],
    )


def _materials() -> list[SourceMaterial]:
    video = SourceMaterial(
        source=Source(
            id="video-01",
            type=ClipSourceType.VIDEO,
            origin=ClipSourceOrigin.UPLOAD,
            name="briefing.mp4",
            reference="briefing.mp4",
        ),
        metadata=SourceMetadata(duration=30, width=1920, height=1080),
        content=ExtractedContent(
            segments=[
                ContentSegment(
                    id="video-01-seg-001",
                    text="The company changed its annual outlook after results.",
                    start=10,
                    end=14,
                )
            ]
        ),
    )
    image = SourceMaterial(
        source=Source(
            id="image-01",
            type=ClipSourceType.IMAGE,
            origin=ClipSourceOrigin.UPLOAD,
            name="chart.jpg",
            reference="chart.jpg",
        ),
        content=ExtractedContent(
            assets=[
                VisualAsset(
                    id="image-01-asset-01",
                    source_id="image-01",
                    kind=VisualAssetKind.SOURCE_IMAGE,
                    label="Revenue chart",
                )
            ]
        ),
    )
    return [video, image]


def test_visual_selector_fits_relevant_video_to_the_scene_duration() -> None:
    planning = ScenePlanning(
        scenes=[
            SceneProposal(
                script_section_id="section_01",
                visual=SceneVisual(
                    type=SceneVisualType.SOURCE_VIDEO,
                    source_id="video-01",
                    start=10,
                    end=14,
                ),
            )
        ]
    )

    scene = VisualSelector().select(_script(), planning, _materials())[0]

    assert scene.visual.type is SceneVisualType.SOURCE_VIDEO
    assert scene.visual.end - scene.visual.start == 5


def test_visual_selector_uses_an_evidence_image_before_a_text_card() -> None:
    script = _script().model_copy(
        update={
            "sections": [
                _script()
                .sections[0]
                .model_copy(
                    update={
                        "evidence": [
                            EvidenceReference(source_id="image-01", asset_id="image-01-asset-01")
                        ]
                    }
                )
            ]
        }
    )
    planning = ScenePlanning(
        scenes=[
            SceneProposal(
                script_section_id="section_01",
                visual=SceneVisual(type=SceneVisualType.TEXT_CARD),
            )
        ]
    )

    scene = VisualSelector().select(script, planning, _materials())[0]

    assert scene.visual.type is SceneVisualType.SOURCE_IMAGE


def test_scene_planning_rejects_video_outside_the_source_duration() -> None:
    planning = ScenePlanning(
        scenes=[
            SceneProposal(
                script_section_id="section_01",
                visual=SceneVisual(
                    type=SceneVisualType.SOURCE_VIDEO,
                    source_id="video-01",
                    start=10,
                    end=40,
                ),
            )
        ]
    )

    with pytest.raises(LLMError, match="outside its source video"):
        validate_scene_planning(planning, _script(), _story(), _materials())


def test_scene_planner_uses_validated_structured_response() -> None:
    class FakeClient:
        def generate(self, *_: object, **__: object) -> ScenePlanning:
            return ScenePlanning(
                scenes=[
                    SceneProposal(
                        script_section_id="section_01",
                        visual=SceneVisual(type=SceneVisualType.TEXT_CARD),
                    )
                ]
            )

    planner = OpenRouterScenePlanner(Settings(_env_file=None, llm_api_key="test-key"))
    planner.client = FakeClient()  # type: ignore[assignment]

    assert (
        planner.plan(_story(), _script(), _materials()).scenes[0].script_section_id == "section_01"
    )
