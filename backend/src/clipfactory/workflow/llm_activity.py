"""Records every LLM call made inside a Run stage and re-asks once when the answer is unusable (CF-REQ-758)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from clipfactory.ports.errors import ProviderError
from clipfactory.ports.llm import ImageInput, LLMMessage, LLMProvider, LLMResult
from clipfactory.ports.llm_governance import LLMGovernance
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
    def __init__(
        self,
        inner: LLMProvider,
        events: RunEventWriter,
        *,
        max_schema_repairs: int = 1,
        max_call_retries: int = 3,
        call_retry_base_delay_seconds: float = 2,
        call_retry_max_delay_seconds: float = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        governance: LLMGovernance | None = None,
    ) -> None:
        self._inner = inner
        self._events = events
        self._max_schema_repairs = max_schema_repairs
        self._max_call_retries = max_call_retries
        self._retry_base_delay = call_retry_base_delay_seconds
        self._retry_max_delay = call_retry_max_delay_seconds
        self._sleep = sleep
        self._governance = governance
        self.name = inner.name

    def configure_retries(
        self,
        *,
        max_call_retries: int,
        call_retry_base_delay_seconds: float,
        call_retry_max_delay_seconds: float,
        llm_max_schema_repairs: int,
    ) -> None:
        self._max_call_retries = max_call_retries
        self._retry_base_delay = call_retry_base_delay_seconds
        self._retry_max_delay = call_retry_max_delay_seconds
        self._max_schema_repairs = llm_max_schema_repairs

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
        request = messages
        for repair in range(self._max_schema_repairs + 1):
            final = repair == self._max_schema_repairs
            try:
                for call_retry in range(self._max_call_retries + 1):
                    try:
                        return await self._call(
                            task,
                            request,
                            schema,
                            model_role=model_role,
                            images=images,
                            temperature=temperature,
                            repair=repair,
                            final=final,
                            call_retry=call_retry,
                        )
                    except ProviderError as exc:
                        if not exc.transient or call_retry == self._max_call_retries:
                            raise
                        delay = min(
                            self._retry_max_delay,
                            max(
                                self._retry_base_delay * 2**call_retry * (1 + random.SystemRandom().random()),
                                exc.retry_after_seconds or 0,
                            ),
                        )
                        await self._emit(
                            CURRENT_STAGE.get(),
                            "progress",
                            f"Retrying LLM {task} in {delay:.1f}s ({call_retry + 1}/{self._max_call_retries})",
                            {"task": task, "call_retries": call_retry + 1, "retry_delay_seconds": delay},
                        )
                        await self._sleep(delay)
            except ProviderError as exc:
                if exc.code != "llm_invalid_output" or final:
                    raise
                request = [
                    *messages,
                    LLMMessage(
                        "user",
                        f"Your previous answer could not be used: {exc}. Reply again with only one complete JSON "
                        "object that matches the schema. Keep every text field short so the whole answer fits.",
                    ),
                ]
        raise AssertionError("unreachable")

    async def _call(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        model_role: Literal["default", "evaluation"],
        images: list[ImageInput] | None,
        temperature: float,
        repair: int,
        final: bool,
        call_retry: int,
    ) -> LLMResult[T]:
        current = CURRENT_STAGE.get()
        prompt_chars = sum(len(message.content) for message in messages)
        label = f"{task} (repair {repair})" if repair else task
        await self._emit(
            current,
            "llm_call_started",
            f"Asking the LLM: {label} ({prompt_chars:,} prompt characters"
            + (f", {len(images)} images)" if images else ")"),
            {
                "task": task,
                "repair": repair,
                "model_role": model_role,
                "prompt_chars": prompt_chars,
                "images": len(images or []),
            },
        )
        started = time.monotonic()
        request_id = None
        try:
            if self._governance is not None:
                if current is None:
                    raise ProviderError("llm_governance_unavailable", "LLM request has no Run context", transient=False)
                request_id = await self._governance.begin(UUID(current[0]), task, model_role)
            result = await self._inner.generate_structured(
                task, messages, schema, model_role=model_role, images=images, temperature=temperature
            )
        except ProviderError as exc:
            if request_id is not None and self._governance is not None:
                await self._governance.finish(request_id, None, exc.code)
            elapsed = time.monotonic() - started
            repairing = exc.code == "llm_invalid_output" and not final
            retrying = exc.transient and call_retry < self._max_call_retries
            await self._emit(
                current,
                "provider_call_failed",
                f"LLM {label} failed after {elapsed:.1f}s: {exc}"
                + ("; asking the model to correct its answer" if repairing else "")
                + ("; will retry the same request" if retrying else ""),
                {
                    "port": "LLMProvider",
                    "provider": self.name,
                    "operation": task,
                    "error_code": exc.code,
                    "transient": exc.transient,
                    "call_retries": call_retry,
                    "repair": repair,
                    "duration_seconds": round(elapsed, 2),
                    "response": _excerpt(exc.detail),
                },
                level="warning" if retrying or repairing else "error",
            )
            raise
        if request_id is not None and self._governance is not None:
            await self._governance.finish(request_id, result, None)
        elapsed = time.monotonic() - started
        tokens = (
            f", {result.prompt_tokens:,} \u2192 {result.completion_tokens:,} tokens"
            if result.prompt_tokens is not None and result.completion_tokens is not None
            else ""
        )
        await self._emit(
            current,
            "llm_call_completed",
            f"LLM {label} answered by {result.model} in {elapsed:.1f}s{tokens}",
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
        logger.log(logging.getLevelNamesMapping().get(level.upper(), logging.INFO), message, extra=context)
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
