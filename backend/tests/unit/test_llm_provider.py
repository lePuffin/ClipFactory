import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from clipfactory.infrastructure.providers.llm.openai_compatible import OpenAICompatibleLLMProvider, ProviderError
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.llm import ImageInput, LLMMessage


class Answer(BaseModel):
    answer: str


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.req("CF-REQ-405")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt_json"])
@pytest.mark.parametrize("role", ["default", "evaluation", "evaluation_fallback"])
async def test_output_modes_preserve_schema_images_and_independent_roles(mode: str, role: Any) -> None:
    opposite = "prompt_json" if mode == "json_schema" else "json_schema"
    overrides = {
        "LLM_MODEL": "writer",
        "LLM_MODEL_EVALUATION": "vision",
        "LLM_MODEL_EVALUATION_FALLBACK": "fallback-vision",
        "LLM_OUTPUT_MODE": mode if role == "default" else opposite,
        "LLM_OUTPUT_MODE_EVALUATION": mode if role == "evaluation" else opposite,
        "LLM_OUTPUT_MODE_EVALUATION_FALLBACK": mode if role == "evaluation_fallback" else opposite,
    }
    messages = [LLMMessage("system", "Review candidates"), LLMMessage("user", "Compare supplied images")]
    original = list(messages)
    image = ImageInput(b"preview", "image/jpeg", {})

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert (
            payload["model"]
            == {"default": "writer", "evaluation": "vision", "evaluation_fallback": "fallback-vision"}[role]
        )
        assert payload["temperature"] == 0.2
        if mode == "json_schema":
            assert payload["response_format"] == {
                "type": "json_schema",
                "json_schema": {"name": "unit-task", "strict": True, "schema": Answer.model_json_schema()},
            }
            assert payload["messages"][0] == {"role": "system", "content": "Review candidates"}
        else:
            if mode == "json_object":
                assert payload["response_format"] == {"type": "json_object"}
            else:
                assert "response_format" not in payload
            instruction = payload["messages"][0]
            assert instruction["role"] == "system"
            assert "structured_output.v1" in instruction["content"]
            schema_text = instruction["content"].split("<output-json-schema>\n")[1].split("\n</output-json-schema>")[0]
            assert json.loads(schema_text) == Answer.model_json_schema()
            assert instruction["content"].endswith("\n\nReview candidates")
            assert [message["role"] for message in payload["messages"]] == ["system", "user"]
        assert payload["messages"][-1]["content"] == [
            {"type": "text", "text": "Compare supplied images"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,cHJldmlldw=="}},
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAICompatibleLLMProvider(settings(**overrides), client=client).generate_structured(
            "unit-task", messages, Answer, model_role=role, images=[image]
        )
    assert result.value.answer == "ok"
    assert result.raw_text == '{"answer":"ok"}'
    assert messages == original


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt_json"])
@pytest.mark.parametrize(
    "content",
    [
        '{"answer":',
        "{}",
        "```json\n{}\n```",
        'Text {"answer":"ok"}',
        'Before\n```json\n{"answer":"ok"}\n```',
        '```json\n{"answer":"ok"}\n```\nAfter',
        '```json\n{"answer":"ok"}\n```\n```json\n{"answer":"other"}\n```',
        '```json\n{"answer":\n```',
    ],
)
async def test_all_output_modes_reject_invalid_answers(mode: str, content: str) -> None:
    body = {"choices": [{"message": {"content": content}}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    ) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_OUTPUT_MODE=mode), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == "llm_invalid_output"
    assert caught.value.detail == content
    assert not caught.value.transient


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt_json"])
@pytest.mark.parametrize("label", ["json", ""])
async def test_whole_response_json_fence_is_only_unwrapped_in_non_strict_modes(mode: str, label: str) -> None:
    content = f'\n\n```{label}\n{{"answer":"ok"}}\n```\n'
    body = {"choices": [{"message": {"content": content}}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body))
    ) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_OUTPUT_MODE=mode), client=client)
        if mode == "json_schema":
            with pytest.raises(ProviderError) as caught:
                await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
            assert caught.value.code == "llm_invalid_output"
        else:
            result = await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
            assert result.value.answer == "ok"
            assert result.raw_text == content


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_name", "upstream", "expected_code"),
    [
        ("AtlasCloud", {"code": 400, "msg": "bad request", "request_id": "unit-id"}, "upstream_bad_request"),
        ("AtlasCloud", {"code": 400, "msg": "bad request"}, "upstream_bad_request"),
        ("Other", {"code": 400, "msg": "bad request"}, "http_400"),
        ("AtlasCloud", {"code": 400, "msg": "context length exceeded"}, "http_400"),
        ("AtlasCloud", {"code": 400, "msg": "content policy rejected"}, "http_400"),
        ("AtlasCloud", {"code": 400, "msg": "invalid schema"}, "http_400"),
        ("AtlasCloud", {"code": 400, "msg": "bad request", "reason": "content policy"}, "http_400"),
        ("AtlasCloud", {"code": 401, "msg": "bad request"}, "http_400"),
        ("AtlasCloud", {"code": 400, "msg": "secret-test-key invalid", "private_payload": "hidden"}, "http_400"),
    ],
)
async def test_only_precise_opaque_upstream_rejection_is_retryable(
    provider_name: str, upstream: dict[str, Any], expected_code: str
) -> None:
    body = {
        "error": {
            "code": 400,
            "message": "Provider returned error",
            "metadata": {"provider_name": provider_name, "raw": json.dumps(upstream)},
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json=body))
    ) as client:
        provider = OpenAICompatibleLLMProvider(settings(), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == expected_code
    assert caught.value.transient == (expected_code == "upstream_bad_request")
    assert str(upstream["msg"]).replace("secret-test-key", "[redacted]") in str(caught.value)
    assert "hidden" not in str(caught.value)
    assert "secret-test-key" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-670")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "message", "expected_code"),
    [
        ("openrouter/free", "Provider returned error", "free_router_upstream_rejection"),
        ("vendor/model:free", "Provider returned error", "http_400"),
        ("openrouter/free", "Invalid request: response_format unsupported", "http_400"),
    ],
)
async def test_only_opaque_free_router_rejection_is_reroutable(model: str, message: str, expected_code: str) -> None:
    """Regression: openrouter/free routed one review to an upstream that rejected it and the Run failed."""
    body = {"error": {"code": 400, "message": message, "metadata": {"provider_name": "Unknown"}}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(400, json=body))
    ) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_MODEL=model), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == expected_code
    assert caught.value.transient == (expected_code == "free_router_upstream_rejection")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_schema", "prompt_json"])
