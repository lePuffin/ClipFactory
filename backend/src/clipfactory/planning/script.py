"""Grounded script generation request, output schema, and deterministic gate."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import ceil, floor
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clipfactory.assets.selection import narration_keywords
from clipfactory.domain.graphics import (
    GraphicsError,
    GraphicsSpec,
    VisualKind,
    graphics_kind,
    validate_graphics_claims,
    validate_graphics_kind,
)
from clipfactory.domain.models import Claim, ClaimKind, ClaimStatus, ContentProfile, SupportLevel
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMMessage, LLMProvider

logger = logging.getLogger(__name__)


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
    generation_prompt: str | None = Field(default=None, min_length=1, max_length=2000)
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

    @field_validator("generation_prompt")
    @classmethod
    def concrete_generation_prompt(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("generation prompt must not be blank")
        return value

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
        if self.graphics_spec is not None:
            if self.kind == "media" and self.fallback_graphics_spec is None:
                self.fallback_graphics_spec, self.graphics_spec = self.graphics_spec, None
            elif self.kind != "media":
                self.kind = graphics_kind(self.graphics_spec)
                self.fallback_graphics_spec = None
        elif self.kind != "media":
            self.kind = "media"
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


class PersonDraft(BaseModel):
    """A real person named in the narration (CF-REQ-268)."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    mentions: list[str] = Field(default_factory=list)


class BuzzLineDraft(BaseModel):
    """A punchy Claim-grounded context summary shown in the top panel from a segment onward (CF-REQ-269)."""

    model_config = ConfigDict(extra="forbid")
    segment_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    claim_ids: list[UUID] = Field(min_length=1)


BUZZ_LINE_MAX_CHARS = 48
BUZZ_LINE_MAX_WORDS = 8


class WriteScriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[ScriptSegmentDraft] = Field(min_length=1)
    social_metadata: SocialMetadataDraft
    visuals: list[VisualDraft] = Field(min_length=1)
    editorial_overlays: list[EditorialDraft] = Field(default_factory=list, max_length=8)
    people: list[PersonDraft] = Field(default_factory=list)
    buzz_lines: list[BuzzLineDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_visual_coverage(self) -> Self:
        if len(self.visuals) < len(self.segments):
            # Free writers sometimes stop the visual list early; a narration-derived media Visual is a deterministic,
            # reviewable fallback instead of discarding the whole Script (CF-REQ-250).
            template = self.visuals[-1]
            self.visuals = [
                *self.visuals,
                *(
                    VisualDraft(
                        objective="Illustrate what this segment says",
                        media_type="any",
                        category=template.category,
                        description=" ".join(segment.text.split()[:16]),
                        tags=list(narration_keywords(segment.text, limit=4)),
                    )
                    for segment in self.segments[len(self.visuals) :]
                ),
            ]
        if any(cue.segment_index >= len(self.segments) for cue in self.editorial_overlays):
            raise ValueError("editorial overlay references an unknown Script Segment")
        return self


class NarrationCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    attribution: str | None


class BuzzLinesRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buzz_lines: list[BuzzLineDraft] = Field(min_length=1)


class NarrationRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrections: list[NarrationCorrection] = Field(min_length=1)


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
    people: tuple[PersonDraft, ...] = ()
    buzz_lines: tuple[BuzzLineDraft, ...] = ()


class ScriptGateError(ValueError):
    def __init__(self, codes: list[str], detail: str = "") -> None:
        super().__init__(", ".join(codes))
        self.codes = tuple(codes)
        self.detail = detail
        self.draft: WriteScriptResult | None = None


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
    prompt_version: str = "write_script.v3",
    revision_instructions: Sequence[str] = (),
    target_word_count: int | None = None,
    source_attributions: Sequence[str] = (),
    claim_publishers: Mapping[UUID, Sequence[str]] | None = None,
    previous_script: Mapping[str, object] | None = None,
    rejected_draft: WriteScriptResult | None = None,
    rejected_codes: Sequence[str] = (),
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
    framing = "square"
    if profile.output.height > profile.output.width:
        framing = "portrait (vertical)"
    elif profile.output.width > profile.output.height:
        framing = "landscape (horizontal)"
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
            "Use infographic for statistic/comparison/timeline/key_date and scientific for "
            "function_plot/relationship_diagram. Illustrate one specific date with a key_date infographic whose "
            "date text is verbatim from an accepted Claim, never with a stock calendar photograph. "
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
            "Claim's listed publishers. Name each publisher at most once across the entire narration "
            "(e.g. 'according to <publisher>'); do not repeat that credit in later segments. "
            "Keep attribution fields on every required segment even when the spoken credit occurred earlier. "
            "social_metadata.description is the post caption: two to four sentences summarising the key "
            "accepted facts and why they matter, ending with an invitation to follow for more news. "
            "social_metadata.hashtags are three to eight specific discovery tags without spaces for the "
            "people, places, organisations and topic of the Story. "
            "Use a modern news-explainer structure: grounded hook, context, evidence, why it matters, "
            "uncertainty and conclusion. "
            "The narration never asks viewers to follow, subscribe, like, share or stay tuned, never mentions "
            "a channel or page, and never promises future updates; a separate branded end card does that. "
            "End the narration on a factual conclusion. "
            "Narration is spoken news copy only: never describe camera moves, shots, what appears on screen, "
            "lighting or crowd atmosphere, and never tell viewers to watch; visuals belong only in media fields. "
            "Record each segment's purpose. Keep narration coherent and avoid repeating the same claim to fill time. "
            "Stay on the selected Story; unrelated entries from a rolling live blog are not part of this Clip. "
            "Spell supported numbers, currency and abbreviations naturally for speech instead of digits, "
            "currency symbols or typographic hyphens. Preserve the exact factual value. "
            "Return concise editorial_overlays for headline/place/source/key-number context, "
            "bound to segment_index and accepted claim_ids. "
            "Use real specific subjects/tags for search, not sentences such as 'visual representation of'. "
            "Media descriptions must be ordinary photographable scenes that free stock libraries plausibly hold "
            "(places, crowds, buildings, objects, activities); never request on-screen text, tables, scoreboards, "
            "specific numbers, logos or screenshots as media. Data belongs in a graphics_spec. "
            "For every eligible illustrative media shot, including reuse_first shots that may need generation, "
            "set generation_prompt separately from the search description: "
            "describe a concrete moving scene, subject/action, environment, lighting, framing and camera motion. "
            "Specify recognizable physical subject details and stable subject geometry throughout the shot, "
            "with restrained, believable motion and one continuous shot; avoid unnecessary camera movement. "
            f"Compose for {framing} "
            "framing, keeping the main subject clearly visible with room for captions. "
            "Use realistic live-action cinematography, not cartoons, renders, diagrams, maps or invented footage. "
            "Never put policy/disclosure instructions in generation_prompt; provenance handles disclosure. "
            "Never introduce depicted real people or unsupported factual detail. "
            "Every spoken sentence must state something an accepted Claim says, mostly in the Claim's own words; "
            "never add commentary about what observers, analysts or critics think, what an event underscores, "
            "highlights or signals, or invented setting such as when, where or how something was said. "
            "Mix relevant photos, maps and B-roll with media_type any where either works. "
            "Script motion and transitions separately for each shot according to its narration and subject. "
            "Record the editorial reason in motion_reason. Use none for reading-focused graphics and native video; "
            "only use pans or zooms to guide attention to the concrete subject. Cuts are the default; "
            "use a transition only for a motivated change of time, place or viewpoint. Avoid repeated zooms. "
            "List in people every real, named person spoken in the narration (politicians, leaders, celebrities, "
            "officials), with the full canonical name and the exact forms spoken in narration as mentions "
            "(e.g. name 'Volodymyr Zelenskyy', mentions ['Zelensky']). Their verified real photos are shown "
            "on mention automatically; do not describe them in generation_prompt. "
            "Return buzz_lines: short punchy uppercase-ready context banners kept on screen so viewers know "
            "what the story is about, like a gossip headline (e.g. 'Zelensky disagrees with Trump's decision!'). "
            f"Each has at most {BUZZ_LINE_MAX_WORDS} words and {BUZZ_LINE_MAX_CHARS} characters, a segment_index "
            "where it starts (the first must be 0), and accepted claim_ids supporting it; at most one per segment, "
            "two to four in total. Emphatic wording is fine, but never state anything the Claims do not support. "
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
                "name each publisher at most once in the entire narration, not in every segment. "
                "Put URLs only in metadata, never narration. " + json.dumps(source_attributions),
            )
        )
    if rejected_draft is not None:
        previous_script = rejected_draft.model_dump(mode="json")
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
                "credits at most once per publisher across the entire narration when shortening the hook. "
                "Remove repeated spoken credits, not the structured attribution fields. "
                "Keep the hook within its word limit when adding credits. "
                "Do not trade one gate failure for another. Count the final hook and total narration before replying.",
            )
        )
    narration_codes = {
        "hook_too_long",
        "script_too_short",
        "script_too_long",
        "missing_attribution",
        "repeated_attribution",
        "repeated_sentence",
        "spoken_call_to_action",
        "filler_padding",
        "stage_direction",
        "unsupported_commentary",
        "headline_fragment",
        "forbidden_content",
    }
    if rejected_draft is not None and rejected_codes and set(rejected_codes) <= narration_codes:
        editable = set(range(len(rejected_draft.segments)))
        if set(rejected_codes) == {"hook_too_long"}:
            editable = {0}
        elif set(rejected_codes) <= {"script_too_short", "script_too_long"}:
            editable.discard(0)
        repair_messages = [
            LLMMessage(
                "system",
                f"Correct only the requested narration defects in {profile.language}. "
                "Return indexed corrections only, not a complete script or any visuals. "
                f"Editable segment indexes: {sorted(editable)}. "
                f"The hook must have at most {int(hook_max_seconds * words_per_minute / 60)} words; "
                f"target at most {max(1, int(hook_max_seconds * words_per_minute / 60) - 2)} to leave margin. "
                f"The complete narration must contain {minimum_words} to {maximum_words} words. "
                "Preserve factual meaning and do not invent facts or add unsupported commentary such as what "
                "observers, analysts or critics think, what it underscores or signals, or where an event happened, "
                "unless an accepted Claim says so. "
                "Never speak the same sentence twice; replace a repeated sentence with a different accepted fact. "
                "Lengthen narration only with another accepted fact or necessary context, never with filler "
                "adverbs such as notably, remarkably, impressively or truly. "
                "Keep each publisher's attribution field when required, but speak each publisher at most once "
                "across the whole narration. Attribution fields are not spoken narration. "
                "Count words before returning; use plain spoken text, no URLs, markup or emoji. "
                "Claim IDs, purpose, metadata and visuals are immutable and must not appear in the response. "
                "Prompt version: repair_narration.v1.",
            ),
            messages[1],
            LLMMessage(
                "user",
                "Corrections required: "
                + "; ".join(revision_instructions)
                + "\n<untrusted-rejected-narration>\n"
                + json.dumps(
                    [segment.model_dump(mode="json") for segment in rejected_draft.segments], ensure_ascii=False
                )
                + "\n</untrusted-rejected-narration>",
            ),
        ]
        repaired = await provider.generate_structured("write_script", repair_messages, NarrationRepairResult)
        indexes = [correction.segment_index for correction in repaired.value.corrections]
        if len(indexes) != len(set(indexes)) or not set(indexes) <= editable:
            error = ScriptGateError(
                list(rejected_codes),
                "Narration correction has duplicate or out-of-scope indexes; the original defects remain",
            )
            error.draft = rejected_draft
            raise error
        segments = list(rejected_draft.segments)
        for correction in repaired.value.corrections:
            original = segments[correction.segment_index]
            segments[correction.segment_index] = original.model_copy(
                update={"text": correction.text, "attribution": correction.attribution}
            )
        draft = rejected_draft.model_copy(update={"segments": segments})
        model = repaired.model
    else:
        try:
            response = await provider.generate_structured("write_script", messages, WriteScriptResult)
        except ProviderError as exc:
            if exc.code != "unsupported_statement":
                raise
            # Invalid typed graphics in the response are a stage-gate rewrite, not a Run failure (CF-REQ-263).
            raise ScriptGateError(
                ["unsupported_statement"],
                f"{exc} Graphics labels must be short plain phrases copied verbatim from the referenced accepted "
                "Claim; otherwise use kind media for that visual.",
            ) from exc
        draft = response.value
        model = response.model
    if any(not set(cue.claim_ids) <= allowed_ids for cue in draft.editorial_overlays):
        error = ScriptGateError(["unknown_claim"])
        error.draft = draft
        raise error
    if len(draft.visuals) < len(draft.segments):
        raise ValueError("visual plan draft must include at least one Visual Segment per Script Segment")
    script = _build_script(draft, profile, lead_in_seconds, tail_seconds)
    for index, visual in enumerate(script.visuals):
        for spec in (visual.graphics_spec, visual.fallback_graphics_spec):
            if spec is None:
                continue
            try:
                validate_graphics_claims(spec, accepted)
            except GraphicsError as exc:
                if exc.code != "unsupported_statement":
                    raise
                error = ScriptGateError(
                    ["unsupported_statement"],
                    f"Visual {index} graphics is not grounded ({exc}). Every graphics label must be a short phrase "
                    "copied verbatim from its referenced accepted Claim, and each value must follow its label in "
                    "that Claim; otherwise use kind media for that visual.",
                )
                error.draft = draft
                raise error from exc
    script = _attribution_from_narration(script, publishers)
    if any(
        original.attribution != normalized.attribution
        for original, normalized in zip(draft.segments, script.segments, strict=True)
    ):
        draft = draft.model_copy(
            update={
                "segments": [
                    original.model_copy(update={"attribution": normalized.attribution})
                    for original, normalized in zip(draft.segments, script.segments, strict=True)
                ]
            }
        )
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
    try:
        validate_script_gate(
            script,
            claims=accepted,
            profile=profile,
            min_segments=min_segments,
            max_segments=max_segments,
            hook_max_seconds=hook_max_seconds,
            lead_in_seconds=lead_in_seconds,
            tail_seconds=tail_seconds,
            claim_publishers=publishers,
        )
    except ScriptGateError as exc:
        exc.draft = draft
        raise
    return GeneratedScript(
        language=profile.language,
        segments=script.segments,
        word_count=script.word_count,
        estimated_duration_seconds=script.estimated_duration_seconds,
        social_metadata=script.social_metadata,
        visuals=script.visuals,
        model=model,
        editorial_overlays=script.editorial_overlays,
        people=normalize_people(draft.people, script.segments),
        buzz_lines=await _buzz_lines_with_repair(
            provider, draft.buzz_lines, script.segments, allowed_ids, script.social_metadata.title, messages[1]
        ),
    )


