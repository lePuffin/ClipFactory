from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipfactory.domain.models import Claim, ClaimKind, ClaimStatus, ContentProfile, SupportLevel
from clipfactory.planning.script import (
    GeneratedScript,
    ScriptGateError,
    ScriptSegment,
    SocialMetadataDraft,
    WriteScriptResult,
    generate_script,
    validate_script_gate,
)
from clipfactory.ports.llm import LLMMessage, LLMResult


class FakeLLM:
    name = "fake"

    def __init__(self, result: WriteScriptResult) -> None:
        self.result = result
        self.calls: list[tuple[str, list[LLMMessage]]] = []

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[Any],
        *,
        model_role: str = "default",
        images: list[Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[Any]:
        del schema, model_role, images, temperature
        self.calls.append((task, messages))
        return cast(LLMResult[Any], LLMResult(self.result, "fake", "test-model"))


def _claims() -> list[Claim]:
    story_id = uuid4()
    return [
        Claim(
            story_id=story_id,
            text=f"Verified claim number {index}.",
            kind=ClaimKind.FACT,
            support_level=SupportLevel.CORROBORATED,
            status=ClaimStatus.ACCEPTED,
        )
        for index in range(3)
    ]


def _result(claims: list[Claim]) -> WriteScriptResult:
    claim_ids = [claim.id for claim in claims]
    detail = (
        "The report describes verified measurements, independent review, and the study's documented public impact "
        "in clear terms for readers. " * 3
    )
    texts = ["A verified event is unfolding now", detail, detail, detail]
    return WriteScriptResult.model_validate(
        {
            "segments": [
                {"text": text, "claim_ids": [claim_ids[min(index, len(claim_ids) - 1)]], "attribution": None}
                for index, text in enumerate(texts)
            ],
            "social_metadata": {
                "title": "Verified science update",
                "description": "Source-grounded summary.",
                "hashtags": ["#science", "#news", "#research"],
            },
            "visuals": [
                {
                    "objective": "Show an illustrative science visual",
                    "media_type": "image",
                    "category": "photo",
                    "description": "Scientific research",
                    "subjects": [],
                    "tags": ["science"],
                    "strategy": "reuse_first",
                    "motion": "ken_burns",
                    "transition_in": "cut",
                }
                for _ in texts
            ],
        }
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-153")
@pytest.mark.req("CF-REQ-154")
@pytest.mark.req("CF-REQ-156")
@pytest.mark.req("CF-REQ-157")
@pytest.mark.req("CF-REQ-160")
@pytest.mark.asyncio
async def test_script_generation_uses_one_grounded_structured_request() -> None:
    claims = _claims()
    llm = FakeLLM(_result(claims))
    script = await generate_script(
        llm,
        story_title="Science update",
        story_summary="A significant event.",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
        revision_instructions=["Shorten the hook to fit its duration limit"],
        target_word_count=170,
        source_attributions=["Fixture Publisher"],
    )
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "write_script"
    assert "<untrusted-accepted-claims>" in llm.calls[0][1][1].content
    assert "first segment must contain at most" in llm.calls[0][1][0].content
    assert "Target 170 words" in llm.calls[0][1][0].content
    assert "Fixture Publisher" in llm.calls[0][1][-2].content
    assert "Shorten the hook" in llm.calls[0][1][-1].content
    assert "All original constraints still apply" in llm.calls[0][1][-1].content
    assert "keep required publisher attribution fields and spoken" in llm.calls[0][1][-1].content
    assert "including publisher credits" in llm.calls[0][1][0].content
    assert "Use names, numbers, dates and quotes only when supported" in llm.calls[0][1][0].content
    assert "Do not add names, numbers" not in llm.calls[0][1][0].content
    assert len(script.segments) == 4
    assert script.segments[0].estimated_duration_seconds <= 5
    assert 60 <= script.estimated_duration_seconds <= 90
    assert script.social_metadata.title == "Verified science update"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-163")
@pytest.mark.req("CF-REQ-259")
@pytest.mark.asyncio
async def test_quality_writer_preserves_grounded_editorial_intent_in_one_call():
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][0]["purpose"] = "hook"
    value["editorial_overlays"] = [
        {"segment_index": 0, "kind": "headline", "text": "Verified science update", "claim_ids": [str(claims[0].id)]}
    ]
    llm = FakeLLM(WriteScriptResult.model_validate(value))
    script = await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
    )
    assert len(llm.calls) == 1
    assert script.segments[0].purpose == "hook"
    assert script.editorial_overlays[0].claim_ids == [claims[0].id]
    assert "editorial_overlays" in llm.calls[0][1][0].content


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_script_gate_rejects_unknown_claim_reference() -> None:
    claims = _claims()
    unknown_id = uuid4()
    generated = GeneratedScript(
        language="en",
        segments=(
            ScriptSegment(0, "A short grounded hook.", (claims[0].id,), None, 1.0),
            ScriptSegment(1, "An unknown claim reference.", (unknown_id,), None, 1.0),
            ScriptSegment(2, "Another grounded fact.", (claims[1].id,), None, 1.0),
            ScriptSegment(3, "A final grounded fact.", (claims[2].id,), None, 1.0),
        ),
        word_count=20,
        estimated_duration_seconds=70,
        social_metadata=SocialMetadataDraft(
            title="Valid title", description="Valid description", hashtags=["#a", "#b", "#c"]
        ),
        visuals=tuple(_result(claims).visuals),
        model="fake",
    )
    with pytest.raises(ScriptGateError) as caught:
        validate_script_gate(
            generated,
            claims=claims,
            profile=ContentProfile(),
            min_segments=4,
            max_segments=8,
            hook_max_seconds=5,
            lead_in_seconds=0.3,
            tail_seconds=1.0,
        )
    assert "unknown_claim" in caught.value.codes


