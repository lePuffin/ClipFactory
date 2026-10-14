import json
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipfactory.domain.models import Claim, ClaimKind, ClaimStatus, ContentProfile, Stage, SupportLevel
from clipfactory.domain.routing import ISSUE_ROUTES
from clipfactory.planning.script import (
    GeneratedScript,
    NarrationRepairResult,
    ScriptGateError,
    ScriptSegment,
    SocialMetadataDraft,
    VisualDraft,
    WriteScriptResult,
    claim_restated_sentences,
    generate_script,
    validate_script_gate,
)
from clipfactory.planning.visuals import build_visual_plan
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.workflow.graph import WorkflowState
from clipfactory.workflow.production_stages import ProductionStageService


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


_FIXTURE_SENTENCES = [
    "Coastal laboratories recorded warmer currents across northern shipping lanes during three "
    "consecutive months, as the official summary notes, "
    "{}.",
    "Independent reviewers compared archived satellite readings against buoy logs before approving "
    "publication, as the official summary notes, "
    "{}.",
    "Fishing cooperatives reported smaller seasonal catches while regional ports delayed several cargo "
    "departures, as the official summary notes, "
    "{}.",
    "University statisticians checked every calculation twice and released their spreadsheets for public "
    "scrutiny, as the official summary notes, "
    "{}.",
    "Municipal planners scheduled flood barrier inspections because tidal gauges exceeded earlier safety "
    "thresholds, as the official summary notes, "
    "{}.",
    "Environmental agencies opened consultations inviting farmers, engineers and residents to submit "
    "written evidence, as the official summary notes, "
    "{}.",
    "Insurance analysts revised premium forecasts after storm damage claims doubled along exposed river "
    "valleys, as the official summary notes, "
    "{}.",
    "Teachers added classroom modules explaining how sensors capture salinity, pressure and wind "
    "direction data, as the official summary notes, "
    "{}.",
    "Volunteer divers photographed coral bleaching near protected reefs and shared images with marine "
    "biologists, as the official summary notes, "
    "{}.",
]


def _claims() -> list[Claim]:
    story_id = uuid4()
    return [
        Claim(
            story_id=story_id,
            text=f"Verified claim number {index}: a verified event is unfolding now. "
            + " ".join(sentence.format("item") for sentence in _FIXTURE_SENTENCES[index * 3 : index * 3 + 3]),
            kind=ClaimKind.FACT,
            support_level=SupportLevel.CORROBORATED,
            status=ClaimStatus.ACCEPTED,
        )
        for index in range(3)
    ]


def _result(claims: list[Claim]) -> WriteScriptResult:
    claim_ids = [claim.id for claim in claims]

    sentences = _FIXTURE_SENTENCES

    def detail(segment: int) -> str:
        return " ".join(
            sentences[(segment - 1) * 3 + offset].format(f"item {segment}{part}") for offset, part in enumerate("abc")
        )

    texts = ["A verified event is unfolding now.", detail(1), detail(2), detail(3)]
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
            "buzz_lines": [
                {"segment_index": index, "text": f"Verified finding {index}", "claim_ids": [claim_ids[0]]}
                for index in (0, 1)
            ],
        }
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-153")
@pytest.mark.req("CF-REQ-154")
@pytest.mark.req("CF-REQ-156")
@pytest.mark.req("CF-REQ-157")
@pytest.mark.req("CF-REQ-158")
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
    assert "complete spoken sentences with initial capitalization" in llm.calls[0][1][0].content
    assert "sentence-final punctuation" in llm.calls[0][1][0].content
    assert "Never copy a headline or incomplete evidence clause verbatim" in llm.calls[0][1][0].content
    assert "Target 170 words" in llm.calls[0][1][0].content
    assert "Fixture Publisher" in llm.calls[0][1][-2].content
    assert "Shorten the hook" in llm.calls[0][1][-1].content
    assert "All original constraints still apply" in llm.calls[0][1][-1].content
    assert "keep required publisher attribution fields and spoken" in llm.calls[0][1][-1].content
    assert "including publisher credits" in llm.calls[0][1][0].content
    assert "Use names, numbers, dates and quotes only when supported" in llm.calls[0][1][0].content
    assert "ordinary photographable scenes that free stock libraries" in llm.calls[0][1][0].content
    assert "never request on-screen text, tables, scoreboards" in llm.calls[0][1][0].content
    assert "Do not add names, numbers" not in llm.calls[0][1][0].content
    assert len(script.segments) == 4
    assert script.segments[0].estimated_duration_seconds <= 5
    assert 60 <= script.estimated_duration_seconds <= 90
    assert script.social_metadata.title == "Verified science update"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-267")
@pytest.mark.parametrize(
    ("width", "height", "framing"),
    [(720, 1280, "portrait (vertical)"), (1280, 720, "landscape (horizontal)"), (720, 720, "square")],
)
async def test_generation_shot_prompt_is_separate_from_search_and_preserved_in_plan(width, height, framing) -> None:
    claims = _claims()
    value = _result(claims)
    value.visuals[0].generation_prompt = "Cinematic view of laboratory instruments moving under soft window light."
    llm = FakeLLM(value)
    profile = ContentProfile()
    profile = profile.model_copy(
        update={"output": profile.output.model_copy(update={"width": width, "height": height})}
    )
    script = await generate_script(
        llm,
        story_title="Science update",
        story_summary="Accepted measurements",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=profile,
    )
    assert len(llm.calls) == 1
    assert "generation_prompt separately from the search description" in llm.calls[0][1][0].content
    assert "including reuse_first shots" in llm.calls[0][1][0].content
    assert "stable subject geometry" in llm.calls[0][1][0].content
    assert f"Compose for {framing}" in llm.calls[0][1][0].content
    assert "restrained, believable motion" in llm.calls[0][1][0].content
    segment = build_visual_plan(script, allow_generated_media=True)[0]
    assert segment.requirement["description"] == "Scientific research"
    assert segment.requirement["generation_prompt"] == value.visuals[0].generation_prompt


