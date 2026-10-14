"""Pure research controls shared by profiles and legacy snapshot resolution."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator, model_validator

PublisherQuality = Literal["high", "standard", "low", "blocked"]
Feed = tuple[
    Annotated[str, Field(min_length=1)],
    Annotated[str, Field(min_length=1, json_schema_extra={"format": "uri"})],
]


class ResearchSelectionWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_relevance: float = Field(default=0.30, ge=0, le=1, allow_inf_nan=False)
    newsworthiness: float = Field(default=0.25, ge=0, le=1, allow_inf_nan=False)
    independent_sources: float = Field(default=0.20, ge=0, le=1, allow_inf_nan=False)
    source_quality: float = Field(default=0.15, ge=0, le=1, allow_inf_nan=False)
    recency: float = Field(default=0.10, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> ResearchSelectionWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("selection weights must sum to 1")
        return self


class ResearchControls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feeds: list[Feed] = Field(default_factory=list)
    publisher_quality: dict[str, PublisherQuality] = Field(default_factory=dict)
    max_article_bytes: int = Field(default=5_000_000, gt=0)
    story_novelty_window_hours: int = Field(default=48, ge=0, le=2160)
    near_duplicate_threshold: float = Field(default=0.8, ge=0.5, le=1, allow_inf_nan=False)
    max_additional_sources: int = Field(default=5, ge=0, le=20)
    selection_weights: ResearchSelectionWeights = Field(default_factory=ResearchSelectionWeights)

    @field_validator("feeds")
    @classmethod
    def valid_feed_urls(cls, feeds: list[Feed]) -> list[Feed]:
        for publisher, url in feeds:
            if not publisher.strip():
                raise ValueError("feed publisher cannot be blank")
            parsed = TypeAdapter(HttpUrl).validate_python(url)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("feed URLs cannot contain credentials")
        return feeds
