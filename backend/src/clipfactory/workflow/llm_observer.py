"""Records every LLM call made inside a Run stage as Run Events and log lines."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMProvider, LLMResult
from clipfactory.workflow.graph import CURRENT_STAGE

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)
_EXCERPT_CHARS = 4_000


class RunEventWriter(Protocol):
    def append_event(
        self,
        run_id: UUID,
        event_type: str,
        message: str,
        *,
        stage: str | None = None,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class ObservedLLMProvider:
    def __init__(self, inner: LLMProvider, events: RunEventWriter) -> None:
        self._inner = inner
        self._events = events
        self.name = inner.name

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
        current = CURRENT_STAGE.get()
        prompt_chars = sum(len(message.content) for message in messages)
        await self._emit(
            current,
            "llm_call_started",
            f"Asking the LLM: {task} ({prompt_chars:,} prompt characters"
            + (f", {len(images)} images)" if images else ")"),
            {"task": task, "model_role": model_role, "prompt_chars": prompt_chars, "images": len(images or [])},
        )
        started = time.monotonic()
        try:
            result = await self._inner.generate_structured(
                task, messages, schema, model_role=model_role, images=images, temperature=temperature
            )
        except ProviderError as exc:
            elapsed = time.monotonic() - started
            await self._emit(
                current,
                "provider_call_failed",
                f"LLM {task} failed after {elapsed:.1f}s: {exc}",
                {
                    "port": "LLMProvider",
                    "provider": self.name,
                    "operation": task,
                    "error_code": exc.code,
                    "transient": exc.transient,
                    "call_retries": 0,
                    "duration_seconds": round(elapsed, 2),
                    "response": _excerpt(exc.detail),
                },
                level="error",
            )
            raise
        elapsed = time.monotonic() - started
        tokens = (
            f", {result.prompt_tokens:,} \u2192 {result.completion_tokens:,} tokens"
            if result.prompt_tokens is not None and result.completion_tokens is not None
            else ""
        )
        await self._emit(
            current,
            "llm_call_completed",
            f"LLM {task} answered by {result.model} in {elapsed:.1f}s{tokens}",
            {
                "task": task,
                "model": result.model,
                "duration_seconds": round(elapsed, 2),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "reasoning": _excerpt(result.reasoning),
                "response": _excerpt(result.raw_text or result.value.model_dump_json()),
            },
        )
        return result

    async def _emit(
        self,
        current: tuple[str, str] | None,
        event_type: str,
        message: str,
        payload: dict[str, Any],
        *,
        level: str = "info",
    ) -> None:
        context = {"run_id": current[0], "stage": current[1]} if current else {}
        logger.log(logging.ERROR if level == "error" else logging.INFO, message, extra=context)
        if payload.get("reasoning"):
            logger.debug("LLM reasoning: %s", payload["reasoning"], extra=context)
        if current is None:
            return
        try:
            await asyncio.to_thread(
                self._events.append_event,
                UUID(current[0]),
                event_type,
                message,
                stage=current[1],
                level=level,
                payload=payload,
            )
        except Exception:
            logger.warning("Could not record %s Run Event", event_type, exc_info=True, extra=context)


def _excerpt(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= _EXCERPT_CHARS else text[:_EXCERPT_CHARS] + "\u2026"