@pytest.mark.unit
@pytest.mark.req("CF-REQ-267")
@pytest.mark.parametrize("prompt", ["", "   ", "x" * 2001])
def test_generation_prompt_is_bounded(prompt: str) -> None:
    with pytest.raises(ValidationError):
        VisualDraft(
            objective="Concrete shot",
            media_type="video",
            category="broll",
            description="Landscape",
            generation_prompt=prompt,
        )


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
@pytest.mark.req("CF-REQ-219")
def test_copied_unspecific_visuals_get_segment_specific_searches() -> None:
    """Regression (Run 05bbf9de): a free writer copied one visual block for every Script Segment."""
    claims = _claims()
    copied = VisualDraft(
        objective="Illustrate the announcement.",
        media_type="video",
        category="News",
        description="Shows the announcement of the livestreamed firing squad execution.",
    )
    specific = copied.model_copy(update={"subjects": ["courtroom"]})
    script = GeneratedScript(
        language="en",
        segments=(
            ScriptSegment(0, "According to France 24, the execution will be livestreamed.", (claims[0].id,), None, 4),
            ScriptSegment(1, "Hasan was convicted of killing thirteen people.", (claims[1].id,), None, 4),
            ScriptSegment(2, "The last military execution took place in 1961.", (claims[2].id,), None, 4),
            ScriptSegment(3, "Hasan was convicted at a court martial.", (claims[2].id,), None, 4),
        ),
        word_count=30,
        estimated_duration_seconds=16,
        social_metadata=SocialMetadataDraft(title="Title", description="Description", hashtags=["#a", "#b", "#c"]),
        visuals=(copied, copied, copied, specific),
        model="fake",
    )

    plan = build_visual_plan(script, allow_generated_media=True)

    assert plan[0].requirement["tags"] == []
    assert plan[1].requirement["tags"] == ["Hasan", "convicted", "killing", "thirteen"]
    assert plan[2].requirement["tags"] == ["last", "military", "execution", "took"]
    assert plan[3].requirement["tags"] == []
    assert plan[3].requirement["subjects"] == ["courtroom"]
    assert {segment.requirement["description"] for segment in plan} == {copied.description}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-250")
@pytest.mark.req("CF-REQ-758")
def test_missing_visual_coverage_gets_narration_derived_media_visuals() -> None:
    """Regression: a free writer listed fewer Visuals than Script Segments and the whole Run failed twice."""
    value = _result(_claims()).model_dump()
    value["visuals"] = value["visuals"][:1]
    result = WriteScriptResult.model_validate(value)
    assert len(result.visuals) == len(result.segments)
    assert result.visuals[0].model_dump() == value["visuals"][0]
    for segment, visual in zip(result.segments[1:], result.visuals[1:], strict=True):
        assert visual.kind == "media"
        assert visual.description == " ".join(segment.text.split()[:16])
        assert visual.tags
        assert visual.category == value["visuals"][0]["category"]


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
@pytest.mark.req("CF-REQ-116")
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-407")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("credits", "repeated"),
    [
        (("", "", ""), False),
        (("According to The Guardian World, ", "", ""), False),
        (("According to The Guardian World, ", "According to The Guardian World, ", ""), True),
        (("The Guardian World reports; GUARDIAN   WORLD adds: ", "", ""), True),
        (("According to The Guardian World, ", "According to Reuters, ", ""), False),
        (("The Guardian Worldwide service is available. ", "", ""), False),
    ],
)
async def test_spoken_publisher_mentions_are_limited_across_the_entire_script(
    credits: tuple[str, str, str], repeated: bool
) -> None:
    claims = _claims()
    claims[1] = claims[1].model_copy(update={"support_level": SupportLevel.SINGLE_SOURCE})
    value = _result(claims).model_dump(mode="json")
    for segment, credit in zip(value["segments"][1:], credits, strict=True):
        segment["text"] = credit + segment["text"]
        segment["attribution"] = "The Guardian World"
    llm = FakeLLM(WriteScriptResult.model_validate(value))

    async def generate() -> GeneratedScript:
        return await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            claim_publishers={claims[1].id: ["The Guardian World"], claims[2].id: ["Reuters"]},
        )

    if repeated:
        with pytest.raises(ScriptGateError) as caught:
            await generate()
        assert caught.value.codes == ("repeated_attribution",)
        assert "at most once" in caught.value.detail
        assert "guardian world" in caught.value.detail
        assert ISSUE_ROUTES["repeated_attribution"].action_type.value == "revise_script"
        target_stage = ISSUE_ROUTES["repeated_attribution"].target_stage
        assert target_stage is not None
        assert target_stage.value == "write_script"
    else:
        script = await generate()
        assert all(segment.attribution == "The Guardian World" for segment in script.segments[1:])
        assert script.social_metadata == llm.result.social_metadata
    assert len(llm.calls) == 1
    assert "at most once across the entire narration" in llm.calls[0][1][0].content


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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "correction",
    [
        {"segment_index": 0, "text": "Coastal laboratories recorded warmer currents.", "attribution": None},
        {"segment_index": 0, "text": " ".join(["Measurement"] * 13) + ".", "attribution": None},
        {"segment_index": 1, "text": "Wrong segment.", "attribution": None},
        {"segment_index": 50, "text": "Out of range.", "attribution": None},
    ],
)
@pytest.mark.parametrize("duplicate", [False, True])
async def test_rejected_hook_is_repaired_without_regenerating_visuals_or_claims(
    correction: dict[str, Any], duplicate: bool
) -> None:
    claims = _claims()
    result = _result(claims)
    result.segments[0].text = " ".join(["Measurement"] * 13) + "."
    with pytest.raises(ScriptGateError) as initial:
        await generate_script(
            FakeLLM(result),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert initial.value.draft is result
    assert initial.value.codes == ("hook_too_long",)

    class RepairLLM(FakeLLM):
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
            assert schema is NarrationRepairResult
            self.calls.append((task, messages))
            return LLMResult(
                NarrationRepairResult.model_validate({"corrections": [correction] * (2 if duplicate else 1)}),
                "fake",
                "repair-model",
            )

    llm = RepairLLM(result)

    async def repair() -> GeneratedScript:
        return await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            rejected_draft=initial.value.draft,
            rejected_codes=initial.value.codes,
            revision_instructions=[initial.value.detail],
        )

    if duplicate or correction["segment_index"] != 0 or len(correction["text"].split()) > 12:
        with pytest.raises(ScriptGateError) as rejected:
            await repair()
        assert rejected.value.draft is not None
        assert rejected.value.codes == ("hook_too_long",)
        if duplicate or correction["segment_index"] != 0:
            assert "duplicate or out-of-scope indexes" in rejected.value.detail
            assert rejected.value.draft == result
    else:
        script = await repair()
        assert script.segments[0].text == correction["text"]
        assert script.segments[0].claim_ids == tuple(result.segments[0].claim_ids)
        assert [segment.text for segment in script.segments[1:]] == [segment.text for segment in result.segments[1:]]
        assert script.visuals == tuple(result.visuals)
        assert script.social_metadata == result.social_metadata
        assert script.model == "repair-model"
    assert len(llm.calls) == 1
    assert "Editable segment indexes: [0]" in llm.calls[0][1][0].content
    assert "graphics_spec" not in "".join(message.content for message in llm.calls[0][1])