async def test_wire_messages_alternate_roles_for_strict_chat_templates(mode: str) -> None:
    """Regression: a schema repair sent system, user, user and a strict upstream rejected it with HTTP 400."""
    sent: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.extend(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_OUTPUT_MODE=mode), client=client)
        await provider.generate_structured(
            "unit-task",
            [LLMMessage("system", "rules"), LLMMessage("user", "question"), LLMMessage("user", "repair hint")],
            Answer,
            images=[ImageInput(b"jpeg", "image/jpeg", {})],
        )
    roles = [message["role"] for message in sent]
    assert roles == ["system", "user"]
    assert "rules" in sent[0]["content"]
    assert sent[1]["content"][0] == {"type": "text", "text": "question\n\nrepair hint"}
    assert sent[1]["content"][1]["type"] == "image_url"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-219")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail",
    [
        "Provider returned error: Failed to apply prompt replacement for mm_items['image'][1]",
        "At most 1 image(s) may be provided in one request.",
    ],
)
async def test_per_prompt_image_limit_is_not_retried_unchanged(detail: str) -> None:
    """Regression: a single-image free upstream returned 502s that were retried unchanged until the circuit opened."""
    body = {"error": {"code": 502, "message": detail}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(502, json=body))
    ) as client:
        provider = OpenAICompatibleLLMProvider(settings(), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == "image_limit"
    assert caught.value.transient is False


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
async def test_evaluation_mode_remains_independent_when_model_inherits_main() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "writer"
        assert "response_format" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OpenAICompatibleLLMProvider(
            settings(LLM_MODEL="writer", LLM_MODEL_EVALUATION=None, LLM_OUTPUT_MODE_EVALUATION="prompt_json"),
            client=client,
        )
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer, model_role="evaluation")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt_json"])
async def test_http_rejection_never_automatically_downgrades_output_mode(mode: str) -> None:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "Rejected"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OpenAICompatibleLLMProvider(settings(LLM_OUTPUT_MODE=mode), client=client)
        with pytest.raises(ProviderError) as caught:
            await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    assert caught.value.code == "http_400"
    assert not caught.value.transient
    assert len(requests) == 1


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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-655")
@pytest.mark.req("CF-NFR-111")
@pytest.mark.asyncio
async def test_gzip_compressed_in_band_error_is_reported_not_crashed_on_decode() -> None:
    import gzip
    import json

    body = {"error": {"message": "Provider returned error", "code": 429}}
    payload = gzip.compress(json.dumps(body).encode())
    headers = {"content-encoding": "gzip", "content-type": "application/json", "retry-after": "7"}
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload, headers=headers))
    )
    provider = OpenAICompatibleLLMProvider(settings(), client=client)
    with pytest.raises(ProviderError) as caught:
        await provider.generate_structured("unit-task", [LLMMessage("user", "hello")], Answer)
    await client.aclose()
    assert caught.value.code == "rate_limited"
    assert caught.value.transient
    assert "Provider returned error" in str(caught.value)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-758")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "mode", "expected"),
    [
        ("https://openrouter.ai/api/v1", "json_schema", {"require_parameters": True}),
        ("https://openrouter.ai/api/v1", "json_object", {"require_parameters": True}),
        ("https://openrouter.ai/api/v1", "prompt_json", None),
        ("http://localhost:8080/v1", "json_schema", None),
    ],
)
async def test_openrouter_routing_requires_endpoints_that_honour_the_output_contract(
    base_url: str, mode: str, expected: dict[str, bool] | None
) -> None:
    captured: dict[str, Any] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await OpenAICompatibleLLMProvider(
            settings(LLM_BASE_URL=base_url, LLM_MODEL="openrouter/free", LLM_OUTPUT_MODE=mode), client=client
        ).generate_structured("unit-task", [LLMMessage("user", "Answer")], Answer)
    assert captured.get("provider") == expected


@pytest.mark.unit
@pytest.mark.req("CF-REQ-405")
@pytest.mark.parametrize(
    ("evaluation", "fallback", "expected"),
    [("vision", "backup", "backup"), ("vision", None, "vision"), (None, None, "writer")],
)
def test_evaluation_fallback_role_selects_the_configured_fallback_model(
    evaluation: str | None, fallback: str | None, expected: str
) -> None:
    settings = EnvironmentSettings.model_validate(
        {"LLM_MODEL": "writer", "LLM_MODEL_EVALUATION": evaluation, "LLM_MODEL_EVALUATION_FALLBACK": fallback}
    )
    assert settings.model_for_role("evaluation_fallback") == expected
    assert settings.model_for_role("evaluation") == (evaluation or "writer")
    assert settings.model_for_role("default") == "writer"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-405")
def test_evaluation_fallback_defaults_to_prompt_json_transport() -> None:
    assert settings().llm_output_mode_evaluation_fallback == "prompt_json"
