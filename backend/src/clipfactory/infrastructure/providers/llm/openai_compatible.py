"""Structured-output adapter for OpenAI-compatible chat-completion APIs."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from clipfactory.domain.graphics import GraphicsError
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMResult

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleLLMProvider:
    name = "openai_compatible"

    def __init__(
        self,
        settings: EnvironmentSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._client = client

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        model_role: Literal["default", "evaluation"] = "default",
        images: list[ImageInput] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[T]:
        api_key = self.settings.llm_api_key
        if api_key is None:
            raise ProviderError("not_configured", "LLM credentials are not configured", transient=False)
        model = self.settings.llm_model_evaluation if model_role == "evaluation" else None
        model = model or self.settings.llm_model
        wire_messages: list[dict[str, object]] = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        if images:
            last = wire_messages[-1]
            text_content = str(last["content"])
            last["content"] = [
                {"type": "text", "text": text_content},
                *[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode('ascii')}"
                        },
                    }
                    for image in images
                ],
            ]
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": wire_messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(task),
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        }
        client = self._client or httpx.AsyncClient(timeout=self.settings.llm_request_timeout_seconds)
        should_close = self._client is None
        try:
            async with asyncio.timeout(self.settings.llm_request_timeout_seconds):
                response = await client.post(
                    f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
                    json=payload,
                )
            if response.is_error:
                raise _provider_error(response, model, self.settings.llm_base_url, api_key.get_secret_value())
            body = response.json()
            if isinstance(body, dict) and body.get("error") and not body.get("choices"):
                # OpenRouter reports some upstream failures inside an HTTP 200 body.
                raise _provider_error(
                    _in_band_error_response(response, body),
                    model,
                    self.settings.llm_base_url,
                    api_key.get_secret_value(),
                )
            choice = body["choices"][0]
            message = choice["message"]
            content = message["content"]
            reasoning = message.get("reasoning") or message.get("reasoning_content")
            reasoning = reasoning if isinstance(reasoning, str) and reasoning.strip() else None
            truncated = (
                "; the answer was cut off at the model's output length limit"
                if choice.get("finish_reason") == "length"
                else ""
            )
            if not isinstance(content, str):
                raise ProviderError(
                    "llm_invalid_output",
                    "LLM returned no text JSON answer" + truncated,
                    transient=False,
                    detail=_answer_excerpt(reasoning) if reasoning else None,
                )
            try:
                value = schema.model_validate_json(content)
            except ValidationError as exc:
                if task == "write_script":
                    try:
                        raw = json.loads(content)
                    except json.JSONDecodeError:
                        raw = {}
                    visuals = raw.get("visuals", []) if isinstance(raw, dict) else []
                    graphics_errors = [
                        error
                        for error in exc.errors(include_url=False)
                        if "graphics_spec" in error["loc"]
                        or isinstance(error.get("ctx", {}).get("error"), GraphicsError)
                        or ("fallback_graphics_spec" in error["loc"])
                        or ("kind" in error["loc"] and "visuals" in error["loc"])
                        or (
                            len(error["loc"]) >= 2
                            and error["loc"][0] == "visuals"
                            and isinstance(error["loc"][1], int)
                            and isinstance(visuals, list)
                            and 0 <= error["loc"][1] < len(visuals)
                            and isinstance(visuals[error["loc"][1]], dict)
                            and visuals[error["loc"][1]].get("kind", "media") != "media"
                        )
                    ]
                    if graphics_errors:
                        code = (
                            "unsupported_graphics_template"
                            if any(
                                error["type"] in {"union_tag_invalid", "union_tag_not_found", "literal_error"}
                                or isinstance(error.get("ctx", {}).get("error"), GraphicsError)
                                for error in graphics_errors
                            )
                            else "unsupported_statement"
                        )
                        raise ProviderError(
                            code,
                            "Writing response contains invalid bounded graphics data; no schema repair allowed",
                            transient=False,
                        ) from exc
                problems = "; ".join(
                    f"{'.'.join(str(part) for part in error['loc']) or 'response'}: {error['msg']}"
                    for error in exc.errors(include_url=False)[:5]
                )
                raise ProviderError(
                    "llm_invalid_output",
                    f"LLM response for {task} did not match the requested schema ({problems}{truncated})",
                    transient=False,
                    detail=_answer_excerpt(content),
                ) from exc
            except ValueError as exc:
                raise ProviderError(
                    "llm_invalid_output",
                    f"LLM response for {task} was not valid JSON{truncated}",
                    transient=False,
                    detail=_answer_excerpt(content),
                ) from exc
            usage = body.get("usage") or {}
            cost = _reported_cost(body, usage)
            return LLMResult(
                value=value,
                provider=self.name,
                model=str(body.get("model") or model),
                prompt_tokens=_optional_int(usage.get("prompt_tokens")),
                completion_tokens=_optional_int(usage.get("completion_tokens")),
                reported_cost=cost,
                reasoning=reasoning,
                raw_text=content,
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ProviderError("timeout", "LLM request timed out", transient=True) from exc
        except httpx.NetworkError as exc:
            raise ProviderError("network_error", "LLM provider could not be reached", transient=True) from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                "invalid_response", "LLM provider returned an invalid response", transient=False
            ) from exc
        finally:
            if should_close:
                await client.aclose()


def _schema_name(task: str) -> str:
    safe = "".join(char if char.isalnum() or char in "_-" else "_" for char in task)
    return safe[:64] or "structured_output"


def _answer_excerpt(content: str) -> str:
    # Keep the tail too: JSON errors usually sit near the end of a truncated answer.
    if len(content) <= 4_000:
        return content
    return f"{content[:2_500]}\n…[{len(content) - 3_500:,} characters omitted]…\n{content[-1_000:]}"


_STATUS_HINTS = {
    400: "the request was rejected; the model may not support structured output (response_format json_schema)",
    401: "check LLM_API_KEY",
    402: "the provider account has insufficient credit",
    403: "the API key is not allowed to use this model; check LLM_API_KEY and provider account settings",
    404: "model or endpoint not found; check LLM_MODEL / LLM_MODEL_EVALUATION and LLM_BASE_URL, and that the model"
    " supports structured output",
    408: "the provider timed out; retry later",
    429: "rate limited by the provider; retry later or lower the request rate",
}
_PROVIDER_DETAIL_LIMIT = 300


def _in_band_error_response(response: httpx.Response, body: dict[str, Any]) -> httpx.Response:
    error = body.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    status_code = code if isinstance(code, int) and 400 <= code <= 599 else 502
    return httpx.Response(status_code, json=body, headers=response.headers)


def _provider_error(response: httpx.Response, model: str, base_url: str, api_key: str) -> ProviderError:
    status_code = response.status_code
    transient = status_code in {408, 429} or status_code >= 500
    code = "rate_limited" if status_code == 429 else f"http_{status_code}"
    host = urlparse(base_url).hostname or "configured endpoint"
    hint = _STATUS_HINTS.get(status_code, "provider-side error; retry later" if status_code >= 500 else None)
    message = f"LLM request failed with HTTP {status_code} from {host} for model '{model}'"
    if hint:
        message += f": {hint}"
    detail = _provider_detail(response, api_key)
    daily_markers = ("free-models-per-day", "daily limit", "daily quota", "requests per day")
    daily_exhausted = (
        status_code == 429 and detail is not None and any(marker in detail.casefold() for marker in daily_markers)
    )
    if daily_exhausted:
        code = "llm_budget_exhausted"
        transient = False
    if detail:
        message += f". Provider said: {detail}"
    retry_after = response.headers.get("Retry-After")
    retry_after_seconds = None
    if retry_after:
        try:
            retry_after_seconds = max(0.0, float(retry_after))
        except ValueError:
            with suppress(ValueError, TypeError, OverflowError):
                retry_after_seconds = max(0.0, (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds())
    return ProviderError(code, message, transient=transient, retry_after_seconds=retry_after_seconds)


def _provider_detail(response: httpx.Response, api_key: str) -> str | None:
    """Extract only the structured provider error message; raw bodies are never surfaced."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    text = error.get("message") if isinstance(error, dict) else error
    metadata = error.get("metadata") if isinstance(error, dict) else None
    raw = metadata.get("raw") if isinstance(metadata, dict) else None
    if isinstance(raw, str):
        with suppress(ValueError):
            nested = json.loads(raw)
            nested_error = nested.get("error", nested) if isinstance(nested, dict) else None
            nested_message = nested_error.get("message") if isinstance(nested_error, dict) else None
            if isinstance(nested_message, str) and nested_message.strip():
                text = f"{text}: {nested_message}" if isinstance(text, str) and text.strip() else nested_message
    if not isinstance(text, str) or not text.strip():
        return None
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = " ".join(text.split())
    if len(text) > _PROVIDER_DETAIL_LIMIT:
        text = text[: _PROVIDER_DETAIL_LIMIT - 1] + "…"
    return text


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _reported_cost(body: dict[str, object], usage: dict[str, object]) -> Decimal | None:
    candidates = (usage.get("cost"), body.get("cost"))
    for candidate in candidates:
        if isinstance(candidate, (int, float, str)):
            try:
                amount = Decimal(str(candidate))
            except InvalidOperation:
                continue
            if amount >= 0:
                return amount
    return None