@pytest.mark.unit
@pytest.mark.req("CF-REQ-153")
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_rejected_draft_retains_attribution_recovered_from_spoken_credit() -> None:
    claims = _claims()
    claims[0] = claims[0].model_copy(update={"support_level": SupportLevel.SINGLE_SOURCE})
    draft = _result(claims)
    draft.segments[0].text = "According to Fixture Publisher " + " ".join(["measurement"] * 9) + "."
    with pytest.raises(ScriptGateError) as rejected:
        await generate_script(
            FakeLLM(draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            claim_publishers={claims[0].id: ["Fixture Publisher"]},
        )
    assert rejected.value.codes == ("hook_too_long",)
    assert rejected.value.draft is not None
    assert rejected.value.draft.segments[0].attribution == "Fixture Publisher"
    assert rejected.value.draft.visuals == draft.visuals
    assert draft.segments[0].attribution is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_non_narration_defects_use_full_writer_with_the_retained_draft() -> None:
    claims = _claims()
    draft = _result(claims)
    draft.segments = draft.segments[:3]
    with pytest.raises(ScriptGateError) as rejected:
        await generate_script(
            FakeLLM(draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "script_segment_count" in rejected.value.codes
    llm = FakeLLM(_result(claims))
    script = await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
        rejected_draft=rejected.value.draft,
        rejected_codes=rejected.value.codes,
        revision_instructions=["Restore the required segment count"],
    )
    assert len(script.segments) == 4
    assert len(llm.calls) == 1
    request = "".join(message.content for message in llm.calls[0][1])
    assert "<untrusted-previous-script>" in request
    assert draft.segments[0].text in request
    assert "Return the complete script and visual draft" in request


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_workflow_retains_rejected_draft_without_accepting_it_and_reuses_it_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = _claims()
    draft = _result(claims)
    run_id, package_id = uuid4(), uuid4()
    production = MagicMock()
    production.package_context.return_value = {
        "title": "Science",
        "summary": "Verified findings",
        "claims": claims,
        "key_fact_claim_ids": [str(claim.id) for claim in claims],
    }
    production.current_script.side_effect = LookupError("No accepted script")
    service = ProductionStageService(
        production=production,
        runs=MagicMock(),
        assets=None,
        evaluations=MagicMock(),
        storage=None,
        llm=None,
        tts=None,
        transcription=None,
        media=None,
        clock=lambda: datetime(2026, 10, 9, tzinfo=UTC),
    )
    monkeypatch.setattr(
        service,
        "_run_context",
        AsyncMock(
            return_value=(
                run_id,
                1,
                {"settings_snapshot": {}},
                ContentProfile(),
            )
        ),
    )
    error = ScriptGateError(["hook_too_long"], "Hook has 13 words; maximum 12")
    error.draft = draft
    generate = AsyncMock(side_effect=error)
    monkeypatch.setattr("clipfactory.workflow.production_stages.generate_script", generate)
    state: WorkflowState = {
        "run_id": str(run_id),
        "story_package_id": str(package_id),
        "attempt": 1,
        "trigger": "run_now",
    }
    await service.write_script(state)
    production.save_script.assert_not_called()
    artifact = production.save_artifact.call_args.args[3]
    assert artifact["passed"] is False
    assert artifact["draft"] == draft.model_dump(mode="json")
    assert artifact["story_package_id"] == str(package_id)
    production.latest_artifact.return_value = artifact
    service = ProductionStageService(
        production=production,
        runs=service.runs,
        assets=None,
        evaluations=service.evaluations,
        storage=None,
        llm=None,
        tts=None,
        transcription=None,
        media=None,
        clock=service.clock,
    )
    monkeypatch.setattr(
        service,
        "_run_context",
        AsyncMock(
            return_value=(
                run_id,
                2,
                {"settings_snapshot": {}},
                ContentProfile(),
            )
        ),
    )
    state["pending_actions"] = [{"instructions": error.detail}]
    await service.write_script(state)
    assert generate.call_args.kwargs["rejected_draft"] == draft
    assert generate.call_args.kwargs["rejected_codes"] == ["hook_too_long"]
    production.save_script.assert_not_called()
    production.latest_artifact.return_value = {**artifact, "story_package_id": str(uuid4())}
    await service.write_script(state)
    assert generate.call_args.kwargs["rejected_draft"] is None
    production.latest_artifact.return_value = artifact
    generate.side_effect = None
    generate.return_value = await generate_script(
        FakeLLM(draft),
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
    )
    production.save_script.return_value = 1
    await service.write_script(state)
    production.save_script.assert_called_once()
    assert production.save_artifact.call_args.args[3] == {"story_package_id": str(package_id), "passed": True}
    production.latest_artifact.return_value = production.save_artifact.call_args.args[3]
    await service.write_script(state)
    assert generate.call_args.kwargs["rejected_draft"] is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
async def test_duration_only_repairs_preserve_the_passing_hook(index: int) -> None:
    claims = _claims()
    draft = _result(claims)

    class RepairLLM(FakeLLM):
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
            assert schema is NarrationRepairResult
            return LLMResult(
                NarrationRepairResult.model_validate(
                    {
                        "corrections": [
                            {
                                "segment_index": index,
                                "text": draft.segments[index].text,
                                "attribution": None,
                            }
                        ]
                    }
                ),
                "fake",
                "repair-model",
            )

    async def repair() -> GeneratedScript:
        return await generate_script(
            RepairLLM(draft),
            story_title="Science",
            story_summary="Findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            rejected_draft=draft,
            rejected_codes=["script_too_short"],
            revision_instructions=["Expand body to meet duration"],
        )

    if index == 0:
        with pytest.raises(ScriptGateError, match="script_too_short") as rejected:
            await repair()
        assert "out-of-scope indexes" in rejected.value.detail
        assert rejected.value.draft == draft
    else:
        script = await repair()
        assert script.segments[0].text == draft.segments[0].text


@pytest.mark.unit
@pytest.mark.req("CF-REQ-155")
@pytest.mark.parametrize(("words", "rejected"), [(146, True), (147, False)])
def test_script_gate_counts_lead_in_and_tail_once(words: int, rejected: bool) -> None:
    from clipfactory.planning.script import _build_script

    claims = _claims()
    draft = _result(claims)
    hook = draft.segments[0].text
    filler = words - len(hook.split())
    per_segment = [filler // 3 + (1 if index < filler % 3 else 0) for index in range(3)]
    segments = [draft.segments[0]] + [
        segment.model_copy(update={"text": " ".join([word] * count) + "."})
        for segment, count, word in zip(draft.segments[1:], per_segment, ("Alpha", "Bravo", "Charlie"), strict=True)
    ]
    script = _build_script(draft.model_copy(update={"segments": segments}), ContentProfile(), 0.3, 1.0)
    assert script.word_count == words

    def gate() -> None:
        validate_script_gate(
            script,
            claims=claims,
            profile=ContentProfile(),
            min_segments=4,
            max_segments=8,
            hook_max_seconds=5,
            lead_in_seconds=0.3,
            tail_seconds=1.0,
        )

    if rejected:
        with pytest.raises(ScriptGateError) as caught:
            gate()
        assert "script_too_short" in caught.value.codes
    else:
        gate()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-263")
@pytest.mark.req("CF-REQ-400")
@pytest.mark.asyncio
async def test_ungrounded_optional_graphic_names_fallback_field_in_rewrite_instructions() -> None:
    claims = _claims()
    draft = _result(claims).model_dump(mode="json")
    draft["visuals"][1]["fallback_graphics_spec"] = {
        "template": "statistic",
        "title": {"text": "Verified claim number", "claim_ids": [str(claims[0].id)]},
        "item": {
            "label": {"text": "Verified claim number", "claim_ids": [str(claims[1].id)]},
            "value": 999,
        },
    }
    rejected = WriteScriptResult.model_validate(draft)
    llm = FakeLLM(rejected)

    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            llm,
            story_title="Science update",
            story_summary="A significant event.",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )

    assert caught.value.codes == ("unsupported_statement",)
    assert caught.value.draft == rejected
    assert "Visual 1 fallback_graphics_spec" in caught.value.detail
    assert "fallback_graphics_spec=null" in caught.value.detail
    assert "graphics_spec=null" in caught.value.detail
    assert "kind=media alone" in caught.value.detail
    assert rejected.visuals[1].fallback_graphics_spec is not None
    assert len(llm.calls) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-263")
@pytest.mark.req("CF-REQ-155")
@pytest.mark.asyncio
async def test_ungrounded_graphics_label_is_a_bounded_write_script_gate_not_a_run_failure() -> None:
    claims = _claims()
    draft = _result(claims).model_dump(mode="json")
    draft["visuals"][1] = {
        "objective": "Present the measured value",
        "media_type": "video",
        "category": "infographic",
        "kind": "infographic",
        "description": "Statistic",
        "graphics_spec": {
            "template": "statistic",
            "title": {"text": "Verified claim number", "claim_ids": [str(claims[0].id)]},
            "item": {
                "label": {"text": "A label truncated mid-word, theSa", "claim_ids": [str(claims[1].id)]},
                "value": 1,
            },
        },
    }
    llm = FakeLLM(WriteScriptResult.model_validate(draft))
    with pytest.raises(ScriptGateError) as gate:
        await generate_script(
            llm,
            story_title="Science update",
            story_summary="A significant event.",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert gate.value.codes == ("unsupported_statement",)
    assert gate.value.draft is not None
    assert "Visual 1" in gate.value.detail
    assert "copied verbatim" in gate.value.detail
    assert ISSUE_ROUTES["unsupported_statement"].target_stage == Stage.WRITE_SCRIPT
    assert len(llm.calls) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-163")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fillers", "repeated"),
    [
        (("", "", ""), False),
        ((" Investigators are working to determine the full sequence.", "", ""), False),
        (
            (
                " Investigators are working to determine the full sequence.",
                " investigators ARE working, to determine the full sequence!",
                "",
            ),
            True,
        ),
        ((" Police said more.", " Police said more.", ""), False),
    ],
)
async def test_repeated_narration_sentences_fail_the_script_gate(fillers: tuple[str, str, str], repeated: bool) -> None:
    claims = _claims()
    claims.append(
        claims[0].model_copy(
            update={"id": uuid4(), "text": "Investigators are working to determine the full sequence."}
        )
    )
    value = _result(claims).model_dump(mode="json")
    for segment, filler in zip(value["segments"][1:], fillers, strict=True):
        segment["text"] = segment["text"].rstrip(".") + "." + filler
    llm = FakeLLM(WriteScriptResult.model_validate(value))

    async def generate() -> GeneratedScript:
        return await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )

    if repeated:
        with pytest.raises(ScriptGateError) as caught:
            await generate()
        assert "repeated_sentence" in caught.value.codes
        assert "investigators are working to determine the full sequence" in caught.value.detail
        assert ISSUE_ROUTES["repeated_sentence"].action_type.value == "revise_script"
    else:
        script = await generate()
        assert script.segments


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_paraphrased_restatements_are_detected_but_distinct_facts_are_not() -> None:
    from clipfactory.planning.script import restated_sentences

    earlier = (
        "Only a felony conviction would make Paul ineligible to assume office when the police chief term "
        "begins on January first."
    )
    assert restated_sentences([earlier, "If convicted of a felony, Paul would be ineligible to assume office."]) == [
        ("If convicted of a felony, Paul would be ineligible to assume office.", earlier)
    ]
    assert restated_sentences([earlier, "The term for the police chief begins on January 1."])
    assert restated_sentences(
        ["The man was shot and wounded, but remained alive.", "The man was shot and wounded, but survived."]
    )
    assert not restated_sentences(
        [
            earlier,
            "Zachary LaCaze was the only other candidate who qualified for the November election.",
            "The allegations involve incidents from 2005 and 2006.",
        ]
    )
    assert not restated_sentences([earlier, earlier])
    court = (
        "Brazil's electoral court gave Meta forty-eight hours to explain whether it reduced the reach of those "
        "posts and to detail any irregularities."
    )
    restated = "The court asked Meta to clarify both the reach reduction and the reported irregularities."
    assert restated_sentences([court, restated]) == [(restated, court)]
    assert not restated_sentences(
        [court, "The campaign filed a formal complaint with the electoral court over the alleged blocks."]
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_synonym_restatement_of_the_same_claim_is_detected_by_claim_grounding() -> None:
    from clipfactory.planning.script import claim_restated_sentences, restated_sentences

    city_claims = [
        "Man City beat 10-man Liverpool 3-0 in first game after guilty verdict",
        "Erling Haaland, Jeremy Doku and Rayan Cherki score second half goals after Ryan Gravenberch sent off",
        "Victory reestablishes City\u2019s three-point lead at the top of the table",
    ]
    lead = "The win restored Manchester City's three-point lead at the top of the English Premier League table."
    summit = (
        "Manchester City now sit three points clear of their nearest rivals at the summit of the English Premier "
        "League."
    )
    city = [
        "Manchester City beat ten-man Liverpool three-nil.",
        lead,
        "Erling Haaland, Jeremy Doku and Rayan Cherki scored after Ryan Gravenberch was sent off.",
        summit,
    ]
    assert not restated_sentences(city)
    assert claim_restated_sentences(city, city_claims) == [(summit, lead)]

    massive = (
        "Democrats must “win by massive numbers” during November\u2019s federal midterm elections because Donald Trump "
        "and his Republican allies are bound to try to sow doubt about the integrity of the results, Democratic "
        "Senate candidate Abdul El-Sayed of Michigan said on Sunday."
    )
    stated = (
        "Abdul El-Sayed said Democrats must win by massive numbers in November's federal midterm elections because "
        "Donald Trump and his allies will try to sow doubt about the integrity of the results."
    )
    paraphrase = (
        "Abdul El-Sayed urged Democrats to secure a large victory in the upcoming federal midterms to offset "
        "Trump's attempts to undermine confidence in the results."
    )
    sayed = ["A Michigan Senate candidate says Democrats need a landslide.", stated, paraphrase]
    assert claim_restated_sentences(sayed, [massive]) == [(paraphrase, stated)]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_claim_grounded_restatement_spares_hook_elaboration_and_distinct_facts() -> None:
    from clipfactory.planning.script import claim_restated_sentences

    claims = [
        "The boss of Volkswagen has backed EU proposals to boost its domestic industry, arguing European carmakers "
        "need to be able to “compete under comparable conditions” with Chinese rivals.",
        "The proposals for the Made in Europe rules, formally known as the Industrial Accelerator Act, would limit "
        "subsidies and public procurement to products with a large proportion of their materials and manufacturing "
        "coming from within the EU.",
        "Germany\u2019s biggest carmaker has launched a brutal plan to cut as many as 100,000 jobs",
        "Volkswagen is exhibiting at the Paris show for the first time in 20 years.",
    ]
    narration = [
        "The boss of Volkswagen has backed proposals to boost domestic industry.",
        "According to The Guardian, he argued European carmakers need to be able to “compete under comparable "
        "conditions” with Chinese rivals.",
        "The proposals for the Made in Europe rules, formally known as the Industrial Accelerator Act, would limit "
        "subsidies and public procurement to products with a large proportion of their materials and manufacturing "
        "coming from within the EU.",
        "Germany\u2019s biggest carmaker has launched a brutal plan to cut as many as 100,000 jobs.",
        "Volkswagen is exhibiting at the Paris show for the first time in 20 years.",
    ]
    assert claim_restated_sentences(narration, claims) == []
    assert claim_restated_sentences(narration, []) == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_later_sentence_repeating_a_whole_earlier_hook_is_detected_but_adjacent_elaboration_is_not() -> None:
    from clipfactory.planning.script import restated_sentences

    hook = "Andy Burnham will publish all details of his City dealings."
    later = (
        "Andy Burnham has said he will publish all details of his dealings with Manchester City in his previous "
        "mayoral role after his intervention in support of the football club\u2019s owners raised eyebrows."
    )
    middle = [
        "The Premier League said an independent commission found City arranged sham commercial deals with sponsors.",
        "His intervention in support of Manchester City\u2019s owners has raised eyebrows.",
    ]
    assert restated_sentences([hook, *middle, later]) == [(later, hook)]
    assert restated_sentences([hook, later, middle[0]]) == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_closing_line_restating_a_finding_split_across_an_earlier_segment_is_detected() -> None:
    from clipfactory.planning.script import restated_sentences

    finding = [
        "Post-meal blood sugar spikes were lower when participants consumed the brazzein or brazzein and inulin "
        "versions.",
        "Compared with the sugar-sweetened version, the study showed this reduction.",
    ]
    closing = "The evidence shows brazzein can lower blood sugar spikes compared to sugar."
    other = "The reductions were most notable in participants with type two diabetes."
    assert not restated_sentences([*finding, other, closing])
    assert restated_sentences([*finding, other, closing], segment_indexes=[0, 0, 1, 2]) == [
        (closing, " ".join(finding))
    ]
    assert not restated_sentences([*finding, other], segment_indexes=[0, 0, 1])


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.asyncio
async def test_paraphrased_restatement_fails_the_script_gate_for_narration_revision() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] += " Researchers measured a large drop in regional ocean temperatures."
    value["segments"][2]["text"] += " Regional ocean temperatures dropped by a large measured amount, researchers said."
    llm = FakeLLM(WriteScriptResult.model_validate(value))

    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "repeated_sentence" in caught.value.codes
    assert "restates the earlier passage" in caught.value.detail


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-165")
def test_spoken_follow_requests_are_detected_but_news_uses_of_follow_are_not() -> None:
    from clipfactory.planning.script import spoken_calls_to_action

    pitches = [
        "Stay tuned for more updates on his health.",
        "Please follow our channel for further news on the pope\u2019s recovery and any Vatican announcements.",
        "We will continue to monitor the situation and report any developments.",
        "Investigators continue to piece together the motive, and we will bring you updates—follow for more news.",
        "Subscribe now for daily briefings.",
        "Viewers are invited to consider the implications for upcoming elections.",
        "The audience is encouraged to submit questions via social media during the broadcast.",
    ]
    news = [
        "Police followed the suspect for three blocks before the arrest.",
        "Officials will follow up with a formal report next week.",
        "Doctors told him to follow a strict diet after the surgery.",
        "The ministry said this account of events was inaccurate.",
        "Supporters began to like and comment on the court's statement within minutes.",
        "Residents are urged to stay indoors until the storm passes.",
    ]
    assert spoken_calls_to_action(pitches) == pitches
    assert spoken_calls_to_action(news) == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-165")
