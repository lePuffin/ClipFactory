"""Typed LangGraph production workflow; nodes delegate to application use cases."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any, NotRequired, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from clipfactory.domain.models import Stage

logger = logging.getLogger(__name__)


class WorkflowState(TypedDict):
    run_id: str
    trigger: str
    story_id: NotRequired[str | None]
    story_fallbacks_used: NotRequired[int]
    story_package_id: NotRequired[str | None]
    story_package_version: NotRequired[int | None]
    attempt: NotRequired[int]
    revision_retries_used: NotRequired[int]
    pending_actions: NotRequired[list[dict[str, Any]]]
    reentry_stage: NotRequired[str | None]
    affected_segments: NotRequired[list[int]]
    clip_id: NotRequired[str | None]
    last_evaluation_ids: NotRequired[list[str]]
    outcome: NotRequired[str | None]


class StageExecutor(Protocol):
    async def execute(self, stage: Stage, state: WorkflowState) -> Mapping[str, Any]: ...

    async def evaluation_passed(self, state: WorkflowState) -> bool: ...


class StageObserver(Protocol):
    def start_stage(self, run_id: UUID, stage: str) -> Any: ...


class StageTimeout(TimeoutError):
    def __init__(self, stage: Stage) -> None:
        super().__init__(f"Stage {stage.value} exceeded its configured timeout")
        self.stage = stage


_STAGE_TIMEOUT_SECONDS: ContextVar[float] = ContextVar("stage_timeout_seconds", default=1800)
CURRENT_STAGE: ContextVar[tuple[str, str] | None] = ContextVar("current_stage", default=None)
_ACTIVE_STAGE_TIMEOUT: ContextVar[asyncio.Timeout | None] = ContextVar("active_stage_timeout", default=None)


def renew_generation_watchdog() -> None:
    timeout = _ACTIVE_STAGE_TIMEOUT.get()
    if timeout is not None and not timeout.expired():
        timeout.reschedule(asyncio.get_running_loop().time() + _STAGE_TIMEOUT_SECONDS.get())


def set_stage_timeout(seconds: float) -> Token[float]:
    return _STAGE_TIMEOUT_SECONDS.set(seconds)


def reset_stage_timeout(token: Token[float]) -> None:
    _STAGE_TIMEOUT_SECONDS.reset(token)


_PRODUCTION_STAGES = (
    Stage.GATHER_SOURCES,
    Stage.EXTRACT_CLAIMS,
    Stage.BUILD_STORY_PACKAGE,
    Stage.WRITE_SCRIPT,
    Stage.PLAN_VISUALS,
    Stage.SELECT_ASSETS,
    Stage.GENERATE_NARRATION,
    Stage.TRANSCRIBE_NARRATION,
    Stage.BUILD_CAPTIONS,
    Stage.COMPOSE_CLIP,
    Stage.VALIDATE_CLIP,
    Stage.EVALUATE_CLIP,
)
_REENTRY_STAGES = tuple(stage for stage in Stage if stage not in {Stage.PLAN_RETRY, Stage.PUBLISH})


def build_workflow(
    executor: StageExecutor,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    stage_observer: StageObserver | None = None,
):
    """Build a resumable workflow; persistence is supplied by the composition root."""
    graph = StateGraph(WorkflowState)

    async def route_entry(state: WorkflowState) -> dict[str, Any]:
        return {}

    async def route_evaluation(state: WorkflowState) -> str:
        return "publish" if await executor.evaluation_passed(state) else "plan_retry"

    async def route_gate(state: WorkflowState) -> str:
        return "continue" if await executor.evaluation_passed(state) else "plan_retry"

    graph.add_node("route_entry", route_entry)
    for stage in (
        Stage.RESEARCH,
        Stage.CLUSTER_STORIES,
        Stage.SELECT_STORY,
        Stage.INGEST_URL,
        *_PRODUCTION_STAGES,
        Stage.PLAN_RETRY,
        Stage.PUBLISH,
    ):
        graph.add_node(stage.value, _stage_node(executor, stage, stage_observer))

    graph.add_edge(START, "route_entry")
    graph.add_conditional_edges(
        "route_entry",
        lambda state: "ingest_url" if state["trigger"] == "manual_url" else "research",
        {"research": Stage.RESEARCH.value, "ingest_url": Stage.INGEST_URL.value},
    )
    graph.add_edge(Stage.RESEARCH.value, Stage.CLUSTER_STORIES.value)
    graph.add_edge(Stage.CLUSTER_STORIES.value, Stage.SELECT_STORY.value)
    graph.add_edge(Stage.SELECT_STORY.value, Stage.GATHER_SOURCES.value)
    graph.add_edge(Stage.INGEST_URL.value, Stage.GATHER_SOURCES.value)
    graph.add_edge(Stage.GATHER_SOURCES.value, Stage.EXTRACT_CLAIMS.value)
    graph.add_edge(Stage.EXTRACT_CLAIMS.value, Stage.BUILD_STORY_PACKAGE.value)
    graph.add_edge(Stage.BUILD_STORY_PACKAGE.value, Stage.WRITE_SCRIPT.value)
    graph.add_conditional_edges(
        Stage.WRITE_SCRIPT.value,
        route_gate,
        {"continue": Stage.PLAN_VISUALS.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_edge(Stage.PLAN_VISUALS.value, Stage.SELECT_ASSETS.value)
    graph.add_conditional_edges(
        Stage.SELECT_ASSETS.value,
        route_gate,
        {"continue": Stage.GENERATE_NARRATION.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_conditional_edges(
        Stage.GENERATE_NARRATION.value,
        route_gate,
        {"continue": Stage.TRANSCRIBE_NARRATION.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_edge(Stage.TRANSCRIBE_NARRATION.value, Stage.BUILD_CAPTIONS.value)
    graph.add_edge(Stage.BUILD_CAPTIONS.value, Stage.COMPOSE_CLIP.value)
    graph.add_conditional_edges(
        Stage.COMPOSE_CLIP.value,
        route_gate,
        {"continue": Stage.VALIDATE_CLIP.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_conditional_edges(
        Stage.VALIDATE_CLIP.value,
        route_gate,
        {"continue": Stage.EVALUATE_CLIP.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_conditional_edges(
        Stage.EVALUATE_CLIP.value,
        route_evaluation,
        {"publish": Stage.PUBLISH.value, "plan_retry": Stage.PLAN_RETRY.value},
    )
    graph.add_conditional_edges(
        Stage.PLAN_RETRY.value,
        lambda state: state.get("reentry_stage") if state.get("reentry_stage") else "end",
        {**{stage.value: stage.value for stage in _REENTRY_STAGES}, "end": END},
    )
    graph.add_edge(Stage.PUBLISH.value, END)
    return graph.compile(checkpointer=checkpointer)


def _stage_node(executor: StageExecutor, stage: Stage, observer: StageObserver | None):
    async def execute(state: WorkflowState) -> dict[str, Any]:
        context = {"run_id": state["run_id"], "stage": stage.value, "attempt": state.get("attempt")}
        if observer is not None:
            if inspect.iscoroutinefunction(observer.start_stage):
                await observer.start_stage(UUID(state["run_id"]), stage.value)
            else:
                await asyncio.to_thread(observer.start_stage, UUID(state["run_id"]), stage.value)
        logger.info("Stage %s started", stage.value, extra=context)
        started = time.monotonic()
        stage_token = CURRENT_STAGE.set((state["run_id"], stage.value))
        try:
            async with asyncio.timeout(_STAGE_TIMEOUT_SECONDS.get()) as timeout:
                watchdog_token = _ACTIVE_STAGE_TIMEOUT.set(timeout)
                try:
                    result = dict(await executor.execute(stage, state))
                finally:
                    _ACTIVE_STAGE_TIMEOUT.reset(watchdog_token)
        except TimeoutError as exc:
            logger.warning("Stage %s timed out", stage.value, extra=context)
            raise StageTimeout(stage) from exc
        except Exception as exc:
            logger.warning(
                "Stage %s failed after %.1fs: %s: %s",
                stage.value,
                time.monotonic() - started,
                type(exc).__name__,
                exc,
                extra=context,
                exc_info=logger.isEnabledFor(logging.DEBUG),
            )
            raise
        finally:
            CURRENT_STAGE.reset(stage_token)
        logger.info("Stage %s completed in %.1fs", stage.value, time.monotonic() - started, extra=context)
        return result

    return execute
