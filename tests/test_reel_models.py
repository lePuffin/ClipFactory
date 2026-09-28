import pytest
from pydantic import ValidationError

from app.models.job import JobRecord
from app.models.reel import (
    EditorialAngle,
    EditorialDecision,
    EditorialScores,
    EvidenceReference,
    HookCandidate,
    PreferredVisualType,
    ReelScriptSection,
    Scene,
    SceneVisual,
    SceneVisualType,
    ScriptSectionRole,
    StatementType,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source


def test_reel_job_accepts_an_uploaded_image_source() -> None:
    image = Source(
        id="image-01",
        type=ClipSourceType.IMAGE,
        origin=ClipSourceOrigin.UPLOAD,
        name="announcement.jpg",
        reference="announcement.jpg",
    )

    job = JobRecord(
        id="reel-job",
        job_type="reel",
        source_type="reel",
        source_name="Multi-source story",
        sources=[image],
    )

    assert job.is_reel()
    assert job.sources[0].type is ClipSourceType.IMAGE


def test_scene_requires_provenance_and_a_valid_visual_reference() -> None:
    scene = Scene(
        id="scene-01",
        script_section_id="section-01",
        duration=4,
        narration="The announcement changes the market outlook.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
        visual=SceneVisual(
            type=SceneVisualType.SOURCE_VIDEO,
            source_id="video-01",
            start=12,
            end=16,
        ),
    )

    assert scene.visual.type is SceneVisualType.SOURCE_VIDEO
    with pytest.raises(ValidationError, match="source video scenes require"):
        SceneVisual(type=SceneVisualType.SOURCE_VIDEO, source_id="video-01")


def test_editorial_records_preserve_scores_hook_and_visual_intent() -> None:
    evidence = [EvidenceReference(source_id="article-01", segment_id="article-01-p-001")]
    angle = EditorialAngle(
        id="angle_01",
        angle="What the outlook change means",
        rationale="The change has a clear consequence for viewers.",
        audience_interest_rationale="It explains why the announcement matters.",
        evidence=evidence,
        editorial_scores=EditorialScores(importance=0.9, factual_support=1),
        overall_score=0.82,
    )
    hook = HookCandidate(
        id="hook_01",
        text="The outlook just changed.",
        rationale="It opens with the supported development.",
        evidence=evidence,
        score=0.8,
    )
    section = ReelScriptSection(
        id="section_01",
        role=ScriptSectionRole.KEY_REVELATION,
        text="The company raised its annual outlook after strong sales.",
        duration_seconds=5,
        evidence=evidence,
        statement_type=StatementType.SOURCE_CLAIM,
        visual_intent="Show the revenue chart while the outlook is named.",
        preferred_visual_type=PreferredVisualType.SOURCE_IMAGE,
        candidate_asset_ids=["image-01-asset-01"],
    )

    decision = EditorialDecision(
        angles=[angle],
        selected_angle=angle,
        hooks=[hook],
        selected_hook=hook,
    )

    assert decision.selected_angle is not None
    assert decision.selected_hook is not None
    assert section.statement_type is StatementType.SOURCE_CLAIM
    assert section.preferred_visual_type is PreferredVisualType.SOURCE_IMAGE