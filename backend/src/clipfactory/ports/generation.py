"""Provider-neutral video generation requests and provenance."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Protocol

from clipfactory.domain.graphics import GraphicsSpec

GenerationProgress = Callable[[str, dict[str, object]], Awaitable[None]]
GENERATION_ABORT: ContextVar[Event | None] = ContextVar("generation_abort", default=None)


@dataclass(frozen=True, slots=True)
class VideoGenerationRequest:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    duration_seconds: float
    seed: int
    graphics_spec: GraphicsSpec | None = None


@dataclass(frozen=True, slots=True)
class GeneratedMedia:
    path: Path
    model: str
    license: str
    parameters: dict[str, object]
    cost: Decimal = Decimal("0")


class VideoProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def estimate_cost(self, request: VideoGenerationRequest) -> Decimal: ...

    async def generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia: ...
