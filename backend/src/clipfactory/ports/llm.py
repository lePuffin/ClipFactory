"""Provider-neutral structured LLM port."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


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
        model_role: Literal["default", "evaluation"] = "default",
        images: list[ImageInput] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[T]: ...
