"""Structured narration models for generated vertical clips."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScriptSentence(BaseModel):
    """One narration unit with an LLM-proposed duration and visual source hints."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(min_length=3, max_length=500)
    duration_seconds: float = Field(gt=0.5, le=30)
    broll_hint: str = Field(default="", max_length=180)
    source_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids cannot contain duplicates")
        for source_id in value:
            if not source_id or len(source_id) > 64:
                raise ValueError("source_ids must contain valid source identifiers")
        return value


class ClipScript(BaseModel):
    """A coherent narration plan produced from article and video source material."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=600)
    sentences: list[ScriptSentence] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_total_duration(self) -> "ClipScript":
        if self.planned_duration > 600:
            raise ValueError("script duration cannot exceed 10 minutes")
        return self

    @property
    def planned_duration(self) -> float:
        return sum(sentence.duration_seconds for sentence in self.sentences)


class NarrationTiming(BaseModel):
    """Measured timing for one synthesized sentence in the rendered WAV file."""

    sentence_index: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_time_range(self) -> "NarrationTiming":
        if self.end <= self.start:
            raise ValueError("narration timing end must be after start")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start