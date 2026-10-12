"""Deterministic Visual Plan normalization from the write_script draft."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from clipfactory.assets.selection import narration_keywords
from clipfactory.domain.graphics import GroundedText, KeyDate
from clipfactory.domain.models import Claim, ClaimStatus
from clipfactory.planning.people import MIN_PIECE_WORDS, split_at_mentions
from clipfactory.planning.script import GeneratedScript, PersonDraft, VisualDraft


@dataclass(frozen=True, slots=True)
class VisualSegment:
    index: int
    script_segment_index: int
    narration_text: str
    objective: str
    requirement: dict[str, Any]
    planned_duration_seconds: float
    motion: str
    transition_in: str
    motion_reason: str = ""
    selected_asset_id: str | None = None
    selection_reason: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None


def build_visual_plan(
    script: GeneratedScript,
    *,
    allow_generated_media: bool,
    max_segment_seconds: float = 8.0,
) -> tuple[VisualSegment, ...]:
    if max_segment_seconds <= 0 or len(script.visuals) < len(script.segments):
        raise ValueError("visual draft cannot cover the Script")
    people = _plan_people(script)
    output: list[VisualSegment] = []
    for script_segment, draft in zip(script.segments, script.visuals, strict=False):
        total_words = max(1, len(script_segment.text.split()))
        pieces_of_segment: list[tuple[str, str | None, float, bool]] = []
        for person_text, person in _cap_portraits(split_at_mentions(script_segment.text, people)):
            piece_duration = script_segment.estimated_duration_seconds * len(person_text.split()) / total_words
            pieces = max(1, math.ceil(piece_duration / max_segment_seconds))
            text_parts = _split_words(person_text, pieces)
            for part_index, part in enumerate(text_parts):
                # CF-REQ-268: only the first piece of a split person piece shows the portrait.
                shown = person if part_index == 0 else None
                pieces_of_segment.append((part, shown, piece_duration / len(text_parts), part_index > 0))
        anchor = _graphic_anchor(pieces_of_segment, draft)
        for position, (part, person, duration, continuation) in enumerate(pieces_of_segment):
            segment = _normalize_segment(
                len(output),
                script_segment.index,
                part,
                duration,
                draft,
                allow_generated_media,
                continuation=continuation,
            )
            previous = output[-1].requirement.get("person") if output else None
            if person is not None and not (previous and previous.get("name") == person):
                segment = _person_segment(segment, person)
            elif draft.kind != "media" and position != anchor:
                segment = _footage_segment(segment)
            elif draft.fallback_graphics_spec is not None and position != anchor:
                segment = _without_fallback_graphic(segment)
            output.append(segment)
    distinct_media_searches([(segment.requirement, segment.narration_text) for segment in output])
    return tuple(output)


_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_DAY_WORDS = {
    word: day
    for day, word in enumerate(
        [
            "first",
            "second",
            "third",
            "fourth",
            "fifth",
            "sixth",
            "seventh",
            "eighth",
            "ninth",
            "tenth",
            "eleventh",
            "twelfth",
            "thirteenth",
            "fourteenth",
            "fifteenth",
            "sixteenth",
            "seventeenth",
            "eighteenth",
            "nineteenth",
            "twentieth",
        ],
        start=1,
    )
}
_MONTH = r"(?P<{name}>January|February|March|April|May|June|July|August|September|October|November|December|" + (
    r"Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)"
)
_DAY = r"(?P<{name}>(?:[12]\d|3[01]|0?[1-9])(?:st|nd|rd|th)?|" + "|".join(_DAY_WORDS) + ")"
_YEAR = r"(?:,?\s+(?:19|20)\d\d)?"
_DATE = re.compile(
    rf"(?<!\w)(?:{_MONTH.format(name='m1')}\s+{_DAY.format(name='d1')}{_YEAR}"
    rf"|{_DAY.format(name='d2')}\s+(?:of\s+)?{_MONTH.format(name='m2')}{_YEAR})(?![\w-])",
)
_CALENDAR_INTENT = re.compile(r"\b(?:calendars?|dates?)\b", re.IGNORECASE)


def _date_key(match: re.Match[str]) -> tuple[int, int]:
    month_text = (match["m1"] or match["m2"]).rstrip(".").casefold()
    month = next(index for index, name in enumerate(_MONTH_NAMES, 1) if name.casefold().startswith(month_text[:3]))
    day_text = (match["d1"] or match["d2"]).casefold()
    day = _DAY_WORDS.get(day_text) or int(re.sub(r"\D", "", day_text))
    return month, day


def with_date_cards(
    script: GeneratedScript, claims: Sequence[Claim], *, allow_generated_media: bool
) -> GeneratedScript:
    """Replace calendar/date stock-media requests with a grounded key_date card (CF-REQ-251, CF-REQ-263)."""
    if not allow_generated_media:
        return script
    accepted = [claim for claim in claims if claim.status == ClaimStatus.ACCEPTED]
    visuals = list(script.visuals)
    for segment, draft in zip(script.segments, script.visuals, strict=False):
        intent = " ".join([draft.description, *draft.search_queries, *draft.tags])
        if draft.kind != "media" or not _CALENDAR_INTENT.search(intent):
            continue
        spoken = {_date_key(match) for match in _DATE.finditer(segment.text)}
        if not spoken:
            continue
        cited = [claim for claim in accepted if claim.id in segment.claim_ids]
        ordered = cited + [claim for claim in accepted if claim.id not in segment.claim_ids]
        found = next(
            (
                (claim, match[0])
                for claim in ordered
                for match in _DATE.finditer(claim.text)
                if _date_key(match) in spoken
            ),
            None,
        )
        if found is None:
            continue
        claim, date_text = found
        visuals[segment.index] = draft.model_copy(
            update={
                "kind": "infographic",
                "media_type": "video",
                "category": "graphic",
                "strategy": "generate_allowed",
                "subjects": [],
                "graphics_spec": KeyDate(template="key_date", date=GroundedText(text=date_text, claim_ids=[claim.id])),
                "fallback_graphics_spec": None,
                "search_queries": [],
            }
        )
    return replace(script, visuals=tuple(visuals))


def _plan_people(script: GeneratedScript) -> tuple[PersonDraft, ...]:
    """Declared people plus capitalized multi-word visual subjects as an exact-name safety net."""
    people = list(script.people)
    known = {person.name.casefold() for person in people}
    for draft in script.visuals:
        for subject in draft.subjects:
            name = " ".join(subject.split())
            if contains_named_person([name]) and name.casefold() not in known:
                known.add(name.casefold())
                # Exact name only: undeclared subjects may be places or organizations.
                people.append(PersonDraft(name=name, mentions=[name]))
    return tuple(people)


MAX_PORTRAIT_WORDS = 14


def _cap_portraits(pieces: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """A portrait covers at most ``MAX_PORTRAIT_WORDS`` spoken words; the rest shows the planned visual (CF-REQ-268)."""
    output: list[tuple[str, str | None]] = []
    for text, person in pieces:
        words = text.split()
        if person is None or len(words) - MAX_PORTRAIT_WORDS < MIN_PIECE_WORDS:
            output.append((text, person))
            continue
        output.append((" ".join(words[:MAX_PORTRAIT_WORDS]), person))
        output.append((" ".join(words[MAX_PORTRAIT_WORDS:]), None))
    return output


def _graphic_anchor(pieces: Sequence[tuple[str, str | None, float, bool]], draft: VisualDraft) -> int | None:
    """The one piece of a Script Segment that shows its graphic: where its text is spoken, else the first."""
    spec = draft.graphics_spec if draft.kind != "media" else draft.fallback_graphics_spec
    if draft.kind == "media" and spec is None:
        return None
    slots = [position for position, piece in enumerate(pieces) if piece[1] is None]
    if not slots:
        return None
    texts = [_spoken_form(value) for value in _graphic_texts(spec.model_dump(mode="json") if spec else {})]
    spoken_at = [
        position
        for position, piece in enumerate(pieces)
        if any(text and text in _spoken_form(piece[0]) for text in texts)
    ]
    for position in spoken_at:
        if position in slots:
            return position
    # Spoken only within a portrait piece: an earlier card would precede its own words.
    return None if spoken_at else slots[0]


def _graphic_texts(value: object) -> list[str]:
    if isinstance(value, dict):
        found = [str(item) for key, item in value.items() if key == "text" and isinstance(item, str)]
        return found + [text for key, item in value.items() if key != "text" for text in _graphic_texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _graphic_texts(item)]
    return []


def _spoken_form(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def _footage_segment(segment: VisualSegment) -> VisualSegment:
    """A further piece of a graphic Script Segment shows narration-keyed footage instead of repeating the graphic."""
    requirement = {
        **segment.requirement,
        "media_type": "video",
        "category": "broll",
        "description": segment.narration_text,
        "generation_prompt": None,
        "subjects": [],
        "tags": list(narration_keywords(segment.narration_text, limit=4)),
        "strategy": "reuse_first",
        "kind": "media",
        "graphics_spec": None,
        "fallback_graphics_spec": None,
        "search_queries": [],
    }
    return replace(segment, requirement=requirement)


def _without_fallback_graphic(segment: VisualSegment) -> VisualSegment:
    """A further piece of a media Script Segment keeps its search but not the fallback graphic (CF-REQ-265)."""
    if not segment.requirement.get("search_queries"):
        return _footage_segment(segment)
    return replace(segment, requirement={**segment.requirement, "fallback_graphics_spec": None})


def _person_segment(segment: VisualSegment, name: str) -> VisualSegment:
    """Show the mentioned person; the original requirement is kept as the fallback (CF-REQ-268)."""
    requirement = {
        "media_type": "image",
        "category": "person",
        "description": f"Portrait photograph of {name}",
        "generation_prompt": None,
        "subjects": [name],
        "tags": [name],
        "strategy": "acquire_only",
        "kind": "media",
        "graphics_spec": None,
        "fallback_graphics_spec": None,
        "search_queries": [],
        "person": {"name": name, "fallback": segment.requirement},
    }
    return VisualSegment(
        index=segment.index,
        script_segment_index=segment.script_segment_index,
        narration_text=segment.narration_text,
        objective=f"Show {name} while they are mentioned",
        requirement=requirement,
        planned_duration_seconds=segment.planned_duration_seconds,
        motion="zoom_in",
        transition_in="cut",
        motion_reason=f"Draw attention to {name}",
    )


def serialize_visual_plan(segments: tuple[VisualSegment, ...]) -> list[dict[str, Any]]:
    return [asdict(segment) for segment in segments]


def _normalize_segment(
    index: int,
    script_index: int,
    narration_text: str,
    duration: float,
    draft: VisualDraft,
    allow_generated_media: bool,
    continuation: bool = False,
) -> VisualSegment:
    strategy = draft.strategy
    if strategy == "generate_allowed" and not allow_generated_media:
        strategy = "reuse_first"
    if draft.kind != "media" and allow_generated_media:
        strategy = "generate_allowed"
    if strategy == "generate_allowed" and contains_named_person(draft.subjects):
        strategy = "acquire_only"
    motion = "none" if continuation else draft.motion
    return VisualSegment(
        index=index,
        script_segment_index=script_index,
        narration_text=narration_text,
        objective=draft.objective,
        requirement={
            "media_type": "video" if draft.kind != "media" else draft.media_type,
            "category": (
                "chart"
                if draft.graphics_spec and draft.graphics_spec.template in {"comparison", "function_plot"}
                else "graphic"
                if draft.kind != "media"
                else draft.category
            ),
            "description": draft.description,
            "generation_prompt": draft.generation_prompt,
            "subjects": draft.subjects,
            "tags": draft.tags,
            "strategy": strategy,
            "kind": draft.kind,
            "graphics_spec": draft.graphics_spec.model_dump(mode="json") if draft.graphics_spec else None,
            "fallback_graphics_spec": (
                draft.fallback_graphics_spec.model_dump(mode="json") if draft.fallback_graphics_spec else None
            ),
            "search_queries": draft.search_queries,
        },
        planned_duration_seconds=duration,
        motion=motion,
        transition_in="cut" if index == 0 or continuation else draft.transition_in,
        motion_reason=draft.motion_reason or draft.objective,
    )


def distinct_media_searches(segments: list[tuple[dict[str, Any], str]]) -> None:
    """Give repeated, unspecific media intents a search keyed to their own narration (CF-REQ-219).

    Free writers sometimes copy one visual block for every Script Segment; without this every Visual would share
    one search pool and exhaust it before the last Visuals. Mutates the requirements in place and is idempotent.
    """
    seen: set[str] = set()
    for requirement, narration in segments:
        description = " ".join(str(requirement.get("description", "")).split()).casefold()
        repeated = description in seen
        seen.add(description)
        if (
            repeated
            and requirement.get("kind", "media") == "media"
            and not (requirement.get("subjects") or requirement.get("tags") or requirement.get("search_queries"))
        ):
            requirement["tags"] = list(narration_keywords(narration, limit=4))


def _split_words(text: str, count: int) -> tuple[str, ...]:
    words = text.split()
    count = min(count, len(words))
    return tuple(
        " ".join(words[start:end])
        for index in range(count)
        if (start := round(index * len(words) / count)) < (end := round((index + 1) * len(words) / count))
    )


def contains_named_person(subjects: list[str]) -> bool:
    return any(
        len(subject.split()) >= 2 and all(part[:1].isupper() for part in subject.split()) for subject in subjects
    )
