"""Normalized article content used as a narrative source for clip jobs."""

from pydantic import BaseModel, ConfigDict, Field


class ArticleParagraph(BaseModel):
    """An addressable article paragraph retained for fact provenance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    text: str = Field(min_length=1, max_length=8_000)


class ArticleImage(BaseModel):
    """An article image URL and nearby descriptive text, when available."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    url: str = Field(min_length=1, max_length=2_048)
    alt_text: str = Field(default="", max_length=800)


class ArticleDocument(BaseModel):
    """Cleaned article text retained independently from its acquisition method."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=120, max_length=50_000)
    url: str | None = Field(default=None, max_length=2048)
    paragraphs: list[ArticleParagraph] = Field(default_factory=list, max_length=1_000)
    images: list[ArticleImage] = Field(default_factory=list, max_length=40)