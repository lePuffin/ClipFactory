import pytest

from app.core.exceptions import LLMError
from app.models.reel import (
    ContentSegment,
    EvidenceReference,
    ExtractedContent,
    SourceAnalysis,
    SourceMaterial,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.reel_validation import hydrate_evidence, hydrate_source_analysis


def _video_material() -> SourceMaterial:
    return SourceMaterial(
        source=Source(
            id="video-01",
            type=ClipSourceType.VIDEO,
            origin=ClipSourceOrigin.UPLOAD,
            name="briefing.mp4",
            reference="briefing.mp4",
        ),
        content=ExtractedContent(
            segments=[
                ContentSegment(
                    id="video-01-seg-001",
                    text="The company announced its earnings outlook.",
                    start=12,
                    end=18,
                )
            ]
        ),
    )


def test_evidence_hydrates_video_timestamps_from_the_known_transcript_segment() -> None:
    material = _video_material()

    evidence = hydrate_evidence(
        [EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")],
        [material],
    )

    assert evidence[0].start == 12
    assert evidence[0].end == 18


def test_source_analysis_cannot_reference_an_unknown_segment() -> None:
    material = _video_material()
    analysis = SourceAnalysis(
        summary="The video covers a company earnings outlook.",
        topics=["earnings"],
        important_evidence=[
            EvidenceReference(source_id="video-01", segment_id="video-01-seg-999")
        ],
    )

    with pytest.raises(LLMError, match="unknown source segment"):
        hydrate_source_analysis(analysis, material)