@pytest.mark.asyncio
async def test_spoken_follow_request_fails_the_script_gate_but_the_caption_keeps_its_invitation() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["social_metadata"]["description"] = "Verified findings explained. Follow for more news."
    llm = FakeLLM(WriteScriptResult.model_validate(value))
    script = await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
    )
    assert script.social_metadata.description.endswith("Follow for more news.")
    assert any("never asks viewers to follow" in message.content for message in llm.calls[0][1])

    value["segments"][-1]["text"] += " Please follow our channel for further news."
    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            FakeLLM(WriteScriptResult.model_validate(value)),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "spoken_call_to_action" in caught.value.codes
    assert "Please follow our channel" in caught.value.detail
    assert ISSUE_ROUTES["spoken_call_to_action"].action_type.value == "revise_script"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_filler_adverb_padding_is_detected_but_ordinary_emphasis_is_not() -> None:
    from clipfactory.planning.script import filler_padded_sentences

    stacked = (
        "Notably, clearly he noticeably impressively scored seven goals and made three assists during the encounter."
    )
    assert filler_padded_sentences([stacked]) == [stacked]
    assert filler_padded_sentences(["Salah has remarkably set a new record (truly impressive) in the league."])
    spread = [
        "Notably, the vote passed.",
        "Remarkably, turnout rose.",
        "The count was impressively fast.",
        "Truly, it was close.",
    ]
    assert filler_padded_sentences(spread) == spread
    assert not filler_padded_sentences(
        [
            "Karen Bass said the remarks were clearly irresponsible threats to the city's very safety.",
            'Zelenskyy clearly said it "looks absolutely terrible, truly remarkably bad" for Ukraine.',
            "Remarkably, turnout rose.",
        ]
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-304")
@pytest.mark.asyncio
async def test_filler_padding_fails_the_script_gate_for_narration_revision() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] += " Notably, researchers remarkably measured the drop."
    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            FakeLLM(WriteScriptResult.model_validate(value)),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "filler_padding" in caught.value.codes
    assert "add a different accepted fact" in caught.value.detail
    assert ISSUE_ROUTES["filler_padding"].action_type.value == "revise_script"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_spoken_stage_directions_are_detected_but_news_copy_is_not() -> None:
    from clipfactory.planning.script import spoken_stage_directions

    directions = [
        "Watch the action unfold.",
        "The camera pulls back to show the rally hall filled with attendees today.",
        "Proudly red hats and signs appear in the crowd under bright overhead lights.",
        "Final shot lingers on the stage as Trump waves and steps back.",
        "Crowd chants loudly.",
    ]
    assert spoken_stage_directions(directions) == directions
    assert not spoken_stage_directions(
        [
            "The crowd cheered as Trump spoke at the rally in Tennessee.",
            "Police used camera footage to identify the driver.",
            "The rally occurred on October 11, 2026, as reported by Al Jazeera.",
            'Critics called it "the final shot at reform" before the vote.',
        ]
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-304")
@pytest.mark.asyncio
async def test_stage_direction_fails_the_script_gate_for_narration_revision() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] += " The camera pulls back to show the laboratory."
    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            FakeLLM(WriteScriptResult.model_validate(value)),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "stage_direction" in caught.value.codes
    assert "director's note" in caught.value.detail
    assert ISSUE_ROUTES["stage_direction"].action_type.value == "revise_script"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_headline_fragments_are_detected_but_complete_sentences_are_not() -> None:
    from clipfactory.planning.script import headline_fragment

    # Live Run 48c3524d: the writer copied two live-blog headlines as segments 0 and 1.
    assert headline_fragment("Hanson-Young writes to Albanese govt after Hegseth comment")
    assert headline_fragment("Greens urge block of US execution livestream ")
    assert not headline_fragment("The Greens urged the government to block the livestream.")
    assert not headline_fragment("Will the left unite?")
    assert not headline_fragment('He said it was "a disgrace."')
    assert not headline_fragment("He called it \u201cunacceptable.\u201d")
    assert not headline_fragment("The vote is next week\u2026")
    assert headline_fragment("to do more to make sure it is safe.")
    assert headline_fragment("\u201cand the only answer is to stop.\u201d")
    assert not headline_fragment("iPhone sales fell 4% this quarter.")
    assert not headline_fragment("\u201cWe will act,\u201d the minister said.")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.asyncio
