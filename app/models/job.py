"""Processing job models persisted for browser polling and debugging."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.clip import ClipOutput, RenderedClip
from app.models.reel import NarrationRequest, ReelOutput
from app.models.source import Source


class JobStatus(StrEnum):
    CREATED = "CREATED"
    INGESTING = "INGESTING"
    ACQUIRING = "ACQUIRING"
    EXTRACTING = "EXTRACTING"
    TRANSCRIBING = "TRANSCRIBING"
    ANALYZING = "ANALYZING"
    STORY_SELECTING = "STORY_SELECTING"
    SCRIPTING = "SCRIPTING"
    PLANNING = "PLANNING"
    SYNTHESIZING = "SYNTHESIZING"
    ASSEMBLING = "ASSEMBLING"
    COMPOSING = "COMPOSING"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobRecord(BaseModel):
    """A local, JSON-serializable processing job."""

    id: str
    job_type: Literal["standard", "clip", "reel"] = "standard"
    source_type: Literal["upload", "youtube", "clip", "reel"]
    source_name: str
    requested_clip_count: int = Field(default=5, ge=1, le=10)
    sources: list[Source] = Field(default_factory=list)
    status: JobStatus = JobStatus.CREATED
    progress: int = Field(default=0, ge=0, le=100)
    current_step: str = "Queued"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error: str | None = None
    clips: list[RenderedClip] = Field(default_factory=list)
    clip: ClipOutput | None = None
    reel: ReelOutput | None = None
    narration_request: NarrationRequest | None = None

    @model_validator(mode="after")
    def validate_job_variant(self) -> "JobRecord":
        if self.job_type == "clip":
            if self.source_type != "clip":
                raise ValueError("clip jobs must use the clip source type")
            if not self.sources:
                raise ValueError("clip jobs require at least one source")
            if len({source.id for source in self.sources}) != len(self.sources):
                raise ValueError("clip job source IDs must be unique")
        elif self.job_type == "reel":
            if self.source_type != "reel":
                raise ValueError("reel jobs must use the reel source type")
            if not self.sources:
                raise ValueError("reel jobs require at least one source")
            if len({source.id for source in self.sources}) != len(self.sources):
                raise ValueError("reel job source IDs must be unique")
        elif self.source_type in {"clip", "reel"}:
            raise ValueError("standard jobs cannot use a managed multi-source type")
        if self.narration_request is not None and not self.is_reel():
            raise ValueError("only reel jobs can request v0.5 narration")
        return self

    def is_clip(self) -> bool:
        return self.job_type == "clip"

    def is_reel(self) -> bool:
        return self.job_type == "reel"