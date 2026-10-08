from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.workflow.graph import CURRENT_STAGE
from clipfactory.workflow.llm_activity import ObservedLLMProvider


class Answer(BaseModel):
    answer: str


class Events:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def append_event(self, run_id: UUID, event_type: str, message: str, **kwargs: Any) -> dict[str, Any]:
        self.items.append({"run_id": run_id, "type": event_type, "message": message, **kwargs})
        return {}


class Governance:
    def __init__(self) -> None:
        self.started: list[tuple[UUID, str, str]] = []
        self.finished: list[tuple[UUID, str | None]] = []

    async def begin(self, run_id: UUID, task: str, role: str) -> UUID:
        request_id = uuid4()
        self.started.append((run_id, task, role))
        return request_id

    async def finish(self, request_id: UUID, result: Any, error_code: str | None) -> None:
        self.finished.append((request_id, error_code))


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


class FlakyLLM(InnerLLM):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.requests: list[list[LLMMessage]] = []

    async def generate_structured(self, task: str, messages: list[LLMMessage], schema: type[Any], **kwargs: Any):
        self.requests.append(messages)
        if len(self.requests) <= self.failures:
            raise ProviderError("llm_invalid_output", "Invalid JSON at column 1678", transient=False, detail="{cut")
        return await super().generate_structured(task, messages, schema, **kwargs)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-669")
@pytest.mark.asyncio
async def test_each_repair_attempt_is_accounted_before_and_after_dispatch() -> None:
    governance = Governance()
    run_id = uuid4()
    token = CURRENT_STAGE.set((str(run_id), "research"))
    try:
        result = await ObservedLLMProvider(FlakyLLM(failures=1), Events(), governance=governance).generate_structured(
            "extract_claims", [LLMMessage("user", "sources")], Answer
        )
    finally:
        CURRENT_STAGE.reset(token)

    assert result.value.answer == "ok"
    assert governance.started == [(run_id, "extract_claims", "default")] * 2
    assert [error for _, error in governance.finished] == ["llm_invalid_output", None]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_invalid_output_is_repaired_once_with_the_validation_error() -> None:
    events = Events()
    inner = FlakyLLM(failures=1)
    token = CURRENT_STAGE.set((str(uuid4()), "research"))
    try:
        result = await ObservedLLMProvider(inner, events).generate_structured(
            "extract_claims", [LLMMessage("user", "sources")], Answer
        )
    finally:
        CURRENT_STAGE.reset(token)

    assert result.value.answer == "ok"
    assert len(inner.requests) == 2
    assert "Invalid JSON at column 1678" in inner.requests[1][-1].content
    assert [item["type"] for item in events.items] == [
        "llm_call_started",
        "provider_call_failed",
        "llm_call_started",
        "llm_call_completed",
    ]
    assert events.items[1]["level"] == "warning"


@pytest.mark.unit
@pytest.mark.req("CF-NFR-010")
@pytest.mark.asyncio
@pytest.mark.parametrize(("transient", "failures", "expected_calls"), [(True, 1, 2), (True, 5, 3), (False, 1, 1)])
async def test_call_retries_are_bounded_and_only_transient(transient, failures, expected_calls) -> None:
    requests = []
    delays = []
    error = ProviderError("rate_limited", "Limited", transient=transient, retry_after_seconds=5)

    class LimitedLLM(InnerLLM):
        async def generate_structured(self, task, messages, schema, **kwargs):
            requests.append(messages)
            if len(requests) <= failures:
                raise error
            return await super().generate_structured(task, messages, schema, **kwargs)

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    provider = ObservedLLMProvider(
        LimitedLLM(), Events(), max_call_retries=2, call_retry_max_delay_seconds=5, sleep=record_delay
    )
    messages = [LLMMessage("user", "sources")]
    if transient and failures < 3:
        result = await provider.generate_structured("extract_claims", messages, Answer)
        assert result.value.answer == "ok"
    else:
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("extract_claims", messages, Answer)
        assert caught.value is error
    assert len(requests) == expected_calls
    assert delays == [5] * (expected_calls - 1)
    assert all(request == messages for request in requests)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_invalid_output_fails_after_the_repair_limit() -> None:
    inner = FlakyLLM(failures=2)
    with pytest.raises(ProviderError) as caught:
        await ObservedLLMProvider(inner, Events(), max_schema_repairs=1).generate_structured(
            "extract_claims", [LLMMessage("user", "sources")], Answer
        )
    assert caught.value.code == "llm_invalid_output"
    assert len(inner.requests) == 2
