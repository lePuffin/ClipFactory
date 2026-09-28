"""Deterministic guardrails for short-form editorial scripts before rendering."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.exceptions import LLMError
from app.models.reel import (
    EditorialAngle,
    EvidenceReference,
    HookCandidate,
    ReelScript,
    ReelScriptSection,
    ScriptSectionRole,
    ScriptValidationReport,
    SourceMaterial,
    StoryCandidate,
)
from app.services.reel_validation import hydrate_reel_script

_WORD = re.compile(r"[A-Za-z0-9']+")
_ATTRIBUTION = re.compile(
    r"\b(according to|reported|reports|said|says|claims|sources disagree)\b",
    re.I,
)
_NON_SUBSTANTIVE_WORDS = frozenset(
    {
        "about",
        "after",
        "against",
        "annual",
        "being",
        "company",
        "could",
        "from",
        "into",
        "just",
        "more",
        "over",
        "said",
        "source",
        "story",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "what",
        "when",
        "which",
        "with",
        "would",
    }
)


@dataclass(frozen=True, slots=True)
class ValidatedScript:
    """A renderer-ready script plus the deterministic duration report."""

    script: ReelScript
    report: ScriptValidationReport


def estimate_spoken_duration(text: str, words_per_minute: int) -> float:
    """Estimate speech duration from word count at the configured delivery rate."""
    if words_per_minute <= 0:
        raise ValueError("words_per_minute must be positive")
    return len(_WORD.findall(text)) * 60 / words_per_minute


def validate_editorial_script(
    script: ReelScript,
    story: StoryCandidate,
    angle: EditorialAngle,
    hook: HookCandidate,
    materials: Sequence[SourceMaterial],
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
    words_per_minute: int,
) -> ValidatedScript:
    """Validate, normalize timing, and retain only an evidence-backed editorial script."""
    _validate_editorial_identity(script, story, angle, hook)
    word_count = sum(len(_WORD.findall(section.text)) for section in script.sections)
    estimated_duration = word_count * 60 / words_per_minute
    if not minimum_duration_seconds <= estimated_duration <= maximum_duration_seconds:
        raise LLMError(
            "The editorial script spoken-duration estimate is outside the configured range "
            f"({estimated_duration:.1f}s; expected {minimum_duration_seconds}-"
            f"{maximum_duration_seconds}s)"
        )
    normalized = _normalize_section_durations(script, words_per_minute, estimated_duration)
    hydrated = hydrate_reel_script(
        normalized,
        story,
        materials,
        minimum_duration_seconds,
        maximum_duration_seconds,
    )
    _validate_structure(hydrated)
    _validate_visual_intent(hydrated, materials)
    unsupported = find_unsupported_claims(hydrated, story, materials)
    if unsupported:
        raise LLMError(
            f"The editorial script contains unsupported claims: {'; '.join(unsupported)}"
        )
    _validate_conflict_attribution(hydrated, story)
    return ValidatedScript(
        script=hydrated,
        report=ScriptValidationReport(
            word_count=word_count,
            estimated_duration_seconds=estimated_duration,
        ),
    )


def find_unsupported_claims(
    script: ReelScript,
    story: StoryCandidate,
    materials: Sequence[SourceMaterial],
) -> list[str]:
    """Flag sections with no substantive lexical anchor in their cited evidence."""
    materials_by_id = {material.source.id: material for material in materials}
    problems: list[str] = []
    for section in script.sections:
        section_terms = _substantive_terms(section.text)
        if len(section_terms) < 2:
            continue
        support_text = _evidence_text(section.evidence, story, materials_by_id)
        if section_terms.isdisjoint(_substantive_terms(support_text)):
            problems.append(f"{section.id} has no substantive terms in its cited evidence")
    return problems


def _validate_editorial_identity(
    script: ReelScript,
    story: StoryCandidate,
    angle: EditorialAngle,
    hook: HookCandidate,
) -> None:
    if script.story_id != story.id:
        raise LLMError("The editorial script was generated for a different story")
    if script.angle_id != angle.id:
        raise LLMError("The editorial script does not preserve the selected angle")
    if script.hook_id != hook.id or script.hook != hook.text:
        raise LLMError("The editorial script does not preserve the selected hook")


def _normalize_section_durations(
    script: ReelScript, words_per_minute: int, estimated_duration: float
) -> ReelScript:
    sections: list[ReelScriptSection] = []
    for section in script.sections:
        duration = estimate_spoken_duration(section.text, words_per_minute)
        if duration <= 0.5:
            raise LLMError("Every editorial script section needs enough spoken content to render")
        if duration > 30:
            raise LLMError(
                f"Editorial script section {section.id} is longer than 30 seconds; split it"
            )
        sections.append(section.model_copy(update={"duration_seconds": duration}))
    return script.model_copy(
        update={
            "sections": sections,
            "estimated_duration_seconds": estimated_duration,
        }
    )


def _validate_structure(script: ReelScript) -> None:
    if script.sections[0].role is not ScriptSectionRole.HOOK:
        raise LLMError("The first editorial script section must be a hook")
    if script.sections[0].text != script.hook:
        raise LLMError("The first editorial script section must use the selected hook text")
    normalized_sections = [_normalized_text(section.text) for section in script.sections]
    if len(normalized_sections) != len(set(normalized_sections)):
        raise LLMError("The editorial script contains duplicate information")


def _validate_visual_intent(script: ReelScript, materials: Sequence[SourceMaterial]) -> None:
    asset_ids = {
        asset.id
        for material in materials
        for asset in material.content.assets
    }
    for section in script.sections:
        if not section.visual_intent:
            raise LLMError(f"Editorial script section {section.id} has no visual intent")
        if section.preferred_visual_type is None:
            raise LLMError(f"Editorial script section {section.id} has no preferred visual type")
        unknown_assets = set(section.candidate_asset_ids).difference(asset_ids)
        if unknown_assets:
            raise LLMError(
                f"Editorial script section {section.id} references an unknown visual asset"
            )


def _validate_conflict_attribution(script: ReelScript, story: StoryCandidate) -> None:
    for section in script.sections:
        section_sources = {reference.source_id for reference in section.evidence}
        for conflict in story.conflicts:
            conflict_sources = {reference.source_id for reference in conflict.evidence}
            if len(section_sources.intersection(conflict_sources)) < 2:
                continue
            if (
                section.statement_type.value != "source_claim"
                or not _ATTRIBUTION.search(section.text)
            ):
                raise LLMError(
                    f"Editorial script section {section.id} must attribute the source conflict"
                )


def _evidence_text(
    evidence: Sequence[EvidenceReference],
    story: StoryCandidate,
    materials_by_id: dict[str, SourceMaterial],
) -> str:
    evidence_keys = {_evidence_key(reference) for reference in evidence}
    text: list[str] = []
    for reference in evidence:
        material = materials_by_id.get(reference.source_id)
        if material is None:
            continue
        if reference.segment_id:
            segment = next(
                (item for item in material.content.segments if item.id == reference.segment_id),
                None,
            )
            if segment is not None:
                text.append(segment.text)
        if reference.asset_id:
            asset = next(
                (item for item in material.content.assets if item.id == reference.asset_id),
                None,
            )
            if asset is not None:
                text.append(asset.label)
    for point in story.key_points:
        if evidence_keys.intersection(_evidence_key(reference) for reference in point.evidence):
            text.append(point.text)
    return " ".join(text)


def _evidence_key(reference: EvidenceReference) -> tuple[str, str | None, str | None]:
    return reference.source_id, reference.segment_id, reference.asset_id


def _substantive_terms(text: str) -> set[str]:
    return {
        word.casefold()
        for word in _WORD.findall(text)
        if len(word) > 2 and word.casefold() not in _NON_SUBSTANTIVE_WORDS
    }


def _normalized_text(text: str) -> str:
    return " ".join(word.casefold() for word in _WORD.findall(text))