async def test_headline_fragment_fails_the_script_gate_for_narration_revision() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] = value["segments"][1]["text"].rstrip(".!? ")
    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            FakeLLM(WriteScriptResult.model_validate(value)),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "headline_fragment" in caught.value.codes
    assert "segment 1" in caught.value.detail
    assert ISSUE_ROUTES["headline_fragment"].action_type.value == "revise_script"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_unsupported_commentary_is_detected_but_grounded_paraphrase_is_not() -> None:
    from clipfactory.planning.script import unsupported_commentary

    # Live Run a811d673: accepted Claims and the padding the writer added around them.
    evidence = [
        "Trump claims Russia and Ukraine agree to stop attacks on energy infrastructure",
        "Trump announced he was lifting sanctions on Russian diesel exports.",
        "Trump warned that Zelenskyy should “damn well stop” hitting Russian refineries.",
        "More than 860,000 without power",
        "The suspect, 46, was arrested in 2026.",
        "The Guardian",
    ]
    padding = [
        "Observers view this as a notable shift.",
        "This underscores the delicate balance.",
        "Critics argue the decision may influence regional stability.",
        "Stakeholders remain wary of potential repercussions.",
        "The warning emerged during a public briefing.",
        "The international community monitors the evolving landscape.",
    ]
    assert unsupported_commentary(padding, evidence) == padding
    assert not unsupported_commentary(
        [
            "Trump claims Russia and Ukraine have agreed to stop attacks on energy infrastructure.",
            "He also announced lifting sanctions on Russian diesel exports.",
            "According to The Guardian, Trump warned Zelenskyy to stop hitting Russian refineries.",
            "More than eight hundred and sixty thousand customers are without power.",
            "The suspect is forty-six and was arrested in twenty twenty-six.",
            "Trump spoke.",
        ],
        evidence,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-304")
@pytest.mark.asyncio
async def test_unsupported_commentary_fails_the_script_gate_for_narration_revision() -> None:
    claims = _claims()
    value = _result(claims).model_dump(mode="json")
    value["segments"][1]["text"] += " Observers view this as a notable shift in the delicate balance."
    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            FakeLLM(WriteScriptResult.model_validate(value)),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert caught.value.codes == ("unsupported_commentary",)
    assert "no accepted Claim supports" in caught.value.detail
    assert ISSUE_ROUTES["unsupported_commentary"].action_type.value == "revise_script"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-263")
@pytest.mark.asyncio
async def test_invalid_graphics_in_writing_response_is_a_rewrite_gate_not_a_run_failure() -> None:
    from clipfactory.ports.errors import ProviderError

    claims = _claims()

    class GraphicsRejectingLLM(FakeLLM):
        async def generate_structured(self, task: str, messages: list[LLMMessage], schema: type[Any], **_: Any) -> Any:
            raise ProviderError(
                "unsupported_statement",
                "Invalid graphics data (visuals.3.graphics_spec.statistic.title.text)",
                transient=False,
            )

    with pytest.raises(ScriptGateError) as caught:
        await generate_script(
            GraphicsRejectingLLM(_result(claims)),
            story_title="Science update",
            story_summary="A significant event.",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert caught.value.codes == ("unsupported_statement",)
    assert "visuals.3.graphics_spec" in caught.value.detail
    assert caught.value.draft is None


class _NarrationRepairLLM(FakeLLM):
    def __init__(self, result: WriteScriptResult, corrections: list[dict[str, Any]]) -> None:
        super().__init__(result)
        self.corrections = corrections

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
        del model_role, images, temperature
        assert schema is NarrationRepairResult
        self.calls.append((task, messages))
        return LLMResult(
            NarrationRepairResult.model_validate({"corrections": self.corrections}), "fake", "repair-model"
        )


def _fragment_and_short_draft(claims: list[Claim]) -> WriteScriptResult:
    """Live Run a3c8b36b pattern: a hook copied from an incomplete Claim plus a body one word short."""
    draft = _result(claims)
    draft.segments[0].text = "A verified event is unfolding"
    draft.segments[3].text = draft.segments[3].text.split(". ", 2)[2]
    draft.segments[3].attribution = "Fixture Publisher"
    for segment in draft.segments[2:]:
        segment.claim_ids = [claims[1].id]
    return draft


@pytest.mark.unit
@pytest.mark.req("CF-REQ-153")
@pytest.mark.asyncio
async def test_writer_receives_every_accepted_claim_with_key_facts_first_and_marked() -> None:
    claims = _claims()
    rejected = claims[0].model_copy(update={"id": uuid4(), "status": ClaimStatus.REJECTED, "text": "Rejected rumour."})
    llm = FakeLLM(_result(claims))
    await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=[*claims, rejected],
        key_fact_claim_ids=[claims[2].id],
        profile=ContentProfile(),
    )
    payload = llm.calls[0][1][1].content.split("<untrusted-accepted-claims>\n")[1].split("\n</untrusted")[0]
    data = json.loads(payload)
    assert [item["claim_id"] for item in data] == [str(claims[2].id), str(claims[0].id), str(claims[1].id)]
    assert [item["key_fact"] for item in data] == [True, False, False]
    assert "Rejected rumour" not in payload
    assert "never by repeating a fact" in llm.calls[0][1][0].content


@pytest.mark.unit
@pytest.mark.req("CF-REQ-155")
@pytest.mark.req("CF-REQ-158")
@pytest.mark.asyncio
async def test_length_gate_instruction_states_the_word_budget_and_evidence_still_available() -> None:
    claims = _claims()
    draft = _result(claims)
    draft.segments[3].text = draft.segments[3].text.split(". ", 2)[2]
    for segment in draft.segments[2:]:
        segment.claim_ids = [claims[1].id]
    with pytest.raises(ScriptGateError) as short:
        await generate_script(
            FakeLLM(draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert short.value.codes == ("script_too_short",)
    assert "narration has 146 words" in short.value.detail
    assert "at least 147 words (1 more)" in short.value.detail
    assert "1 accepted Claims are not cited yet" in short.value.detail
    assert "never a restatement, filler or commentary" in short.value.detail

    draft.segments[3].claim_ids = [claims[2].id]
    with pytest.raises(ScriptGateError) as cited:
        await generate_script(
            FakeLLM(draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "Every accepted Claim is already cited" in cited.value.detail

    long_draft = _result(claims)
    long_draft.segments[2].text += " " + " ".join(f"Station {index} logged data." for index in range(12))
    with pytest.raises(ScriptGateError) as long:
        await generate_script(
            FakeLLM(long_draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
        )
    assert "script_too_long" in long.value.codes
    assert "allows at most 221 words" in long.value.detail


@pytest.mark.unit
@pytest.mark.req("CF-REQ-116")
@pytest.mark.req("CF-REQ-158")
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_narration_repair_recites_accepted_claims_and_keeps_required_attribution() -> None:
    claims = _claims()
    claims[2] = claims[2].model_copy(update={"support_level": SupportLevel.SINGLE_SOURCE})
    publishers = {claims[2].id: ["Fixture Publisher"]}
    draft = _fragment_and_short_draft(claims)
    with pytest.raises(ScriptGateError) as initial:
        await generate_script(
            FakeLLM(draft),
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            claim_publishers=publishers,
        )
    assert initial.value.codes == ("headline_fragment", "script_too_short")
    full_body = _result(claims).segments[3].text
    llm = _NarrationRepairLLM(
        draft,
        [
            {"segment_index": 0, "text": "A verified event is unfolding now."},
            # The model drops the attribution field (live Run bae1afee) while re-citing the Claims it now states.
            {"segment_index": 3, "text": full_body, "attribution": "", "claim_ids": [str(claims[2].id)] * 2},
        ],
    )
    script = await generate_script(
        llm,
        story_title="Science",
        story_summary="Verified findings",
        claims=claims,
        key_fact_claim_ids=[claim.id for claim in claims],
        profile=ContentProfile(),
        claim_publishers=publishers,
        rejected_draft=initial.value.draft,
        rejected_codes=initial.value.codes,
        revision_instructions=[initial.value.detail],
    )
    assert len(llm.calls) == 1
    assert script.segments[0].text == "A verified event is unfolding now."
    assert script.segments[3].text == full_body
    assert script.segments[3].claim_ids == (claims[2].id,)
    assert script.segments[3].attribution == "Fixture Publisher"
    assert script.segments[1].claim_ids == tuple(draft.segments[1].claim_ids)
    assert script.visuals == tuple(draft.visuals)
    assert script.social_metadata == draft.social_metadata
    system, _, request = llm.calls[0][1]
    assert "repair_narration.v2" in system.content
    assert "do not shift text between indexes" in system.content
    assert "return the shorter grounded narration instead of padding" in system.content
    assert "Current narration: 145 words; required: 147 to 221 words." in request.content
    assert '"segment_index": 3, "words": 21' in request.content
    assert f'Accepted Claim IDs not cited by any segment: ["{claims[2].id}"]' in request.content


@pytest.mark.unit
@pytest.mark.req("CF-REQ-159")
@pytest.mark.asyncio
async def test_narration_repair_citing_an_unaccepted_claim_is_rejected_and_the_draft_retained() -> None:
    claims = _claims()
    draft = _fragment_and_short_draft(claims)
    llm = _NarrationRepairLLM(
        draft,
        [{"segment_index": 3, "text": _result(claims).segments[3].text, "claim_ids": [str(uuid4())]}],
    )
    with pytest.raises(ScriptGateError) as rejected:
        await generate_script(
            llm,
            story_title="Science",
            story_summary="Verified findings",
            claims=claims,
            key_fact_claim_ids=[claim.id for claim in claims],
            profile=ContentProfile(),
            rejected_draft=draft,
            rejected_codes=["headline_fragment", "script_too_short"],
            revision_instructions=["Complete the hook and add one accepted fact"],
        )
    assert rejected.value.codes == ("headline_fragment", "script_too_short")
    assert "not an accepted Claim" in rejected.value.detail
    assert rejected.value.draft is draft
    assert f'Accepted Claim IDs not cited by any segment: ["{claims[2].id}"]' in llm.calls[0][1][2].content


@pytest.mark.unit
@pytest.mark.req("CF-REQ-159")
@pytest.mark.parametrize("text", ["", " ", "\n\t"])
def test_blank_narration_correction_is_schema_invalid(text: str) -> None:
    # Live Run a3c8b36b: a repair returned " " for a segment, silently deleting its narration.
    with pytest.raises(ValidationError):
        NarrationRepairResult.model_validate({"corrections": [{"segment_index": 1, "text": text}]})


@pytest.mark.unit
@pytest.mark.req("CF-REQ-158")
def test_possessive_s_does_not_ground_a_sentence_to_an_unrelated_claim() -> None:
    # Live Run a3c8b36b: "nation's" contributed a content word "s" that matched "Ukraine's", so a sentence about
    # injuries was reported as re-telling the railway-infrastructure Claim.
    evidence = [
        "There were blackouts in the city of Izyum after a Russian strike destroyed power grids, Ukraine's state "
        "news agency Ukrinform said, while energy and railway infrastructure in western Ukraine was also targeted.",
        "Zelensky said 33 people had been injured in the strikes on energy facilities across the country.",
    ]
    sentences = [
        "Ukrenergo introduced electricity rationing.",
        "There were blackouts in the city of Izyum after a Russian strike destroyed power grids.",
        "Energy and railway infrastructure in western Ukraine was also targeted overnight, according to Ukrinform.",
        "Zelensky said 33 people had been injured in the strikes on energy facilities across the country.",
        "He stated that the injuries resulted from attacks on the nation's energy infrastructure.",
    ]
    assert claim_restated_sentences(sentences, evidence) == []
    restated = "Railway and energy infrastructure in Ukraine's west was targeted overnight."
    assert claim_restated_sentences([*sentences, restated], evidence) == [(restated, sentences[2])]
