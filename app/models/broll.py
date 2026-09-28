"""Timeline models for source-video and placeholder clip visuals."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.media import VideoMetadata
from app.models.transcript import TranscriptSegment


class BRollKind(StrEnum):
    """The kind of visual rendered for a narration interval."""

    VIDEO = "video"
    PLACEHOLDER = "placeholder"


class BRollClip(BaseModel):
    """A validated source interval or generated placeholder on the narration timeline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: BRollKind
    sentence_index: int = Field(ge=0)
    timeline_start: float = Field(ge=0)
    timeline_end: float = Field(gt=0)
    source_id: str | None = Field(default=None, max_length=64)
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    visual_label: str = Field(min_length=1, max_length=180)

    @model_validator(mode="after")
    def validate_timeline_and_source(self) -> "BRollClip":
        if self.timeline_end <= self.timeline_start:
            raise ValueError("b-roll timeline end must be after its start")
        if self.kind is BRollKind.VIDEO:
            if self.source_id is None or self.source_start is None or self.source_end is None:
                raise ValueError("video b-roll requires a source interval")
            if self.source_end <= self.source_start:
                raise ValueError("b-roll source end must be after its start")
        elif any(
            value is not None for value in (self.source_id, self.source_start, self.source_end)
        ):
            raise ValueError("placeholder b-roll cannot include a source interval")
        return self

    @property
    def duration(self) -> float:
        return self.timeline_end - self.timeline_start


@dataclass(frozen=True, slots=True)
class VideoSourceContext:
    """Locally acquired video content available for b-roll selection and rendering."""

    source_id: str
    path: Path
    metadata: VideoMetadata
    transcript: tuple[TranscriptSegment, ...]
