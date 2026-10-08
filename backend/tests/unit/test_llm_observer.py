from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.workflow.graph import CURRENT_STAGE
from clipfactory.workflow.llm_observer import ObservedLLMProvider


class Answer(BaseModel):
    answer: str


class Events:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def append_event(self, run_id: UUID, event_type: str, message: str, **kwargs: Any) -> dict[str, Any]:
        self.items.append({"run_id": run_id, "type": event_type, "message": message, **kwargs})
        return {}


class InnerLLM:
    name = "fake"

    def __init__(self, error: ProviderError | None = None) -> None:
        self.error = error

    async def generate_structured(self, task: str, messages: list[LLMMessage], schema: type[Any], **kwargs: Any):
        if self.error:
            raise self.error
        return cast(
            LLMResult[Any],
            LLMResult(
                schema(answer="ok"),
                "fake",
                "unit-model",
                120,
                30,
                reasoning="Thinking it over",
                raw_text='{"answer":"ok"}',
            ),
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-853")
@pytest.mark.asyncio
async def test_llm_calls_inside_a_stage_become_run_events_with_reasoning_and_response() -> None:
    events = Events()
    run_id = uuid4()
    token = CURRENT_STAGE.set((str(run_id), "research"))
    try:
        await ObservedLLMProvider(InnerLLM(), events).generate_structured(
            "rank_stories", [LLMMessage("user", "hello")], Answer
        )
    finally:
        CURRENT_STAGE.reset(token)

    assert [item["type"] for item in events.items] == ["llm_call_started", "llm_call_completed"]
    completed = events.items[1]
    assert completed["run_id"] == run_id
    assert completed["stage"] == "research"
    assert "unit-model" in completed["message"]
    assert completed["payload"]["reasoning"] == "Thinking it over"
    assert completed["payload"]["response"] == '{"answer":"ok"}'
    assert completed["payload"]["completion_tokens"] == 30


@pytest.mark.unit
@pytest.mark.req("CF-REQ-853")
@pytest.mark.asyncio
async def test_failed_llm_call_emits_provider_call_failed_and_reraises() -> None:
    events = Events()
    error = ProviderError("llm_invalid_output", "bad schema", transient=False, detail="{broken")
    token = CURRENT_STAGE.set((str(uuid4()), "write_script"))
    try:
        with pytest.raises(ProviderError):
            await ObservedLLMProvider(InnerLLM(error), events).generate_structured(
                "write_script", [LLMMessage("user", "hello")], Answer
            )
    finally:
        CURRENT_STAGE.reset(token)

    failed = events.items[-1]
    assert failed["type"] == "provider_call_failed"
    assert failed["level"] == "error"
    assert failed["payload"]["error_code"] == "llm_invalid_output"
    assert failed["payload"]["response"] == "{broken"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-853")
@pytest.mark.asyncio
async def test_llm_calls_outside_a_run_emit_no_events() -> None:
    events = Events()
    await ObservedLLMProvider(InnerLLM(), events).generate_structured("probe", [LLMMessage("user", "hi")], Answer)
    assert not events.items
