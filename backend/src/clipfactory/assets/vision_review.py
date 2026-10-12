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
from clipfactory.ports.llm import EVALUATION_FALLBACK_ERRORS, ImageInput, LLMMessage, LLMModelRole, LLMProvider
from clipfactory.ports.media_sources import MediaCandidate


async def review_media_candidates(
    llm: LLMProvider,
    segments: Sequence[SegmentCandidates],
    *,
    story_title: str,
    preview: Callable[[MediaCandidate], Awaitable[ImageInput | None]] | None = None,
    max_preview_images: int = 24,
    max_images_per_request: int = 10,
    fallback: bool = False,
) -> dict[int, list[MediaCandidate]]:
    """Review previews in requests of at most `max_images_per_request` images.

    Free vision upstreams reject prompts with many images, so whole segments are packed into bounded requests; a
    segment whose own previews exceed the bound is reviewed in chunks whose rankings are concatenated in order.
    With `fallback`, a request the evaluation model rejects or cannot serve is sent once, unchanged, to the
    evaluation fallback model before failing closed (CF-REQ-219).
    """
    if preview is None:
        return await review_metadata(llm, segments, story_title=story_title)
    if max_images_per_request < 1:
        raise ValueError("max_images_per_request must be positive")
    loaded: dict[str, ImageInput | None] = {}
    for position in range(max((len(segment.candidates) for segment in segments), default=0)):
        for segment in segments:
            if position >= len(segment.candidates):
                continue
            candidate = segment.candidates[position]
            if candidate.url in loaded:
                continue
            within_total = sum(image is not None for image in loaded.values()) < max_preview_images
            loaded[candidate.url] = await preview(candidate) if within_total else None
    chosen: dict[int, list[MediaCandidate]] = {segment.segment_index: [] for segment in segments}
    unusable: list[ProviderError] = []
    batches = _pack(segments, loaded, max_images_per_request)
    for batch in batches:
        _merge(
            chosen,
            await _review_within_image_limit(
                llm, batch, story_title=story_title, loaded=loaded, unusable=unusable, fallback=fallback
            ),
        )
    systemic = [exc for exc in unusable if exc.code != "upstream_bad_request"]
    if systemic and not any(chosen.values()):
        raise systemic[-1]
    return chosen


async def _review_within_image_limit(
    llm: LLMProvider,
    batch: list[SegmentCandidates],
    *,
    story_title: str,
    loaded: dict[str, ImageInput | None],
    unusable: list[ProviderError],
    fallback: bool = False,
) -> dict[int, list[MediaCandidate]]:
    try:
        return await _review_batch(llm, batch, story_title=story_title, loaded=loaded)
    except ProviderError as exc:
        if fallback and exc.code in EVALUATION_FALLBACK_ERRORS:
            try:
                return await _review_batch(
                    llm, batch, story_title=story_title, loaded=loaded, model_role="evaluation_fallback"
                )
            except ProviderError as fallback_exc:
                # llm_unavailable here means the fallback model's own circuit opened (CF-REQ-671 per-model scope).
                if fallback_exc.code not in {
                    "llm_invalid_output",
                    "image_limit",
                    "llm_unavailable",
                    *EVALUATION_FALLBACK_ERRORS,
                }:
                    raise
                # Fail closed for this request only, reporting the primary rejection.
                unusable.append(exc if exc.code == "upstream_bad_request" else fallback_exc)
                return {}
        image_count = len({item.url for segment in batch for item in segment.candidates if loaded.get(item.url)})
        if exc.code in {"llm_invalid_output", "upstream_bad_request"} or (
            exc.code == "image_limit" and image_count <= 1
        ):
            # Fail closed for this request only: its candidates stay unaccepted and their Visuals reselect.
            # An opaque upstream rejection is content-specific; resending or splitting it would only trip the circuit.
            unusable.append(exc)
            return {}
        if exc.code != "image_limit":
            raise
    # The routed vision model accepts fewer images per prompt: halve the request and review the parts separately.
    chosen: dict[int, list[MediaCandidate]] = {}
    for smaller in _pack(batch, loaded, max(1, image_count // 2)):
        _merge(
            chosen,
            await _review_within_image_limit(
                llm, smaller, story_title=story_title, loaded=loaded, unusable=unusable, fallback=fallback
            ),
        )
    return chosen


def _merge(chosen: dict[int, list[MediaCandidate]], reviewed: dict[int, list[MediaCandidate]]) -> None:
    for segment_index, ranked in reviewed.items():
        known = chosen.setdefault(segment_index, [])
        known.extend(item for item in ranked if item not in known)


def _pack(
    segments: Sequence[SegmentCandidates], loaded: dict[str, ImageInput | None], max_images_per_request: int
) -> list[list[SegmentCandidates]]:
    batches: list[list[SegmentCandidates]] = []
    batch_urls: set[str] = set()
    for segment in segments:
        urls = list(dict.fromkeys(item.url for item in segment.candidates if loaded.get(item.url) is not None))
        chunks = [urls[start : start + max_images_per_request] for start in range(0, len(urls), max_images_per_request)]
        for chunk in chunks or [[]]:
            part = segment
            if len(chunks) > 1:
                part = SegmentCandidates(
                    segment.segment_index,
                    segment.narration,
                    segment.intent,
                    tuple(item for item in segment.candidates if item.url in chunk),
                )
            if batches and len(batch_urls | set(chunk)) <= max_images_per_request:
                batches[-1].append(part)
                batch_urls |= set(chunk)
            else:
                batches.append([part])
                batch_urls = set(chunk)
    return batches


async def _review_batch(
    llm: LLMProvider,
    segments: Sequence[SegmentCandidates],
    *,
    story_title: str,
    loaded: dict[str, ImageInput | None],
    model_role: LLMModelRole = "evaluation",
) -> dict[int, list[MediaCandidate]]:
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
            image = loaded.get(candidate.url)
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
        # Unseen media is never approved; empty choices route these Visuals to missing_asset reselection.
        return {segment.segment_index: [] for segment in segments}
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
                "Judge every segment against its own narration and intent; segments may share candidates, so "
                "rank every fitting candidate and prefer different images for different segments. "
                "Choose from supplied IDs only. Prompt version: review_media_candidates.v3.",
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
        model_role=model_role,
        images=images,
    )
    return _validated_choices(response.value, references, [segment.segment_index for segment in segments])