async def _buzz_lines_with_repair(
    provider: LLMProvider,
    lines: Sequence[BuzzLineDraft],
    segments: Sequence[ScriptSegment],
    allowed_ids: set[UUID],
    title: str,
    claims_message: LLMMessage,
) -> tuple[BuzzLineDraft, ...]:
    """Ask once for missing context summaries when fewer than two grounded lines survive (CF-REQ-269)."""
    drops: list[str] = []
    kept = normalize_buzz_lines(lines, segments, allowed_ids, None, drops=drops)
    if len(segments) < 2 or len(kept) >= 2:
        return normalize_buzz_lines(kept, segments, allowed_ids, title)
    messages = [
        LLMMessage(
            "system",
            "Write buzz_lines: punchy context summaries shown in a top panel so viewers always know what the "
            "story is about, like a gossip headline (e.g. 'Zelensky disagrees with Trump's decision!'). "
            f"Return two to four lines, each at most {BUZZ_LINE_MAX_WORDS} words and {BUZZ_LINE_MAX_CHARS} "
            "characters (count them), at most one per segment_index, the first at segment 0, each with the "
            "accepted claim_ids that support it. Summarize what is happening, not a label or a publisher name. "
            "Never state anything the Claims do not support. Plain text, no URLs, Markdown or emoji. "
            "Prompt version: repair_buzz_lines.v1.",
        ),
        claims_message,
        LLMMessage(
            "user",
            "<untrusted-narration>\n"
            + json.dumps(
                [
                    {
                        "segment_index": segment.index,
                        "text": segment.text,
                        "claim_ids": [str(c) for c in segment.claim_ids],
                    }
                    for segment in segments
                ],
                ensure_ascii=False,
            )
            + "\n</untrusted-narration>\nRejected lines: "
            + ("; ".join(drops) or "none were returned"),
        ),
    ]
    try:
        repaired = await provider.generate_structured("write_script", messages, BuzzLinesRepairResult)
    except (ProviderError, ValueError) as exc:
        logger.warning("Buzz line repair failed: %s", exc)
        return normalize_buzz_lines(kept, segments, allowed_ids, title)
    taken = {line.segment_index for line in kept}
    extra = [line for line in repaired.value.buzz_lines if line.segment_index not in taken]
    return normalize_buzz_lines([*kept, *extra], segments, allowed_ids, title)


