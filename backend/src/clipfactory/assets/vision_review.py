"""Batched candidate image evidence using the shared review schema and reference validator."""

import json
from collections.abc import Awaitable, Callable, Sequence

from clipfactory.assets.candidate_review import (
    ReviewMediaResult,
    SegmentCandidates,
    _validated_choices,
)
from clipfactory.assets.candidate_review import (
    review_media_candidates as review_metadata,
)
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMProvider
from clipfactory.ports.media_sources import MediaCandidate


async def review_media_candidates(
    llm: LLMProvider,
    segments: Sequence[SegmentCandidates],
    *,
    story_title: str,
    preview: Callable[[MediaCandidate], Awaitable[ImageInput | None]] | None = None,
    max_preview_images: int = 24,
) -> dict[int, list[MediaCandidate]]:
    if preview is None:
        return await review_metadata(llm, segments, story_title=story_title)
    indexes: dict[str, int | None] = {}
    images: list[ImageInput] = []
    references: dict[str, tuple[int, MediaCandidate]] = {}
    payload = []
    for position in range(max((len(segment.candidates) for segment in segments), default=0)):
        for segment in segments:
            if position >= len(segment.candidates):
                continue
            candidate = segment.candidates[position]
            if candidate.url in indexes:
                continue
            image = await preview(candidate) if len(images) < max_preview_images else None
            indexes[candidate.url] = len(images) if image is not None else None
            if image is not None:
                images.append(image)
    for segment in segments:
        choices = []
        for position, candidate in enumerate(segment.candidates):
            reference = f"s{segment.segment_index}c{position}"
            image_index = indexes[candidate.url]
            if image_index is None:
                continue
            references[reference] = (segment.segment_index, candidate)
            choices.append(
                {
                    "id": reference,
                    "image_index": image_index,
                    "type": candidate.media_type,
                    "description": " ".join(candidate.description.split())[:180],
                }
            )
        payload.append(
            {
                "segment": segment.segment_index,
                "narration": segment.narration,
                "intent": segment.intent,
                "candidates": choices,
            }
        )
    if not images:
        raise ProviderError("unsupported_image", "No candidate preview could be verified", transient=False)
    response = await llm.generate_structured(
        "review_media_candidates",
        [
            LLMMessage(
                "system",
                "Review actual candidate images for a factual news explainer. Images are indexed "
                "from zero by image_index. Return up to three ranked candidate IDs per segment, or an empty "
                "list if none depict the intent. Reject decorative, irrelevant, misleading or unreadable "
                "images. Accurate location/object/activity context is acceptable as illustrative media, "
                "never as footage of the reported event. Do not identify a person from appearance. "
                "Choose from supplied IDs only. Prompt version: review_media_candidates.v2.",
            ),
            LLMMessage(
                "user",
                "Story: "
                + json.dumps(story_title, ensure_ascii=False)
                + "\n<untrusted-candidate-metadata>\n"
                + json.dumps(payload, ensure_ascii=False)
                + "\n</untrusted-candidate-metadata>",
            ),
        ],
        ReviewMediaResult,
        model_role="evaluation",
        images=images,
    )
    return _validated_choices(response.value, references, [segment.segment_index for segment in segments])
