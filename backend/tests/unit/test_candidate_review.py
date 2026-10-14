from typing import Any

import pytest
from pydantic import ValidationError

from clipfactory.assets.candidate_review import (
    ReviewMediaResult,
    SegmentCandidates,
    SegmentChoice,
    review_media_candidates,
)
from clipfactory.assets.vision_review import review_media_candidates as review_images
from clipfactory.evaluation.semantic import SemanticEvaluationResult
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import ImageInput, LLMResult
from clipfactory.ports.media_sources import MediaCandidate


def candidate(name: str) -> MediaCandidate:
    return MediaCandidate(f"https://media.example/{name}", "", "fake", "CC0", "image", 1080, 1920, description=name)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.req("CF-REQ-405")
def test_omitted_review_decisions_cannot_become_default_approval() -> None:
    with pytest.raises(ValidationError):
        SegmentChoice.model_validate({"segment": 0})
    with pytest.raises(ValidationError):
        SemanticEvaluationResult.model_validate({"scores": {}})


class ScriptedLLM:
    name = "fake"

    def __init__(self, result: ReviewMediaResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []
        self.options: list[dict[str, Any]] = []

    async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.calls.append((task, messages[-1].content))
        self.options.append(kwargs)
        return LLMResult(self.result, "fake", "unit-model")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_one_batched_review_orders_choices_and_rejects_foreign_or_unknown_refs() -> None:
    lab, flowers, airbase = candidate("research laboratory"), candidate("floral wallpaper"), candidate("RAF airbase")
    llm = ScriptedLLM(
        ReviewMediaResult(
            choices=[
                SegmentChoice(segment=0, ranked=["s0c0", "s1c0", "nope"]),
                SegmentChoice(segment=1, ranked=[]),
            ]
        )
    )

    chosen = await review_media_candidates(
        llm,
        [
            SegmentCandidates(0, "Scientists studied plague.", "laboratory", (lab, flowers)),
            SegmentCandidates(1, "Capacity was reduced.", "abstract capability", (airbase,)),
        ],
        story_title="Plague researcher",
    )

    assert [task for task, _ in llm.calls] == ["review_media_candidates"]
    assert "untrusted-candidate-metadata" in llm.calls[0][1]
    assert chosen == {0: [lab], 1: []}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_real_preview_evidence_is_deduplicated_in_one_vision_request() -> None:
    lab = candidate("research laboratory")
    llm = ScriptedLLM(ReviewMediaResult(choices=[SegmentChoice(segment=0, ranked=["s0c0"])]))
    loaded = []

    async def preview(item: MediaCandidate) -> ImageInput:
        loaded.append(item.url)
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    chosen = await review_images(
        llm,
        [SegmentCandidates(0, "Researchers", "laboratory", (lab, lab))],
        story_title="Research",
        preview=preview,
    )
    assert loaded == [lab.url]
    assert len(llm.calls) == 1
    assert llm.options[0]["model_role"] == "evaluation"
    assert len(llm.options[0]["images"]) == 1
    assert '"image_index": 0' in llm.calls[0][1]
    assert chosen == {0: [lab]}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_unpreviewable_candidates_are_rejected_without_failing_or_calling_the_llm() -> None:
    """Regression: refined-search candidates with no loadable preview failed the whole stage."""
    llm = ScriptedLLM(ReviewMediaResult(choices=[SegmentChoice(segment=8, ranked=["s8c0"])]))

    async def preview(_item: MediaCandidate) -> None:
        return None

    chosen = await review_images(
        llm,
        [
            SegmentCandidates(8, "Hasan was convicted.", "courtroom", (candidate("court"),)),
            SegmentCandidates(9, "The last execution.", "military base", (candidate("base"),)),
        ],
        story_title="Execution",
        preview=preview,
    )

    assert llm.calls == []
    assert chosen == {8: [], 9: []}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_shared_candidate_chosen_by_another_segments_id_is_kept_for_every_offering_segment() -> None:
    """Regression: segments with the same Shot Intent share candidates; one ID for all must not drop to 1 kept."""
    studio, street = candidate("broadcast studio"), candidate("city street")
    llm = ScriptedLLM(
        ReviewMediaResult(
            choices=[
                SegmentChoice(segment=0, ranked=["s0c0"]),
                SegmentChoice(segment=1, ranked=["s0c0", "s0c1"]),
                SegmentChoice(segment=2, ranked=["s0c0"]),
            ]
        )
    )

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    shared = (studio, street)
    chosen = await review_images(
        llm,
        [
            SegmentCandidates(0, "Announcement.", "announcement", shared),
            SegmentCandidates(1, "Context.", "announcement", shared),
            SegmentCandidates(2, "Other.", "other", (street,)),
        ],
        story_title="Story",
        preview=preview,
    )
    assert chosen == {0: [studio], 1: [studio, street], 2: []}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_vision_review_splits_whole_segments_into_bounded_image_requests() -> None:
    """Regression: one 24-image request was rejected by free vision upstreams (HTTP 400/502)."""
    pools = [tuple(candidate(f"seg{index}-item{item}") for item in range(4)) for index in range(6)]
    llm = ScriptedLLM(
        ReviewMediaResult(choices=[SegmentChoice(segment=index, ranked=[f"s{index}c0"]) for index in range(6)])
    )

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    chosen = await review_images(
        llm,
        [SegmentCandidates(index, f"Narration {index}", "intent", pool) for index, pool in enumerate(pools)],
        story_title="Bounded",
        preview=preview,
        max_images_per_request=10,
    )

    image_counts = [len(options["images"]) for options in llm.options]
    assert image_counts == [8, 8, 8]
    assert all('"segment": 0' not in content for _, content in llm.calls[1:])
    assert chosen == {index: [pools[index][0]] for index in range(6)}


class ImageLimitedLLM(ScriptedLLM):
    """Accepts at most `limit` images per request, like a single-image free upstream."""

    def __init__(self, result: ReviewMediaResult, limit: int) -> None:
        super().__init__(result)
        self.limit = limit

    async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.options.append(kwargs)
        if len(kwargs["images"]) > self.limit:
            raise ProviderError("image_limit", "upstream accepts fewer images", transient=False)
        self.calls.append((task, messages[-1].content))
        return LLMResult(self.result, "fake", "unit-model")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_image_limit_halves_requests_until_the_upstream_accepts_them() -> None:
    pools = [tuple(candidate(f"seg{index}-item{item}") for item in range(3)) for index in range(3)]
    ranked = [SegmentChoice(segment=index, ranked=[f"s{index}c0", f"s{index}c1"]) for index in range(3)]
    llm = ImageLimitedLLM(ReviewMediaResult(choices=ranked), limit=1)

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    chosen = await review_images(
        llm,
        [SegmentCandidates(index, f"Narration {index}", "intent", pool) for index, pool in enumerate(pools)],
        story_title="Limited",
        preview=preview,
    )

    accepted = [len(options["images"]) for options in llm.options if len(options["images"]) <= 1]
    assert accepted == [1] * 9
    assert chosen == {index: list(pools[index]) for index in range(3)}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_other_provider_errors_are_not_split() -> None:
    class FailingLLM(ScriptedLLM):
        async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
            self.options.append(kwargs)
            raise ProviderError("http_400", "rejected", transient=False)

    llm = FailingLLM(ReviewMediaResult(choices=[]))

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    with pytest.raises(ProviderError):
        await review_images(
            llm,
            [SegmentCandidates(0, "Narration", "intent", (candidate("a"), candidate("b")))],
            story_title="Fails",
            preview=preview,
        )
    assert len(llm.options) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_an_unusable_answer_leaves_only_that_request_unaccepted() -> None:
    pools = [(candidate("first-a"), candidate("first-b")), (candidate("second-a"), candidate("second-b"))]

    class FlakyLLM(ScriptedLLM):
        async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
            self.options.append(kwargs)
            if len(self.options) == 1:
                raise ProviderError("llm_invalid_output", "no text JSON answer", transient=False)
            return LLMResult(ReviewMediaResult(choices=[SegmentChoice(segment=1, ranked=["s1c1"])]), "fake", "m")

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    segments = [SegmentCandidates(index, f"Narration {index}", "intent", pool) for index, pool in enumerate(pools)]
    chosen = await review_images(
        FlakyLLM(ReviewMediaResult(choices=[])),
        segments,
        story_title="Flaky",
        preview=preview,
        max_images_per_request=2,
    )
    assert chosen == {0: [], 1: [pools[1][1]]}

    class BrokenLLM(ScriptedLLM):
        async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
            raise ProviderError("llm_invalid_output", "no text JSON answer", transient=False)

    with pytest.raises(ProviderError):
        await review_images(
            BrokenLLM(ReviewMediaResult(choices=[])),
            segments,
            story_title="Broken",
            preview=preview,
            max_images_per_request=2,
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
async def test_an_opaque_upstream_rejection_of_the_only_request_reselects_instead_of_failing() -> None:
    class RejectingLLM(ScriptedLLM):
        async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
            self.options.append(kwargs)
            raise ProviderError("upstream_bad_request", "Provider returned error: bad request", transient=True)

    async def preview(_item: MediaCandidate) -> ImageInput:
        return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})

    llm = RejectingLLM(ReviewMediaResult(choices=[]))
    pools = [(candidate("runway-a"), candidate("runway-b"), candidate("runway-c")), (candidate("desert-a"),)]
    chosen = await review_images(
        llm,
        [SegmentCandidates(index, f"Narration {index}", "intent", pool) for index, pool in enumerate(pools)],
        story_title="Rejected",
        preview=preview,
    )

    assert chosen == {0: [], 1: []}
    assert len(llm.options) == 1