def normalize_people(people: Sequence[PersonDraft], segments: Sequence[ScriptSegment]) -> tuple[PersonDraft, ...]:
    """Keep up to eight distinct declared people actually spoken in narration (CF-REQ-268)."""
    from clipfactory.planning.people import mentions_in, person_aliases

    narration = " ".join(segment.text for segment in segments)
    kept: list[PersonDraft] = []
    seen: set[str] = set()
    for person in people:
        name = " ".join(person.name.split())
        key = name.casefold()
        if not name or key in seen:
            continue
        mentions = list(dict.fromkeys(" ".join(item.split()) for item in person.mentions if item.strip()))[:6]
        candidate = PersonDraft(name=name, mentions=mentions)
        if not mentions_in(narration, person_aliases(candidate)):
            continue
        seen.add(key)
        kept.append(candidate)
        if len(kept) == 8:
            break
    return tuple(kept)


def normalize_buzz_lines(
    lines: Sequence[BuzzLineDraft],
    segments: Sequence[ScriptSegment],
    allowed_ids: set[UUID],
    title: str | None,
    *,
    drops: list[str] | None = None,
) -> tuple[BuzzLineDraft, ...]:
    """Keep grounded, bounded buzz lines (one per segment) and guarantee an opening line (CF-REQ-269)."""
    by_segment: dict[int, BuzzLineDraft] = {}
    for line in lines:
        text = " ".join(line.text.split())
        claims = [claim_id for claim_id in line.claim_ids if claim_id in allowed_ids]
        reason = (
            "empty"
            if not text
            else "no accepted claim"
            if not claims
            else "unknown segment"
            if line.segment_index >= len(segments)
            else "duplicate segment"
            if line.segment_index in by_segment
            else "too long"
            if len(text) > BUZZ_LINE_MAX_CHARS or len(text.split()) > BUZZ_LINE_MAX_WORDS
            else None
        )
        if reason:
            logger.warning("Buzz line %r for segment %d dropped: %s", text, line.segment_index, reason)
            if drops is not None:
                drops.append(f"{text!r} (segment {line.segment_index}): {reason}")
            continue
        by_segment[line.segment_index] = BuzzLineDraft(segment_index=line.segment_index, text=text, claim_ids=claims)
    if title is not None and 0 not in by_segment and segments and segments[0].claim_ids:
        fallback = _title_buzz_line(" ".join(title.split()))
        if fallback:
            by_segment[0] = BuzzLineDraft(segment_index=0, text=fallback, claim_ids=list(segments[0].claim_ids))
    return tuple(by_segment[index] for index in sorted(by_segment))[:8]