@pytest.mark.unit
@pytest.mark.req("CF-REQ-160")
@pytest.mark.req("CF-REQ-758")
def test_script_schema_rejects_missing_visual_coverage() -> None:
    value = _result(_claims()).model_dump()
    value["visuals"] = value["visuals"][:1]
    with pytest.raises(ValidationError, match="at least one Visual Segment per Script Segment"):
        WriteScriptResult.model_validate(value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-116")
@pytest.mark.asyncio
async def test_writer_learns_which_claims_need_attribution_and_gate_names_the_failing_segment() -> None:
    claims = _claims()
    claims[1] = claims[1].model_copy(update={"support_level": SupportLevel.SINGLE_SOURCE})
    llm = FakeLLM(_result(claims))

    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            claim_publishers={claims[1].id: ["The Guardian"]},
        )

    prompt = llm.calls[0][1][1].content
    assert '"requires_attribution": true' in prompt
    assert '"publishers": ["The Guardian"]' in prompt
    assert "missing_attribution" in caught.value.codes
    assert "segment 1 cites a single-source" in caught.value.detail


@pytest.mark.unit
@pytest.mark.req("CF-REQ-116")
@pytest.mark.asyncio
async def test_attribution_field_is_recorded_only_when_narration_names_the_cited_publisher() -> None:
    claims = _claims()
    claims[1] = claims[1].model_copy(update={"support_level": SupportLevel.SINGLE_SOURCE})
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] = "According to The Guardian, " + value["segments"][1]["text"]
    llm = FakeLLM(WriteScriptResult.model_validate(value))

    script = await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
        claim_publishers={claims[1].id: ["The Guardian"]},
    )

    assert script.segments[1].attribution == "The Guardian"
    assert script.segments[0].attribution is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_narration_revision_receives_the_previous_script_and_preserves_hook_guidance() -> None:
    claims = _claims()
    result = _result(claims)
    previous = result.model_dump(mode="json")
    llm = FakeLLM(result)
    await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
        previous_script=previous,
        revision_instructions=["Add eleven words to meet narration duration"],
        target_word_count=180,
    )
    assert len(llm.calls) == 1
    request = llm.calls[0][1][-2].content
    assert "<untrusted-previous-script>" in request
    assert result.segments[0].text in request
    assert str(claims[0].id) in request
    assert "keep an already-passing hook unchanged" in request
    assert "Add eleven words" in llm.calls[0][1][-1].content
