"""Structured clip analysis and rendering models."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClipCandidate(BaseModel):
    """A timestamp range selected by semantic analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=600)
    title: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_time_range(self) -> "ClipCandidate":
        if self.end <= self.start:
            raise ValueError("clip end must be after its start")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class ClipAnalysis(BaseModel):
    """The strictly structured result expected from an LLM provider."""

    clips: list[ClipCandidate] = Field(min_length=1, max_length=30)


class RenderedClip(ClipCandidate):
    """A selected clip whose MP4 has been rendered."""

    filename: str = Field(min_length=1)


class ClipOutput(BaseModel):
    """Final artifact metadata for a managed composed clip."""

    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str = Field(min_length=5, max_length=180)
    title: str = Field(min_length=1, max_length=160)
    duration: float = Field(gt=0)
    source_count: int = Field(ge=1)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if value != "clip.mp4":
            raise ValueError("clip output must use the managed clip.mp4 filename")
        return value