class PrimaryFailingLLM(ScriptedLLM):
    def __init__(self, result: ReviewMediaResult, primary_code: str, fallback_code: str | None = None) -> None:
        super().__init__(result)
        self.primary_code = primary_code
        self.fallback_code = fallback_code

    async def generate_structured(self, task: str, messages: Any, schema: Any, **kwargs: Any) -> LLMResult[Any]:
        self.options.append(kwargs)
        if kwargs.get("model_role") == "evaluation":
            raise ProviderError(self.primary_code, "Provider returned error", transient=True)
        if self.fallback_code:
            raise ProviderError(self.fallback_code, "Provider returned error", transient=True)
        return LLMResult(self.result, "fake", "fallback-model")


async def _jpeg_preview(_item: MediaCandidate) -> ImageInput:
    return ImageInput(b"jpeg-test-evidence", "image/jpeg", {})


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.req("CF-REQ-405")
@pytest.mark.asyncio
@pytest.mark.parametrize("primary_code", ["upstream_bad_request", "http_502"])
async def test_rejected_review_request_is_sent_once_unchanged_to_the_fallback_model(primary_code: str) -> None:
    runway = candidate("runway")
    llm = PrimaryFailingLLM(ReviewMediaResult(choices=[SegmentChoice(segment=0, ranked=["s0c0"])]), primary_code)

    chosen = await review_images(
        llm,
        [SegmentCandidates(0, "Narration", "intent", (runway,))],
        story_title="Moderated",
        preview=_jpeg_preview,
        fallback=True,
    )

    assert chosen == {0: [runway]}
    assert [options["model_role"] for options in llm.options] == ["evaluation", "evaluation_fallback"]
    assert llm.options[0]["images"] == llm.options[1]["images"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_code", ["upstream_bad_request", "llm_unavailable"])
async def test_failed_fallback_review_fails_closed_for_that_request_only(fallback_code: str) -> None:
    # llm_unavailable: the fallback model's own exhausted 502s opened its per-model circuit (live Run 2fc25075).
    llm = PrimaryFailingLLM(ReviewMediaResult(choices=[]), "upstream_bad_request", fallback_code)

    chosen = await review_images(
        llm,
        [SegmentCandidates(0, "Narration", "intent", (candidate("runway"),))],
        story_title="Moderated",
        preview=_jpeg_preview,
        fallback=True,
    )

    assert chosen == {0: []}
    assert len(llm.options) == 2
