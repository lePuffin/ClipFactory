"""Normalized source records used by multi-source clip jobs."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClipSourceType(StrEnum):
    """The broad media category provided to a clip job."""

    VIDEO = "video"
    ARTICLE = "article"
    IMAGE = "image"


class ClipSourceOrigin(StrEnum):
    """How a source entered the local application."""

    UPLOAD = "upload"
    YOUTUBE = "youtube"
    ARTICLE_TEXT = "article_text"
    ARTICLE_URL = "article_url"


class Source(BaseModel):
    """A persisted, normalized source that never contains an arbitrary local path."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    type: ClipSourceType
    origin: ClipSourceOrigin
    name: str = Field(min_length=1, max_length=180)
    reference: str = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_type_and_origin(self) -> "Source":
        video_origins = {ClipSourceOrigin.UPLOAD, ClipSourceOrigin.YOUTUBE}
        article_origins = {ClipSourceOrigin.ARTICLE_TEXT, ClipSourceOrigin.ARTICLE_URL}
        image_origins = {ClipSourceOrigin.UPLOAD}
        if self.type is ClipSourceType.VIDEO and self.origin not in video_origins:
            raise ValueError("video sources must be uploads or YouTube URLs")
        if self.type is ClipSourceType.ARTICLE and self.origin not in article_origins:
            raise ValueError("article sources must be pasted text or article URLs")
        if self.type is ClipSourceType.IMAGE and self.origin not in image_origins:
            raise ValueError("image sources must be uploads")
        return self