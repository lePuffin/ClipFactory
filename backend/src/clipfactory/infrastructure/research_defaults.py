"""Shared starter configuration; publisher presets stay outside the domain."""

from typing import Any

from clipfactory.domain.models import ContentProfile, ResearchPolicy
from clipfactory.domain.research_policy import ResearchControls

STARTER_FEEDS = (
    ("BBC News - World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("The Guardian - World", "https://www.theguardian.com/world/rss"),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("NPR - World", "https://feeds.npr.org/1004/rss.xml"),
    ("Deutsche Welle - World", "https://rss.dw.com/rdf/rss-en-world"),
    ("France 24", "https://www.france24.com/en/rss"),
    ("The New York Times - World", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("CNN - World", "http://rss.cnn.com/rss/edition_world.rss"),
)


def research_defaults() -> dict[str, Any]:
    return ResearchControls(feeds=list(STARTER_FEEDS)).model_dump(mode="json")


def materialize_research(value: dict[str, Any], legacy: dict[str, Any]) -> dict[str, Any]:
    """Fill only absent keys; rerunning is safe and leaves explicit empties intact."""
    return {**value, "research": {**research_defaults(), **legacy, **value.get("research", {})}}


def new_profile_research(profile: ContentProfile) -> ContentProfile:
    explicit = profile.research.model_dump(mode="json", exclude_unset=True)
    research = ResearchPolicy.model_validate({**research_defaults(), **explicit})
    return profile.model_copy(update={"research": research})
