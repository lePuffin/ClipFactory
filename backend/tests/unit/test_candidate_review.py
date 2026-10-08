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
