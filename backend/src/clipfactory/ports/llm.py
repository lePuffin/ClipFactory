"""Provider-neutral structured LLM port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
LLMModelRole = Literal["default", "evaluation", "evaluation_fallback"]
# Evaluation-model failures that a configured evaluation fallback model may answer instead (CF-REQ-405, CF-REQ-219).
EVALUATION_FALLBACK_ERRORS = frozenset({"upstream_bad_request", "http_500", "http_502", "http_503"})


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ImageInput:
    data: bytes
    mime_type: Literal["image/jpeg", "image/png"]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResult[T]:
    value: T
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reported_cost: Decimal | None = None
    reasoning: str | None = None
    raw_text: str | None = None


class LLMProvider(Protocol):
    name: str

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        model_role: LLMModelRole = "default",
        images: list[ImageInput] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[T]: ...
