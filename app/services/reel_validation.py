"""Validation helpers that bind generated reel records to extracted source material."""

from collections.abc import Sequence

from app.core.exceptions import LLMError
from app.models.reel import (
    Claim,
    EvidenceReference,
    NotableQuote,
    ReelScript,
    ReelScriptSection,
    SourceAnalysis,
    SourceMaterial,
    StoryCandidate,
    StoryConflict,
    StoryKeyPoint,
)
from app.models.source import ClipSourceType


def hydrate_evidence(
    evidence: Sequence[EvidenceReference],
    materials: Sequence[SourceMaterial],
    allowed_source_ids: set[str] | None = None,
) -> list[EvidenceReference]:
    """Reject unknown evidence and fill video timestamps from transcript segments."""
    materials_by_id = {material.source.id: material for material in materials}
    hydrated: list[EvidenceReference] = []
    for reference in evidence:
        if allowed_source_ids is not None and reference.source_id not in allowed_source_ids:
            raise LLMError("Generated evidence referenced a source outside the selected story")
        material = materials_by_id.get(reference.source_id)
        if material is None:
            raise LLMError("Generated evidence referenced an unknown source")
        segments = {segment.id: segment for segment in material.content.segments}
        assets = {asset.id: asset for asset in material.content.assets}
        if reference.segment_id is not None:
            segment = segments.get(reference.segment_id)
            if segment is None:
                raise LLMError("Generated evidence referenced an unknown source segment")
            hydrated.append(_hydrate_segment_reference(reference, segment, material))
            continue
        if reference.asset_id not in assets:
            raise LLMError("Generated evidence referenced an unknown source asset")
        hydrated.append(reference)
    return hydrated


def hydrate_source_analysis(analysis: SourceAnalysis, material: SourceMaterial) -> SourceAnalysis:
    """Keep each source analysis self-contained and provenance-backed."""
    source_ids = {material.source.id}
    return analysis.model_copy(
        update={
            "claims": [_hydrate_claim(claim, [material], source_ids) for claim in analysis.claims],
            "notable_quotes": [
                _hydrate_quote(quote, [material], source_ids) for quote in analysis.notable_quotes
            ],
            "important_evidence": hydrate_evidence(
                analysis.important_evidence,
                [material],
                source_ids,
            ),
        }
    )


def hydrate_story_candidate(
    story: StoryCandidate,
    materials: Sequence[SourceMaterial],
) -> StoryCandidate:
    """Ensure a story only groups available sources and their real evidence."""
    known_source_ids = {
        material.source.id for material in materials if material.analysis is not None
    }
    if len(story.source_ids) != len(set(story.source_ids)):
        raise LLMError("A story candidate listed a source more than once")
    if not set(story.source_ids).issubset(known_source_ids):
        raise LLMError("A story candidate referenced an unavailable source")
    return story.model_copy(
        update={
            "key_points": [
                StoryKeyPoint(
                    text=point.text,
                    evidence=hydrate_evidence(point.evidence, materials, set(story.source_ids)),
                    statement_type=point.statement_type,
                )
                for point in story.key_points
            ],
            "conflicts": [
                StoryConflict(
                    description=conflict.description,
                    evidence=hydrate_evidence(
                        conflict.evidence,
                        materials,
                        set(story.source_ids),
                    ),
                )
                for conflict in story.conflicts
            ],
        }
    )


def hydrate_reel_script(
    script: ReelScript,
    story: StoryCandidate,
    materials: Sequence[SourceMaterial],
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
) -> ReelScript:
    """Validate every script statement against the selected story's source set."""
    if script.story_id != story.id:
        raise LLMError("The reel script was generated for a different story")
    if not minimum_duration_seconds <= script.planned_duration <= maximum_duration_seconds:
        raise LLMError(
            "The reel script duration is outside the configured range "
            f"({script.planned_duration:.1f}s; expected {minimum_duration_seconds}-"
            f"{maximum_duration_seconds}s)"
        )
    section_ids = [section.id for section in script.sections]
    if len(section_ids) != len(set(section_ids)):
        raise LLMError("The reel script contains duplicate section IDs")
    allowed_source_ids = set(story.source_ids)
    return script.model_copy(
        update={
            "sections": [
                ReelScriptSection(
                    id=section.id,
                    role=section.role,
                    text=section.text,
                    duration_seconds=section.duration_seconds,
                    evidence=hydrate_evidence(section.evidence, materials, allowed_source_ids),
                    visual_hint=section.visual_hint,
                    statement_type=section.statement_type,
                    visual_intent=section.visual_intent,
                    preferred_visual_type=section.preferred_visual_type,
                    candidate_asset_ids=section.candidate_asset_ids,
                )
                for section in script.sections
            ],
            "angle_id": script.angle_id,
            "hook_id": script.hook_id,
            "estimated_duration_seconds": script.estimated_duration_seconds,
        }
    )


def _hydrate_claim(
    claim: Claim,
    materials: Sequence[SourceMaterial],
    source_ids: set[str],
) -> Claim:
    return claim.model_copy(
        update={"evidence": hydrate_evidence(claim.evidence, materials, source_ids)}
    )


def _hydrate_quote(
    quote: NotableQuote,
    materials: Sequence[SourceMaterial],
    source_ids: set[str],
) -> NotableQuote:
    return quote.model_copy(
        update={"evidence": hydrate_evidence(quote.evidence, materials, source_ids)}
    )


def _hydrate_segment_reference(
    reference: EvidenceReference,
    segment: object,
    material: SourceMaterial,
) -> EvidenceReference:
    start = segment.start
    end = segment.end
    if material.source.type is not ClipSourceType.VIDEO:
        return reference
    if start is None or end is None:
        raise LLMError("Video evidence must reference a timestamped transcript segment")
    reference_start = reference.start if reference.start is not None else start
    reference_end = reference.end if reference.end is not None else end
    if reference_start < start or reference_end > end:
        raise LLMError("Generated video evidence falls outside its transcript segment")
    return reference.model_copy(update={"start": reference_start, "end": reference_end})
