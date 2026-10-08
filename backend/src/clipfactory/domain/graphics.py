"""Bounded declarative graphics and exact accepted-evidence grounding."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clipfactory.domain.models import Claim, ClaimStatus


class GraphicsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GraphicsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class GroundedText(GraphicsModel):
    text: str = Field(min_length=1, max_length=100)
    claim_ids: list[UUID] = Field(min_length=1, max_length=8)

    @field_validator("text")
    @classmethod
    def plain_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(not character.isprintable() for character in value):
            raise ValueError("graphics labels must contain printable non-empty text")
        if re.search(r"[<>{}`\\;$|&\n\r]|://|www\.|javascript:|data:|\b(?:eval|exec|import|fetch)\s*\(", value, re.I):
            raise ValueError("graphics accepts plain factual labels, not markup, code or URLs")
        return value


class DataItem(GraphicsModel):
    label: GroundedText
    value: float = Field(ge=-1e15, le=1e15)


class Statistic(GraphicsModel):
    template: Literal["statistic"]
    title: GroundedText
    item: DataItem


class Comparison(GraphicsModel):
    template: Literal["comparison"]
    title: GroundedText
    items: list[DataItem] = Field(min_length=2, max_length=6)


class TimelineEvent(GraphicsModel):
    date: GroundedText
    label: GroundedText


class Timeline(GraphicsModel):
    template: Literal["timeline"]
    title: GroundedText
    events: list[TimelineEvent] = Field(min_length=2, max_length=8)


class FunctionPlot(GraphicsModel):
    template: Literal["function_plot"]
    title: GroundedText
    function: Literal["linear", "quadratic", "sine", "cosine"]
    a: float = Field(default=1, ge=-1000, le=1000)
    b: float = Field(default=0, ge=-1000, le=1000)
    c: float = Field(default=0, ge=-1000, le=1000)
    x_min: float = Field(default=-5, ge=-100, le=100)
    x_max: float = Field(default=5, ge=-100, le=100)

    @model_validator(mode="after")
    def ordered_domain(self) -> Self:
        if self.x_min >= self.x_max:
            raise ValueError("function domain must be increasing")
        return self


class DiagramNode(GraphicsModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,24}$")
    label: GroundedText


class DiagramEdge(GraphicsModel):
    source: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,24}$")
    target: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,24}$")
    label: GroundedText


class RelationshipDiagram(GraphicsModel):
    template: Literal["relationship_diagram"]
    title: GroundedText
    nodes: list[DiagramNode] = Field(min_length=2, max_length=12)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def endpoints(self) -> Self:
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes) or any(
            edge.source not in ids or edge.target not in ids or edge.source == edge.target for edge in self.edges
        ):
            raise ValueError("diagram needs unique nodes and valid distinct edge endpoints")
        return self


GraphicsSpec = Annotated[
    Statistic | Comparison | Timeline | FunctionPlot | RelationshipDiagram, Field(discriminator="template")
]
VisualKind = Literal["media", "infographic", "scientific"]


def graphics_kind(spec: GraphicsSpec) -> VisualKind:
    return "infographic" if isinstance(spec, Statistic | Comparison | Timeline) else "scientific"


def validate_graphics_kind(kind: VisualKind, spec: GraphicsSpec | None) -> None:
    infographic = isinstance(spec, Statistic | Comparison | Timeline)
    scientific = isinstance(spec, FunctionPlot | RelationshipDiagram)
    if (
        (kind == "media" and spec is not None)
        or (kind == "infographic" and not infographic)
        or (kind == "scientific" and not scientific)
    ):
        raise GraphicsError("unsupported_graphics_template", "Visual kind and supported graphics template must match")


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def graphics_number(value: float) -> str:
    """Lossless shortest label, without insignificant decimal zeros."""
    return str(int(value)) if value.is_integer() else str(value)


def validate_graphics_claims(spec: GraphicsSpec, claims: Sequence[Claim]) -> None:
    evidence = {
        claim.id: [claim.text, *(item.excerpt for item in claim.evidence if item.verified)]
        for claim in claims
        if claim.status == ClaimStatus.ACCEPTED
    }

    def check(label: GroundedText, value: float | None = None) -> None:
        if any(claim_id not in evidence for claim_id in label.claim_ids):
            raise GraphicsError("unsupported_statement", "Graphics references an unknown or unaccepted Claim")
        texts = [_normalized(text) for claim_id in label.claim_ids for text in evidence[claim_id]]
        label_pattern = rf"(?<!\w){re.escape(_normalized(label.text))}(?!\w)"
        matching = [text for text in texts if re.search(label_pattern, text)]
        if not matching:
            raise GraphicsError("unsupported_statement", "Graphics label is absent from accepted evidence")
        if value is not None:
            numbers: list[Decimal] = []
            for text in matching:
                for label_match in re.finditer(label_pattern, text):
                    # A different item's number elsewhere in a Claim is not this
                    # label's value. Require a short, explicit evidence link.
                    following = text[label_match.end() :]
                    number_match = re.match(
                        r"\s*(?::|=|is|was|were|has|had|at|of|totaled|reached|rose to|fell to)?\s*"
                        r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:e[-+]?\d+)?)(?![\w,]|\.\d)",
                        following,
                    )
                    if number_match is not None:
                        numbers.append(Decimal(number_match[1].replace(",", "")))
            if Decimal(str(value)) not in numbers:
                raise GraphicsError("unsupported_statement", "Graphics value does not match its label evidence")

    check(spec.title)
    if isinstance(spec, Statistic):
        check(spec.item.label, spec.item.value)
    elif isinstance(spec, Comparison):
        for item in spec.items:
            check(item.label, item.value)
    elif isinstance(spec, Timeline):
        for event in spec.events:
            check(event.date)
            check(event.label)
    elif isinstance(spec, RelationshipDiagram):
        for node in spec.nodes:
            check(node.label)
        for edge in spec.edges:
            check(edge.label)


def sample_function(spec: FunctionPlot) -> tuple[tuple[float, float], ...]:
    samples: list[tuple[float, float]] = []
    for index in range(256):
        x = spec.x_min + (spec.x_max - spec.x_min) * index / 255
        match spec.function:
            case "linear":
                y = spec.a * x + spec.b
            case "quadratic":
                y = spec.a * x * x + spec.b * x + spec.c
            case "sine":
                y = spec.a * math.sin(spec.b * x + spec.c)
            case "cosine":
                y = spec.a * math.cos(spec.b * x + spec.c)
        samples.append((x, y))
    return tuple(samples)
