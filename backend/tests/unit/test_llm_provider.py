import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from clipfactory.infrastructure.providers.llm.openai_compatible import OpenAICompatibleLLMProvider, ProviderError
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.llm import LLMMessage


class Answer(BaseModel):
    answer: str


def settings(**overrides: object) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "development",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "LLM_API_KEY": "secret-test-key",
        "PUBLIC_MEDIA_BASE_URL": None,
        "MEDIA_URL_SIGNING_KEY": None,
    }
    values.update(overrides)
    return EnvironmentSettings(**values)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_openai_compatible_adapter_validates_structured_output() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-test-key"
        request_body = json.loads(request.content)
        assert request_body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(
            200,
            json={
                "model": "unit-model",
                "choices": [{"message": {"content": '{"answer":"verified"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "cost": 0.004},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    result = await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert result.value.answer == "verified"
    assert result.model == "unit-model"
    assert result.reported_cost == Decimal("0.004")


@pytest.mark.unit
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
async def test_provider_error_does_not_leak_response_body_or_secret() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(401, text="secret-test-key rejected"))
    )
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "http_401"
    assert not caught.value.transient
    assert "secret-test-key" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_truncated_invalid_json_is_reported_with_answer_tail() -> None:
    answer = '{"answer":"' + "x" * 5000
    body = {"choices": [{"message": {"content": answer}, "finish_reason": "length"}]}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "llm_invalid_output"
    assert "cut off at the model's output length limit" in str(caught.value)
    assert caught.value.detail is not None
    assert caught.value.detail.endswith("x" * 1000)
    assert "characters omitted" in caught.value.detail


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
async def test_provider_http_error_is_actionable_and_redacted() -> None:
    body = {"error": {"message": "No endpoints found for unit-model (key secret-test-key).", "code": 404}}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(404, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(LLM_MODEL="unit-model"), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    message = str(caught.value)
    assert caught.value.code == "http_404"
    assert "HTTP 404 from openrouter.ai for model 'unit-model'" in message
    assert "LLM_MODEL" in message
    assert "Provider said: No endpoints found for unit-model (key [redacted])." in message
    assert "secret-test-key" not in message


@pytest.mark.unit
@pytest.mark.req("CF-NFR-010")
@pytest.mark.asyncio
async def test_rate_limit_preserves_retry_after_seconds() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(429, headers={"Retry-After": "5"}, json={"error": {"message": "Limited"}})
        )
    )
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.transient
    assert caught.value.retry_after_seconds == 5


@pytest.mark.unit
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
async def test_nested_provider_message_is_preserved_without_raw_payload_or_credentials() -> None:
    body = {
        "error": {
            "message": "Provider returned error",
            "metadata": {
                "raw": json.dumps(
                    {
                        "error": {"message": "Too many images for key secret-test-key"},
                        "private_payload": "must-not-appear",
                    }
                )
            },
        }
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(400, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = OpenAICompatibleLLMProvider(settings(), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == "http_400"
    assert not caught.value.transient
    assert "Too many images for key [redacted]" in str(caught.value)
    assert "secret-test-key" not in str(caught.value)
    assert "must-not-appear" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_reasoning_only_output_is_a_repairable_schema_error() -> None:
    body = {"choices": [{"message": {"content": None, "reasoning": "Thinking"}, "finish_reason": "length"}]}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "llm_invalid_output"
    assert "output length limit" in str(caught.value)
    assert caught.value.detail == "Thinking"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.asyncio
async def test_daily_free_quota_error_is_non_retryable():
    body = {"error": {"message": "Rate limit exceeded: free-models-per-day"}}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(429, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "llm_budget_exhausted"
    assert not caught.value.transient


@pytest.mark.unit
@pytest.mark.req("CF-NFR-010")
@pytest.mark.asyncio
async def test_total_deadline_cancels_a_request_without_an_http_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout = asyncio.timeout
    deadlines: list[float | None] = []
    cancelled = False

    def expire_immediately(delay: float | None) -> asyncio.Timeout:
        deadlines.append(delay)
        return timeout(0)

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal cancelled
        try:
            await asyncio.Future()
            return httpx.Response(200)
        finally:
            cancelled = True

    monkeypatch.setattr(asyncio, "timeout", expire_immediately)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=600) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_REQUEST_TIMEOUT_SECONDS=240), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert deadlines == [240]
    assert cancelled
    assert caught.value.code == "timeout"
    assert caught.value.transient


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
async def test_in_band_error_in_http_200_body_is_reported_with_its_status() -> None:
    body = {"error": {"message": "This model is unavailable for free", "code": 404}, "user_id": "u"}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "http_404"
    assert not caught.value.transient
    assert "This model is unavailable for free" in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-NFR-010")
@pytest.mark.asyncio
async def test_in_band_upstream_error_without_status_is_transient() -> None:
    body = {"error": {"message": "Upstream provider error"}}
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)))
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "http_502"
    assert caught.value.transient
