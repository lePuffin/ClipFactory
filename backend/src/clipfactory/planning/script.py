"""Grounded script generation request, output schema, and deterministic gate."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import ceil, floor
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clipfactory.domain.graphics import (
    GraphicsSpec,
    VisualKind,
    validate_graphics_claims,
    validate_graphics_kind,
)
from clipfactory.domain.models import Claim, ClaimKind, ClaimStatus, ContentProfile, SupportLevel
from clipfactory.ports.llm import LLMMessage, LLMProvider


class ScriptSegmentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    claim_ids: list[UUID] = Field(min_length=1)
    attribution: str | None = None
    purpose: Literal["hook", "context", "evidence", "significance", "uncertainty", "conclusion"] = "evidence"


class SocialMetadataDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=2000)
    hashtags: list[str] = Field(min_length=3, max_length=8)


class VisualDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    media_type: Literal["image", "video", "any"]
    category: str
    description: str = Field(min_length=1)
    subjects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    strategy: Literal["reuse_first", "acquire_only", "generate_allowed"] = "reuse_first"
    motion: Literal["none", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "ken_burns"] = "none"
    transition_in: Literal["cut", "crossfade", "fade_black", "slide_left", "slide_up"] = "cut"
    motion_reason: str = ""
    kind: VisualKind = "media"
    graphics_spec: GraphicsSpec | None = None
    fallback_graphics_spec: GraphicsSpec | None = None
    search_queries: list[str] = Field(default_factory=list, max_length=2)

    @field_validator("search_queries")
    @classmethod
    def bounded_queries(cls, values: list[str]) -> list[str]:
        values = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 120 or len(value.split()) > 12 for value in values):
            raise ValueError("search queries must be concise non-empty keywords (at most 120 characters, 12 words)")
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError("search queries must be distinct")
        return values

    @model_validator(mode="after")
    def graphics_matches_kind(self) -> Self:
        validate_graphics_kind(self.kind, self.graphics_spec)
        if self.kind != "media" and self.fallback_graphics_spec is not None:
            raise ValueError("only media visuals may declare a separate graphics fallback")
        if " ".join(self.description.split()).casefold() in {query.casefold() for query in self.search_queries}:
            raise ValueError("refined search queries must differ from the original description")
        return self


class EditorialDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_index: int = Field(ge=0)
    kind: Literal["headline", "place", "source", "quote", "number"]
    text: str = Field(min_length=1, max_length=80)
    secondary: str = Field(default="", max_length=70)
    claim_ids: list[UUID] = Field(min_length=1)


class WriteScriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[ScriptSegmentDraft] = Field(min_length=1)
    social_metadata: SocialMetadataDraft
    visuals: list[VisualDraft] = Field(min_length=1)
    editorial_overlays: list[EditorialDraft] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_visual_coverage(self) -> Self:
        if len(self.visuals) < len(self.segments):
            raise ValueError("visuals must include at least one Visual Segment per Script Segment")
        if any(cue.segment_index >= len(self.segments) for cue in self.editorial_overlays):
            raise ValueError("editorial overlay references an unknown Script Segment")
        return self


@dataclass(frozen=True, slots=True)
class ScriptSegment:
    index: int
    text: str
    claim_ids: tuple[UUID, ...]
    attribution: str | None
    estimated_duration_seconds: float
    purpose: str = "evidence"


@dataclass(frozen=True, slots=True)
class GeneratedScript:
    language: str
    segments: tuple[ScriptSegment, ...]
    word_count: int
    estimated_duration_seconds: float
    social_metadata: SocialMetadataDraft
    visuals: tuple[VisualDraft, ...]
    model: str
    editorial_overlays: tuple[EditorialDraft, ...] = ()


class ScriptGateError(ValueError):
    def __init__(self, codes: list[str], detail: str = "") -> None:
        super().__init__(", ".join(codes))
        self.codes = tuple(codes)
        self.detail = detail


async def generate_script(
    provider: LLMProvider,
    *,
    story_title: str,
    story_summary: str,
    claims: Sequence[Claim],
    key_fact_claim_ids: Sequence[UUID],
    profile: ContentProfile,
    lead_in_seconds: float = 0.3,
    tail_seconds: float = 1.0,
    min_segments: int = 4,
    max_segments: int = 8,
    hook_max_seconds: float = 5.0,
    prompt_version: str = "write_script.v2",
    revision_instructions: Sequence[str] = (),
    target_word_count: int | None = None,
    source_attributions: Sequence[str] = (),
    claim_publishers: Mapping[UUID, Sequence[str]] | None = None,
    previous_script: Mapping[str, object] | None = None,
) -> GeneratedScript:
    accepted = [claim for claim in claims if claim.status == ClaimStatus.ACCEPTED]
    allowed_ids = {claim.id for claim in accepted}
    if not set(key_fact_claim_ids) <= allowed_ids:
        raise ValueError("key facts must reference accepted Claims")
    publishers = claim_publishers or {}
    key_fact_ids = set(key_fact_claim_ids)
    claim_data = [
        {
            "claim_id": str(claim.id),
            "text": claim.text,
            "kind": claim.kind.value,
            "support_level": claim.support_level.value,
            "requires_attribution": _requires_attribution(claim),
            "publishers": list(publishers.get(claim.id, ())),
            "evidence": [item.excerpt for item in claim.evidence if item.verified],
        }
        for claim in accepted
        if claim.id in key_fact_ids
    ]
    words_per_minute = profile.voice.words_per_minute
    target_seconds = profile.duration.target_seconds - lead_in_seconds - tail_seconds
    target_words = target_word_count or round(target_seconds * words_per_minute / 60)
    minimum_words = ceil((profile.duration.min_seconds - lead_in_seconds - tail_seconds) * words_per_minute / 60)
    maximum_words = floor((profile.duration.max_seconds - lead_in_seconds - tail_seconds) * words_per_minute / 60)
    messages = [
        LLMMessage(
            "system",
            f"Write one source-grounded narration script in {profile.language}. Target {target_words} words. "
            f"The complete narration must contain {minimum_words} to {maximum_words} words in total. "
            f"Return {min_segments} to {max_segments} segments. "
            f"The grounded hook is at most {hook_max_seconds} seconds. "
            f"The first segment must contain at most {int(hook_max_seconds * words_per_minute / 60)} words. "
            "Count every spoken word, including publisher credits, in that hook limit. "
            "Use one compact hook sentence; put supporting detail in the next segment. "
            "The visuals array must have at least one entry per Script Segment, in matching order. "
            "Every factual statement must reference only accepted Claim IDs. "
            "Classify each visual kind: media (default), infographic, or scientific. "
            "Use infographic for statistic/comparison/timeline and scientific for function_plot/relationship_diagram. "
            "Graphics require generate_allowed, video media_type, and graphics_spec matching its typed template. "
            "Graphics never depict people; supported names are text labels only, not depicted subjects. "
            "For media visuals, optionally declare a suitable accepted-Claim-grounded fallback_graphics_spec "
            "using those same trusted templates; keep primary graphics_spec null. Do not invent a graphic "
            "when evidence is unsuitable. Also supply up to two different precise free-media keyword "
            "search_queries, distinct from the description and each other, at most 120 characters and 12 words. "
            "These alternatives must preserve the original shot's subjects and objective. "
            "Every graphics title/label/date/edge has verbatim accepted-evidence text and claim_ids; values must "
            "occur in the same evidence as their labels. Do not invent labels, values, markup, code, URLs or maps. "
            "Function plots are declared mathematical functions, never measured observations; only linear "
            "(a*x+b), quadratic (a*x*x+b*x+c), sine (a*sin(b*x+c)), cosine (a*cos(b*x+c)) are supported. "
            "Attribute single-source and attributed Claims by publisher. "
            "Set a non-empty attribution field on every segment citing a single-source or attributed Claim. "
            "Claims marked requires_attribution=true need that segment's attribution field set to one of the "
            "Claim's listed publishers, and the narration should credit it (e.g. 'according to <publisher>'). "
            "Use a modern news-explainer structure: grounded hook, context, evidence, why it matters, "
            "uncertainty and conclusion. "
            "Record each segment's purpose. Keep narration coherent and avoid repeating the same claim to fill time. "
            "Stay on the selected Story; unrelated entries from a rolling live blog are not part of this Clip. "
            "Spell supported numbers, currency and abbreviations naturally for speech instead of digits, "
            "currency symbols or typographic hyphens. Preserve the exact factual value. "
            "Return concise editorial_overlays for headline/place/source/key-number context, "
            "bound to segment_index and accepted claim_ids. "
            "Use real specific subjects/tags for search, not sentences such as 'visual representation of'. "
            "Mix relevant photos, maps and B-roll with media_type any where either works. "
            "Script motion and transitions separately for each shot according to its narration and subject. "
            "Record the editorial reason in motion_reason. Use none for reading-focused graphics and native video; "
            "only use pans or zooms to guide attention to the concrete subject. Cuts are the default; "
            "use a transition only for a motivated change of time, place or viewpoint. Avoid repeated zooms. "
            "Never invent a person's identity, a date, a fact, or an engagement promise for a graphic. "
            "Use names, numbers, dates and quotes only when supported by the provided Claims. "
            "Do not add URLs, Markdown, SSML, emoji, or unsupported facts. "
            f"Prompt version: {prompt_version}.",
        ),
        LLMMessage(
            "user",
            "Story: "
            + json.dumps({"title": story_title, "summary": story_summary}, ensure_ascii=False)
            + "\nProfile: "
            + json.dumps(
                {
                    "language": profile.language,
                    "category": profile.category.value,
                    "visual_style": profile.visual_style.description,
                    "allow_generated_media": profile.visual_style.allow_generated_media,
                },
                ensure_ascii=False,
            )
            + "\nKey facts: "
            + json.dumps([str(item) for item in key_fact_claim_ids])
            + "\n<untrusted-accepted-claims>\n"
            + json.dumps(claim_data, ensure_ascii=False)
            + "\n</untrusted-accepted-claims>",
        ),
    ]
    if source_attributions:
        messages.append(
            LLMMessage(
                "user",
                "Source provenance: use publisher names for the required attribution field and spoken credits; "
                "put URLs only in metadata, never narration. " + json.dumps(source_attributions),
            )
        )
    if previous_script is not None:
        messages.append(
            LLMMessage(
                "user",
                "Revise the previous script below only as required by the requested corrections. "
                "Preserve unaffected segment text, claim_ids, attribution, purpose and visual intent. "
                "For narration duration corrections, adjust body segments and keep an already-passing hook unchanged. "
                "Return the complete script and visual draft, not a patch.\n<untrusted-previous-script>\n"
                + json.dumps(dict(previous_script), ensure_ascii=False)
                + "\n</untrusted-previous-script>",
            )
        )
    if revision_instructions:
        messages.append(
            LLMMessage(
                "user",
                "Correct these previous gate failures: "
                + "; ".join(revision_instructions)
                + ". All original constraints still apply: keep required publisher attribution fields and spoken "
                "credits when shortening the hook, and keep the hook within its word limit when adding credits. "
                "Do not trade one gate failure for another. Count the final hook and total narration before replying.",
            )
        )
    response = await provider.generate_structured("write_script", messages, WriteScriptResult)
    if any(not set(cue.claim_ids) <= allowed_ids for cue in response.value.editorial_overlays):
        raise ScriptGateError(["unknown_claim"])
    if len(response.value.visuals) < len(response.value.segments):
        raise ValueError("visual plan draft must include at least one Visual Segment per Script Segment")
    script = _build_script(response.value, profile, lead_in_seconds, tail_seconds)
    for visual in script.visuals:
        if visual.graphics_spec is not None:
            validate_graphics_claims(visual.graphics_spec, accepted)
        if visual.fallback_graphics_spec is not None:
            validate_graphics_claims(visual.fallback_graphics_spec, accepted)
    script = _attribution_from_narration(script, publishers)
    if not script.editorial_overlays:
        for segment in script.segments:
            if segment.estimated_duration_seconds < 4:
                continue
            bound = next(
                (
                    (claim_id, publisher)
                    for claim_id in segment.claim_ids
                    for publisher in publishers.get(claim_id, ())
                    if publisher and len(publisher) <= 80
                ),
                None,
            )
            if bound:
                script = replace(
                    script,
                    editorial_overlays=(
                        EditorialDraft(segment_index=segment.index, kind="source", text=bound[1], claim_ids=[bound[0]]),
                    ),
                )
                break
    validate_script_gate(
        script,
        claims=accepted,
        profile=profile,
        min_segments=min_segments,
        max_segments=max_segments,
        hook_max_seconds=hook_max_seconds,
        lead_in_seconds=lead_in_seconds,
        tail_seconds=tail_seconds,
    )
    return GeneratedScript(
        language=profile.language,
        segments=script.segments,
        word_count=script.word_count,
        estimated_duration_seconds=script.estimated_duration_seconds,
        social_metadata=script.social_metadata,
        visuals=script.visuals,
        model=response.model,
        editorial_overlays=script.editorial_overlays,
    )


def validate_script_gate(
    script: GeneratedScript,
    *,
    claims: Sequence[Claim],
    profile: ContentProfile,
    min_segments: int,
    max_segments: int,
    hook_max_seconds: float,
    lead_in_seconds: float,
    tail_seconds: float,
) -> None:
    issues: list[str] = []
    details: list[str] = []
    if not min_segments <= len(script.segments) <= max_segments:
        issues.append("script_segment_count")
    accepted = {claim.id: claim for claim in claims if claim.status == ClaimStatus.ACCEPTED}
    for segment in script.segments:
        if not segment.claim_ids:
            issues.append("segment_ungrounded")
        if any(claim_id not in accepted for claim_id in segment.claim_ids):
            issues.append("unknown_claim")
        requires_attribution = any(
            _requires_attribution(accepted[claim_id]) for claim_id in segment.claim_ids if claim_id in accepted
        )
        if requires_attribution and not segment.attribution:
            issues.append("missing_attribution")
            details.append(
                f"segment {segment.index} cites a single-source or attributed Claim but its attribution field "
                "is empty; set it to the Claim's publisher and credit that publisher in the narration"
            )
    if script.segments and script.segments[0].estimated_duration_seconds > hook_max_seconds:
        issues.append("hook_too_long")
        details.append(
            f"segment 0 (hook) has {len(script.segments[0].text.split())} words; "
            f"keep it within {int(hook_max_seconds * profile.voice.words_per_minute / 60)} words"
        )
    if not script.segments or not script.segments[0].claim_ids:
        issues.append("hook_ungrounded")
    duration = script.estimated_duration_seconds + lead_in_seconds + tail_seconds
    if duration < profile.duration.min_seconds:
        issues.append("script_too_short")
        details.append(f"narration has {script.word_count} words; it is too short for the minimum duration")
    if duration > profile.duration.max_seconds:
        issues.append("script_too_long")
        details.append(f"narration has {script.word_count} words; it is too long for the maximum duration")
    if any(re.search(r"https?://|www\.|\[[^]]+\]\([^)]*\)|<[^>]+>", segment.text) for segment in script.segments):
        issues.append("forbidden_content")
    if issues:
        raise ScriptGateError(list(dict.fromkeys(issues)), "; ".join(details))


def _attribution_from_narration(script: GeneratedScript, publishers: Mapping[UUID, Sequence[str]]) -> GeneratedScript:
    """Record an omitted attribution field when the narration already credits a cited Claim's publisher."""
    segments = []
    for segment in script.segments:
        if not segment.attribution:
            named = next(
                (
                    publisher
                    for claim_id in segment.claim_ids
                    for publisher in publishers.get(claim_id, ())
                    if publisher and publisher.casefold() in segment.text.casefold()
                ),
                None,
            )
            segment = replace(segment, attribution=named) if named else segment
        segments.append(segment)
    return replace(script, segments=tuple(segments))


def _requires_attribution(claim: Claim) -> bool:
    return claim.support_level == SupportLevel.SINGLE_SOURCE or claim.kind == ClaimKind.STATEMENT_ATTRIBUTED


def _build_script(
    response: WriteScriptResult,
    profile: ContentProfile,
    lead_in: float,
    tail: float,
) -> GeneratedScript:
    segments = tuple(
        ScriptSegment(
            index,
            segment.text,
            tuple(segment.claim_ids),
            segment.attribution,
            len(segment.text.split()) * 60 / profile.voice.words_per_minute,
            segment.purpose,
        )
        for index, segment in enumerate(response.segments)
    )
    words = sum(len(segment.text.split()) for segment in response.segments)
    duration = words * 60 / profile.voice.words_per_minute + lead_in + tail
    return GeneratedScript(
        profile.language,
        segments,
        words,
        duration,
        response.social_metadata,
        tuple(response.visuals),
        "pending",
        tuple(response.editorial_overlays),
    )