def _fits_buzz_line(text: str) -> bool:
    return len(text) <= BUZZ_LINE_MAX_CHARS and len(text.split()) <= BUZZ_LINE_MAX_WORDS


def _title_buzz_line(title: str) -> str:
    if _fits_buzz_line(title):
        return title.rstrip(",;:-|\u2013 ")
    clause = re.split(":| - | \u2013 | \\| ", title, maxsplit=1)[0].strip()
    if clause != title and len(clause.split()) >= 2 and _fits_buzz_line(clause):
        return clause
    return _shorten_words(title, BUZZ_LINE_MAX_CHARS, BUZZ_LINE_MAX_WORDS)


def _shorten_words(text: str, max_chars: int, max_words: int) -> str:
    words: list[str] = []
    for word in text.split()[:max_words]:
        if len(" ".join([*words, word])) > max_chars:
            break
        words.append(word)
    return " ".join(words).rstrip(",;:-")


_MIN_REPEATED_SENTENCE_WORDS = 5
_MIN_RESTATED_CONTENT_WORDS = 4
_RESTATEMENT_CONTAINMENT = 0.65
_ABSORBED_MIN_CONTENT_WORDS = 5
_ABSORBED_CONTAINMENT = 0.8
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "he",
        "she",
        "they",
        "them",
        "his",
        "her",
        "their",
        "him",
        "who",
        "whom",
        "which",
        "what",
        "when",
        "where",
        "while",
        "than",
        "then",
        "so",
        "not",
        "no",
        "nor",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "about",
        "into",
        "over",
        "under",
        "after",
        "before",
        "also",
        "only",
        "just",
        "very",
        "more",
        "most",
        "such",
        "other",
        "there",
        "here",
        "we",
        "our",
        "you",
        "your",
        "i",
        "me",
        "my",
        "us",
        "says",
        "said",
        "say",
        "according",
        "both",
        "any",
        "each",
        "ask",
        "asked",
        "asks",
        "told",
        "tells",
    ]
)
_ORDINALS = {
    "first": "1",
    "second": "2",
    "third": "3",
    "fourth": "4",
    "fifth": "5",
    "sixth": "6",
    "seventh": "7",
    "eighth": "8",
    "ninth": "9",
    "tenth": "10",
}
_SUFFIXES = ("ations", "ation", "ions", "ion", "ings", "ing", "ers", "er", "ies", "ied", "es", "ed", "s")


def _content_words(sentence: str) -> set[str]:
    words: set[str] = set()
    for token in re.findall(r"[^\W_]+", sentence.casefold()):
        if token in _STOPWORDS:
            continue
        word = _ORDINALS.get(str(token), str(token))
        for suffix in _SUFFIXES:
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        words.add(word)
    return words


def _shared_stems(words: set[str], previous: set[str]) -> int:
    """Count words also in ``previous``, letting a 5+ letter stem prefix another (reduc/reduct)."""
    return sum(
        1
        for word in words
        if word in previous
        or any(
            min(len(word), len(other)) >= 5 and (word.startswith(other) or other.startswith(word)) for other in previous
        )
    )


_CALL_TO_ACTION = re.compile(
    r"\b(?:follow|subscribe)(?:\s+(?:to|now|today))?\s+(?:us|me|our|along|for\s+(?:more|daily|updates|the\s+latest))\b"
    r"|\b(?:please|be\s+sure\s+to|make\s+sure\s+to|don'?t\s+forget\s+to)\s+(?:follow|subscribe|like|share|comment)\b"
    r"|\b(?:like\s+and\s+(?:share|subscribe|follow)|hit\s+the\s+bell|turn\s+on\s+notifications|stay\s+tuned"
    r"|comment\s+below|let\s+us\s+know\s+in\s+the\s+comments)\b"
    r"|\b(?:our|my)\s+(?:channel|page|feed|account)\b|\bthis\s+channel\b"
    r"|\b(?:viewers|the\s+audience|listeners|our\s+followers)\s+(?:are|is)\s+(?:invited|encouraged|urged|asked|welcome)"
    r"\s+to\b|\b(?:submit|send)\s+(?:your\s+)?questions\b"
    r"|\bwe(?:'ll|\s+will)\s+(?:continue\s+to\s+|keep\s+)?(?:monitor|report|bring\s+you|update|keep\s+you)",
    re.IGNORECASE,
)


_FILLER_ADVERB = re.compile(
    r"\b(?:notably|remarkably|noticeably|impressively|truly|incredibly|undeniably|strikingly|stunningly"
    r"|astonishingly|amazingly|interestingly|importantly|clearly)\b",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"[\"\u201c][^\"\u201d]*[\"\u201d]")


