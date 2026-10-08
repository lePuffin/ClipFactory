"""One batched LLM judgement of licensed media candidates for every Visual Segment (ADR-018, task 4)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from clipfactory.ports.llm import LLMMessage, LLMProvider
from clipfactory.ports.media_sources import MediaCandidate

_DESCRIPTION_CHARS = 180


@dataclass(frozen=True, slots=True)
class SegmentCandidates:
    segment_index: int
    narration: str
    intent: str
    candidates: tuple[MediaCandidate, ...]


class SegmentChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: int = Field(ge=0)
    ranked: list[str] = Field(max_length=3)


class ReviewMediaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choices: list[SegmentChoice]


async def review_media_candidates(
    llm: LLMProvider,
    segments: Sequence[SegmentCandidates],
    *,
    story_title: str,
    prompt_version: str = "review_media_candidates.v1",
) -> dict[int, list[MediaCandidate]]:
    """Return, per segment, only reviewed candidates in judged order; an empty list means none fits."""
    references: dict[str, tuple[int, MediaCandidate]] = {}
    payload = []
    for segment in segments:
        listed = []
        for position, candidate in enumerate(segment.candidates):
            reference = f"s{segment.segment_index}c{position}"
            references[reference] = (segment.segment_index, candidate)
            listed.append(
                {
                    "id": reference,
                    "type": candidate.media_type,
                    "source": candidate.source,
                    "description": " ".join(candidate.description.split())[:_DESCRIPTION_CHARS],
                }
            )
        payload.append(
            {
                "segment": segment.segment_index,
                "narration": segment.narration,
                "intent": segment.intent,
                "candidates": listed,
            }
        )
    messages = [
        LLMMessage(
            "system",
            "You choose stock or archive visuals for a factual vertical news explainer. "
            "For each segment return up to 3 candidate ids, best first, that genuinely depict the segment intent "
            "or its concrete subject (place, object, institution, activity). Return an empty list when none fits. "
            "Reject decorative or unrelated images (flowers, pets, abstract wallpaper, unrelated documents), "
            "images of a different named place, event or person presented as this one, and anything that could "
            "mislead viewers. A generic but accurate image (e.g. a laboratory for a research story) is acceptable. "
            "Judge only from the given descriptions; never invent identities. "
            f"Prompt version: {prompt_version}.",
        ),
        LLMMessage(
            "user",
            "Story: "
            + json.dumps(story_title, ensure_ascii=False)
            + "\n<untrusted-candidate-metadata>\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n</untrusted-candidate-metadata>",
        ),
    ]
    response = await llm.generate_structured("review_media_candidates", messages, ReviewMediaResult)
    return _validated_choices(response.value, references, [segment.segment_index for segment in segments])


def _validated_choices(
    result: ReviewMediaResult,
    references: Mapping[str, tuple[int, MediaCandidate]],
    segment_indexes: Sequence[int],
) -> dict[int, list[MediaCandidate]]:
    chosen: dict[int, list[MediaCandidate]] = {index: [] for index in segment_indexes}
    for choice in result.choices:
        if choice.segment not in chosen:
            continue
        for reference in choice.ranked:
            owner = references.get(reference)
            # Code, not the model, enforces that a choice belongs to the segment it was offered for.
            if owner is None or owner[0] != choice.segment or owner[1] in chosen[choice.segment]:
                continue
            chosen[choice.segment].append(owner[1])
    return chosen
