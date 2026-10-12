import asyncio
import json
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import BaseModel

from clipfactory.infrastructure.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
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

    async def begin(self, run_id: UUID, task: str, role: str, *, on_wait: Any = None) -> UUID:
        request_id = uuid4()
        self.started.append((run_id, task, role))
        return request_id

    async def finish(
        self, request_id: UUID, result: Any, error_code: str | None, *, retry_after_seconds: float | None = None
    ) -> None:
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
@pytest.mark.req("CF-REQ-667")
@pytest.mark.req("CF-REQ-853")
async def test_model_pacing_wait_is_visible_before_outbound_request() -> None:
    events = Events()

    class WaitingGovernance(Governance):
        async def begin(self, run_id: UUID, task: str, role: str, *, on_wait: Any = None) -> UUID:
            await on_wait("vendor/vision:free", 60)
            return await super().begin(run_id, task, role, on_wait=on_wait)

    token = CURRENT_STAGE.set((str(uuid4()), "select_assets"))
    try:
        await ObservedLLMProvider(InnerLLM(), events, governance=WaitingGovernance()).generate_structured(
            "review_media_candidates",
            [LLMMessage("user", "media")],
            Answer,
        )
    finally:
        CURRENT_STAGE.reset(token)
    assert [event["type"] for event in events.items] == ["llm_call_started", "progress", "llm_call_completed"]
    assert events.items[1]["payload"]["model"] == "vendor/vision:free"
    assert events.items[1]["payload"]["pacing_delay_seconds"] == 60
    assert "Waiting 60.0s" in events.items[1]["message"]


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
@pytest.mark.req("CF-REQ-670")
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcomes", "max_retries", "expected_calls", "succeeds"),
    [
        (["upstream_bad_request", "ok"], 3, 2, True),
        (["upstream_bad_request", "upstream_bad_request", "ok"], 3, 2, False),
        (["upstream_bad_request", "ok"], 0, 1, False),
        (["upstream_bad_request", "llm_invalid_output", "upstream_bad_request", "ok"], 3, 3, False),
    ],
)
async def test_opaque_upstream_retry_is_bounded_across_repairs_and_accounted(
    outcomes: list[str], max_retries: int, expected_calls: int, succeeds: bool
) -> None:
    class SequenceLLM(InnerLLM):
        calls = 0

        async def generate_structured(self, task, messages, schema, **kwargs):
            outcome = outcomes[self.calls]
            self.calls += 1
            if outcome != "ok":
                raise ProviderError(outcome, outcome, transient=outcome == "upstream_bad_request")
            return await super().generate_structured(task, messages, schema, **kwargs)

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    inner, governance, events = SequenceLLM(), Governance(), Events()
    provider = ObservedLLMProvider(
        inner, events, governance=governance, max_call_retries=max_retries, max_schema_repairs=1, sleep=sleep
    )
    token = CURRENT_STAGE.set((str(uuid4()), "evaluate_clip"))
    try:
        if succeeds:
            result = await provider.generate_structured("evaluate_clip", [LLMMessage("user", "test")], Answer)
            assert result.value.answer == "ok"
        else:
            with pytest.raises(ProviderError) as caught:
                await provider.generate_structured("evaluate_clip", [LLMMessage("user", "test")], Answer)
            assert caught.value.code == "upstream_bad_request"
    finally:
        CURRENT_STAGE.reset(token)
    assert inner.calls == len(governance.started) == len(governance.finished) == expected_calls
    assert len(sleeps) == (1 if max_retries > 0 else 0)
    failures = [e for e in events.items if e["type"] == "provider_call_failed"]
    if not succeeds:
        assert "will retry" not in failures[-1]["message"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcomes", "max_retries", "expected_calls", "succeeds"),
    [
        (["free_router_upstream_rejection"] * 3 + ["ok"], 3, 4, True),
        (["free_router_upstream_rejection"] * 4, 3, 4, False),
        (["free_router_upstream_rejection"] * 2 + ["ok"], 1, 2, False),
    ],
)
async def test_free_router_rejections_retry_only_within_configured_call_limit(
    outcomes: list[str], max_retries: int, expected_calls: int, succeeds: bool
) -> None:
    class SequenceLLM(InnerLLM):
        calls = 0

        async def generate_structured(self, task, messages, schema, **kwargs):
            outcome = outcomes[self.calls]
            self.calls += 1
            if outcome != "ok":
                raise ProviderError(outcome, outcome, transient=True)
            return await super().generate_structured(task, messages, schema, **kwargs)

    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    inner, governance, events = SequenceLLM(), Governance(), Events()
    provider = ObservedLLMProvider(
        inner, events, governance=governance, max_call_retries=max_retries, max_schema_repairs=0, sleep=sleep
    )
    token = CURRENT_STAGE.set((str(uuid4()), "select_assets"))
    try:
        if succeeds:
            result = await provider.generate_structured("review_media_candidates", [LLMMessage("user", "test")], Answer)
            assert result.value.answer == "ok"
        else:
            with pytest.raises(ProviderError) as caught:
                await provider.generate_structured("review_media_candidates", [LLMMessage("user", "test")], Answer)
            assert caught.value.code == "free_router_upstream_rejection"
    finally:
        CURRENT_STAGE.reset(token)
    assert inner.calls == len(governance.started) == len(governance.finished) == expected_calls
    assert len(sleeps) == min(max_retries, expected_calls - 1)
    if not succeeds:
        failures = [e for e in events.items if e["type"] == "provider_call_failed"]
        assert "will retry" not in failures[-1]["message"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.req("CF-REQ-669")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_object", "prompt_json"])
@pytest.mark.parametrize("succeeds", [True, False])
async def test_non_strict_transport_repairs_retain_mode_images_and_governance(mode: str, succeeds: bool) -> None:
    from clipfactory.ports.llm import ImageInput

    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        content = '{"answer":"ok"}' if succeeds and len(requests) == 2 else "{}"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    configured = EnvironmentSettings.model_validate(
        {
            "APP_ENV": "development",
            "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:5432/test",
            "LLM_API_KEY": "test-key",
            "LLM_OUTPUT_MODE_EVALUATION": mode,
        }
    )
    events, governance = Events(), Governance()
    token = CURRENT_STAGE.set((str(uuid4()), "select_assets"))
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = ObservedLLMProvider(
                OpenAICompatibleLLMProvider(configured, client=client),
                events,
                governance=governance,
                max_schema_repairs=1,
                max_call_retries=0,
            )
            if succeeds:
                result = await provider.generate_structured(
                    "review_media_candidates",
                    [LLMMessage("user", "Review")],
                    Answer,
                    model_role="evaluation",
                    images=[ImageInput(b"preview", "image/png", {})],
                )
                assert result.value.answer == "ok"
            else:
                with pytest.raises(ProviderError, match="did not match the requested schema") as caught:
                    await provider.generate_structured(
                        "review_media_candidates",
                        [LLMMessage("user", "Review")],
                        Answer,
                        model_role="evaluation",
                        images=[ImageInput(b"preview", "image/png", {})],
                    )
                assert caught.value.code == "llm_invalid_output"
    finally:
        CURRENT_STAGE.reset(token)
    assert len(requests) == len(governance.started) == len(governance.finished) == 2
    assert [error for _, error in governance.finished] == [
        "llm_invalid_output",
        None if succeeds else "llm_invalid_output",
    ]
    assert all(role == "evaluation" for _, _, role in governance.started)
    for request in requests:
        if mode == "prompt_json":
            assert "response_format" not in request
        else:
            assert request["response_format"] == {"type": "json_object"}
        assert "structured_output.v1" in request["messages"][0]["content"]
    assert requests[0]["messages"][-1]["content"][-1] == requests[1]["messages"][-1]["content"][-1]
    assert "answer: Field required" in requests[1]["messages"][-1]["content"][0]["text"]


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
@pytest.mark.req("CF-REQ-670")
@pytest.mark.req("CF-REQ-669")
@pytest.mark.parametrize(("maximum", "hint"), [(60, None), (120, None), (60, 0)])
async def test_unhinted_rate_limit_waits_full_cooldown_and_rechecks_governance(maximum, hint) -> None:
    requests, delays = [], []
    events, governance = Events(), Governance()
    error = ProviderError("rate_limited", "Provider returned error", transient=True, retry_after_seconds=hint)

    class LimitedLLM(InnerLLM):
        async def generate_structured(self, task, messages, schema, **kwargs):
            requests.append(messages)
            if len(requests) == 1:
                raise error
            return await super().generate_structured(task, messages, schema, **kwargs)

    async def record_delay(seconds: float) -> None:
        assert len(requests) == len(governance.started) == 1
        delays.append(seconds)

    provider = ObservedLLMProvider(
        LimitedLLM(), events, governance=governance, call_retry_max_delay_seconds=maximum, sleep=record_delay
    )
    token = CURRENT_STAGE.set((str(uuid4()), "select_assets"))
    try:
        result = await provider.generate_structured("review_media_candidates", [LLMMessage("user", "media")], Answer)
    finally:
        CURRENT_STAGE.reset(token)
    assert result.value.answer == "ok"
    assert delays == [maximum]
    assert len(requests) == len(governance.started) == 2
    assert [error_code for _, error_code in governance.finished] == ["rate_limited", None]
    progress = next(event for event in events.items if event["type"] == "progress")
    assert progress["payload"]["error_code"] == "rate_limited"
    assert progress["payload"]["retry_delay_seconds"] == maximum
    assert "rate-limit cooldown" in progress["message"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.parametrize(("hint", "maximum", "expected"), [(5, 60, 5), (90, 120, 90), (900, 120, 120)])
async def test_rate_limit_honours_positive_provider_hint_up_to_saved_cap(hint, maximum, expected) -> None:
    calls, delays = [], []

    class LimitedLLM(InnerLLM):
        async def generate_structured(self, task, messages, schema, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise ProviderError("rate_limited", "Limited", transient=True, retry_after_seconds=hint)
            return await super().generate_structured(task, messages, schema, **kwargs)

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    provider = ObservedLLMProvider(LimitedLLM(), Events(), sleep=record_delay)
    provider.configure_retries(
        max_call_retries=1,
        call_retry_base_delay_seconds=2,
        call_retry_max_delay_seconds=maximum,
        llm_max_schema_repairs=1,
    )
    await provider.generate_structured("review_media_candidates", [LLMMessage("user", "media")], Answer)
    assert delays == [expected]
    assert len(calls) == 2


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.parametrize(
    ("code", "transient", "expected_calls", "expected_delays"),
    [("rate_limited", True, 3, [60, 60]), ("llm_budget_exhausted", False, 1, []), ("http_400", False, 1, [])],
)
async def test_cooldown_remains_bounded_and_does_not_retry_daily_or_invalid_requests(
    code, transient, expected_calls, expected_delays
) -> None:
    calls, delays = [], []
    error = ProviderError(code, "Rejected", transient=transient)

    class FailingLLM(InnerLLM):
        async def generate_structured(self, *args, **kwargs):
            calls.append(1)
            raise error

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    with pytest.raises(ProviderError) as caught:
        await ObservedLLMProvider(FailingLLM(), Events(), max_call_retries=2, sleep=record_delay).generate_structured(
            "review_media_candidates", [LLMMessage("user", "media")], Answer
        )
    assert caught.value is error
    assert len(calls) == expected_calls
    assert delays == expected_delays


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
async def test_cancelling_rate_limit_cooldown_does_not_dispatch_again() -> None:
    calls = []

    class LimitedLLM(InnerLLM):
        async def generate_structured(self, *args, **kwargs):
            calls.append(1)
            raise ProviderError("rate_limited", "Limited", transient=True)

    async def cancel_sleep(seconds: float) -> None:
        assert seconds == 60
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await ObservedLLMProvider(LimitedLLM(), Events(), sleep=cancel_sleep).generate_structured(
            "review_media_candidates", [LLMMessage("user", "media")], Answer
        )
    assert len(calls) == 1


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