def filler_padded_sentences(sentences: Sequence[str]) -> list[str]:
    """Return sentences padded with empty intensifiers, or all of them when the narration overuses them."""
    counts = [len(_FILLER_ADVERB.findall(_QUOTED.sub(" ", sentence))) for sentence in sentences]
    if sum(counts) >= 4:
        return [sentence for sentence, count in zip(sentences, counts, strict=True) if count]
    return [sentence for sentence, count in zip(sentences, counts, strict=True) if count >= 2]


_STAGE_DIRECTION = re.compile(
    r"\bcamera\s+(?:pulls?|pans?|zooms?|cuts?|tracks?|moves?|follows?|lingers?|focuses|tilts?|sweeps?|holds?)\b"
    r"|\b(?:final|opening|closing|wide|establishing|aerial|next|last|first)\s+shots?\b"
    r"|\bclose[- ]?ups?\b|\bshots?\s+(?:lingers?|holds?|pans?|shows?|cuts?)\b"
    r"|\bcut\s+to\b|\bfades?\s+(?:in|out|to)\b|\bwatch\s+(?:the\s+action|as|closely)\b|\bwe\s+see\b"
    r"|\bon[- ]screen\b|\bb[- ]roll\b|\b(?:footage|visuals?|the\s+scene)\s+(?:shows?|cuts?|opens?|pans?)\b"
    r"|\bunder\s+(?:the\s+)?(?:bright|dim|soft|warm|harsh|glowing|overhead)\s+(?:\w+\s+)?(?:lights?|lighting)\b"
    r"|\bappears?\s+(?:in|on)\s+(?:the\s+)?(?:crowd|frame|screen|background|foreground)\b"
    r"|\b(?:crowd|audience|supporters|fans)\s+(?:chants|cheers|roars|applauds|claps|erupts)\b",
    re.IGNORECASE,
)


_UNSUPPORTED_COMMENTARY_MIN_WORDS = 3
_UNSUPPORTED_COMMENTARY_SUPPORT = 0.3
_UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _number_words(value: int) -> list[str]:
    if value < 20:
        return [_UNITS[value]]
    if value < 100:
        return [_TENS[value // 10]] + ([_UNITS[value % 10]] if value % 10 else [])
    for size, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand"), (100, "hundred")):
        if value >= size:
            rest = value % size
            return [*_number_words(value // size), name] + (_number_words(rest) if rest else [])
    return []


def _evidence_words(texts: Sequence[str]) -> set[str]:
    """Content words of the evidence, with digits also in their spoken form (46 -> forty six)."""
    words: set[str] = set()
    for text in texts:
        words |= _content_words(text)
        for digits in re.findall(r"\d+", re.sub(r"(?<=\d),(?=\d{3})", "", text)):
            if len(digits) <= 12:
                value = int(digits)
                words |= _content_words(" ".join(_number_words(value)))
                if 1000 < value < 10000:
                    # Years are spoken in pairs: 2026 -> twenty twenty-six.
                    words |= _content_words(" ".join(_number_words(value // 100) + _number_words(value % 100)))
    return words


def unsupported_commentary(sentences: Sequence[str], evidence: Sequence[str]) -> list[str]:
    """Return sentences whose content words are mostly absent from the evidence (CF-REQ-158).

    Generic padding such as "Observers view this as a notable shift" or invented context such as
    "The warning emerged during a public briefing" shares almost no words with any accepted Claim.
    """
    known = _evidence_words(evidence)
    flagged: list[str] = []
    for sentence in sentences:
        words = _content_words(sentence)
        if len(words) < _UNSUPPORTED_COMMENTARY_MIN_WORDS:
            continue
        if _shared_stems(words, known) / len(words) < _UNSUPPORTED_COMMENTARY_SUPPORT:
            flagged.append(sentence)
    return flagged


def spoken_stage_directions(sentences: Sequence[str]) -> list[str]:
    """Return narration sentences that describe camera, shots or on-screen scenery (CF-REQ-158)."""
    return [sentence for sentence in sentences if _STAGE_DIRECTION.search(_QUOTED.sub(" ", sentence))]


def spoken_calls_to_action(sentences: Sequence[str]) -> list[str]:
    """Return narration sentences that ask the viewer to follow/subscribe (CF-REQ-158, CF-REQ-165)."""
    return [sentence for sentence in sentences if _CALL_TO_ACTION.search(sentence.replace("\u2019", "'"))]


_SENTENCE_END = re.compile(r"[.!?\u2026][\"'\u201d\u2019)\]]*$")


_FIRST_WORD = re.compile(r"[^\W\d_][\w\u2019'-]*")


def headline_fragment(text: str) -> bool:
    """Return whether spoken segment text is not one complete sentence (CF-REQ-158).

    Flags text without sentence-final punctuation and text opening with an all-lowercase word,
    the tail of a source sentence whose start was cut away.
    """
    stripped = text.strip()
    if not stripped:
        return False
    first = _FIRST_WORD.search(stripped)
    return not _SENTENCE_END.search(stripped) or (first is not None and first.group().islower())


def restated_sentences(
    sentences: Sequence[str], *, segment_indexes: Sequence[int] | None = None
) -> list[tuple[str, str]]:
    """Return (restatement, earlier passage) pairs for paraphrased repeats (CF-REQ-158).

    With ``segment_indexes`` (the script segment of each sentence), a sentence is also compared
    with the combined text of every earlier segment.
    """
    pairs: list[tuple[str, str]] = []
    earlier: list[tuple[str, set[str]]] = []
    segments: dict[int, tuple[list[str], set[str]]] = {}
    for position, sentence in enumerate(sentences):
        words = _content_words(sentence)
        segment = segment_indexes[position] if segment_indexes is not None else None
        candidates = list(earlier)
        candidates += [
            (" ".join(texts), segment_words)
            for index, (texts, segment_words) in segments.items()
            if segment is not None and index < segment and len(texts) > 1
        ]
        if len(words) >= _MIN_RESTATED_CONTENT_WORDS:
            for previous, previous_words in candidates:
                if sentence.casefold() == previous.casefold():
                    continue
                if _shared_stems(words, previous_words) / len(words) >= _RESTATEMENT_CONTAINMENT:
                    pairs.append((sentence, previous))
                    break
            else:
                absorbed = _absorbed_sentence(words, earlier[: max(position - 1, 0)])
                if absorbed is not None:
                    pairs.append((sentence, absorbed))
        earlier.append((sentence, words))
        if segment is not None:
            texts, segment_words = segments.setdefault(segment, ([], set()))
            texts.append(sentence)
            segment_words.update(words)
    return pairs


def _absorbed_sentence(words: set[str], earlier: Sequence[tuple[str, set[str]]]) -> str | None:
    """Return a non-adjacent earlier sentence whose content a longer later sentence repeats."""
    for previous, previous_words in earlier:
        if len(previous_words) < _ABSORBED_MIN_CONTENT_WORDS:
            continue
        if _shared_stems(previous_words, words) / len(previous_words) >= _ABSORBED_CONTAINMENT:
            return previous
    return None


_CLAIM_RESTATEMENT_MIN_WORDS = 3
_CLAIM_RESTATEMENT_CONTAINMENT = 0.6
_CLAIM_RESTATEMENT_MAX_NEW_WORDS = 1


def _covered_words(words: set[str], claim_words: set[str]) -> set[str]:
    return {
        word
        for word in words
        if word in claim_words
        or any(
            min(len(word), len(other)) >= 5 and (word.startswith(other) or other.startswith(word))
            for other in claim_words
        )
    }


def claim_restated_sentences(sentences: Sequence[str], evidence: Sequence[str]) -> list[tuple[str, str]]:
    """Return (restatement, earlier sentence) pairs that re-tell the same accepted Claim (CF-REQ-158).

    Each sentence is grounded to the Claim whose words it covers most. A later sentence is a
    restatement when it maps to the same Claim as an earlier non-opening sentence, at least 60 % of
    its Claim words were already covered by that sentence, and it adds at most one Claim word not yet
    spoken for that Claim. This catches synonym paraphrases ("a large victory" for "win by massive
    numbers") that share too few words for :func:`restated_sentences`. The opening sentence is
    exempt as an earlier passage because the hook headline is normally elaborated next.
    """
    claim_words = [_evidence_words([text]) for text in evidence]
    if not claim_words:
        return []
    pairs: list[tuple[str, str]] = []
    history: list[tuple[str, int, set[str]]] = []
    spoken_for_claim: dict[int, set[str]] = {}
    for sentence in sentences:
        words = _content_words(sentence)
        if not words:
            continue
        best = max(range(len(claim_words)), key=lambda index: len(_covered_words(words, claim_words[index])))
        covered = _covered_words(words, claim_words[best])
        if len(covered) >= _CLAIM_RESTATEMENT_MIN_WORDS and len(covered - spoken_for_claim.get(best, set())) <= (
            _CLAIM_RESTATEMENT_MAX_NEW_WORDS
        ):
            for previous_position, (previous, claim, previous_covered) in enumerate(history):
                if previous_position == 0 or claim != best or sentence.casefold() == previous.casefold():
                    continue
                if len(covered & previous_covered) / len(covered) >= _CLAIM_RESTATEMENT_CONTAINMENT:
                    pairs.append((sentence, previous))
                    break
        history.append((sentence, best, covered))
        spoken_for_claim.setdefault(best, set()).update(covered)
    return pairs


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
    claim_publishers: Mapping[UUID, Sequence[str]] | None = None,
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
                "is empty; set it to the Claim's publisher. Keep each publisher's spoken credit at most once "
                "across the entire narration, not once per segment"
            )
    publisher_names = {
        " ".join(name.split()).casefold().removeprefix("the ")
        for names in (claim_publishers or {}).values()
        for name in names
        if name.strip()
    }
    publisher_names.update(
        " ".join(segment.attribution.split()).casefold().removeprefix("the ")
        for segment in script.segments
        if segment.attribution and segment.attribution.strip()
    )
    publisher_names.discard("")
    narration = " ".join(" ".join(segment.text.split()) for segment in script.segments).casefold()
    if publisher_names:
        pattern = (
            r"(?<!\w)(?:"
            + "|".join(re.escape(name) for name in sorted(publisher_names, key=len, reverse=True))
            + r")(?!\w)"
        )
        mentions: dict[str, int] = {}
        for match in re.finditer(pattern, narration):
            name = match.group()
            mentions[name] = mentions.get(name, 0) + 1
        for name, count in mentions.items():
            if count > 1:
                issues.append("repeated_attribution")
                details.append(
                    f"publisher {name!r} is spoken {count} times; name it at most once across the entire narration. "
                    "Rewrite repeated credits while preserving factual meaning, Claim IDs and attribution fields"
                )
    sentence_counts: dict[str, int] = {}
    spoken_by_segment = [
        (position, sentence)
        for position, segment in enumerate(script.segments)
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(segment.text.split()))
        if sentence.strip()
    ]
    spoken = [sentence for _, sentence in spoken_by_segment]
    restatements = restated_sentences(spoken, segment_indexes=[position for position, _ in spoken_by_segment])
    for restatement, previous in restatements:
        issues.append("repeated_sentence")
        details.append(
            f"the sentence {restatement!r} restates the earlier passage {previous!r} in different words; delete "
            "the restatement or replace it with a different accepted fact"
        )
    for sentence in filler_padded_sentences(spoken):
        issues.append("filler_padding")
        details.append(
            f"the sentence {sentence!r} is padded with filler adverbs (notably, remarkably, impressively, truly, "
            "clearly…); remove them and, if more words are needed, add a different accepted fact"
        )
    for sentence in spoken_calls_to_action(spoken):
        issues.append("spoken_call_to_action")
        details.append(
            f"the sentence {sentence!r} asks the viewer to follow/subscribe or promises updates; the Clip's end "
            "card already does that, so delete the sentence or replace it with a different accepted fact"
        )
    evidence = [claim.text for claim in accepted.values()]
    already_restated = {restatement for restatement, _ in restatements}
    for restatement, previous in claim_restated_sentences(spoken, evidence):
        if restatement in already_restated:
            continue
        issues.append("repeated_sentence")
        details.append(
            f"the sentence {restatement!r} re-tells the same accepted Claim as the earlier sentence {previous!r} "
            "in different words; delete it or replace it with a different accepted fact"
        )
    evidence += [segment.attribution for segment in script.segments if segment.attribution]
    evidence += [name for names in (claim_publishers or {}).values() for name in names]
    for sentence in unsupported_commentary(spoken, evidence):
        issues.append("unsupported_commentary")
        details.append(
            f"the sentence {sentence!r} is commentary or context that no accepted Claim supports; delete it or "
            "replace it with a different accepted fact stated in the Claim's own words"
        )
    for sentence in spoken_stage_directions(spoken):
        issues.append("stage_direction")
        details.append(
            f"the sentence {sentence!r} is a director's note describing the camera, shots or on-screen scenery, "
            "not news narration; delete it or replace it with a different accepted fact. Visuals belong only in "
            "the media fields"
        )
    for segment in script.segments:
        if headline_fragment(segment.text):
            issues.append("headline_fragment")
            details.append(
                f"segment {segment.index} ({' '.join(segment.text.split())!r}) is a headline fragment, not a "
                "complete spoken sentence; rewrite it as one complete sentence ending with a full stop, without "
                "abbreviations such as 'govt', and do not repeat it in the following segments"
            )
    for sentence in re.split(r"(?<=[.!?])\s+", narration):
        normalized = " ".join(re.sub(r"[^\w\s]", " ", sentence).split())
        if len(normalized.split()) >= _MIN_REPEATED_SENTENCE_WORDS:
            sentence_counts[normalized] = sentence_counts.get(normalized, 0) + 1
    for sentence, count in sentence_counts.items():
        if count > 1:
            issues.append("repeated_sentence")
            details.append(
                f"the sentence {sentence!r} is spoken {count} times; say it at most once and replace each repeat "
                "with a different accepted fact instead of filler"
            )
    if script.segments and script.segments[0].estimated_duration_seconds > hook_max_seconds:
        issues.append("hook_too_long")
        details.append(
            f"segment 0 (hook) has {len(script.segments[0].text.split())} words; "
            f"keep it within {int(hook_max_seconds * profile.voice.words_per_minute / 60)} words"
        )
    if not script.segments or not script.segments[0].claim_ids:
        issues.append("hook_ungrounded")
    duration = script.estimated_duration_seconds
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
