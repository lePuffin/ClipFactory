"""Cross-source grouping and explicit ranking of rough-reel story candidates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import SourceMaterial, StoryCandidate, StoryChoice, StoryGrouping
from app.prompts.story_candidate_generation import SYSTEM_PROMPT as GROUPING_PROMPT
from app.prompts.story_selection import SYSTEM_PROMPT as SELECTION_PROMPT
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model
from app.services.reel_validation import hydrate_story_candidate


class StorySelector(Protocol):
    """Groups analyzed sources, then selects the best candidate explicitly."""

    def group(self, materials: Sequence[SourceMaterial]) -> tuple[StoryCandidate, ...]: ...

    def select(self, stories: Sequence[StoryCandidate]) -> StoryCandidate: ...


class OpenRouterStorySelector:
    """Uses separate structured prompts for grouping and selection decisions."""

    def __init__(self, settings: Settings) -> None:
        self.client = OpenRouterJSONClient(settings)

    def group(self, materials: Sequence[SourceMaterial]) -> tuple[StoryCandidate, ...]:
        analyzed = [material for material in materials if material.analysis is not None]
        if not analyzed:
            raise LLMError("At least one successfully analyzed source is required")
        grouping = self.client.generate(
            GROUPING_PROMPT,
            build_story_grouping_payload(analyzed),
            lambda content: parse_json_model(content, StoryGrouping),
            maximum_tokens=4_000,
        )
        story_ids = [story.id for story in grouping.stories]
        if len(story_ids) != len(set(story_ids)):
            raise LLMError("Story grouping returned duplicate story IDs")
        return tuple(hydrate_story_candidate(story, analyzed) for story in grouping.stories)

    def select(self, stories: Sequence[StoryCandidate]) -> StoryCandidate:
        if not stories:
            raise LLMError("At least one story candidate is required")
        choice = self.client.generate(
            SELECTION_PROMPT,
            {"stories": [story.model_dump(mode="json") for story in stories]},
            lambda content: parse_json_model(content, StoryChoice),
            maximum_tokens=1_000,
        )
        stories_by_id = {story.id: story for story in stories}
        selected = stories_by_id.get(choice.story_id)
        if selected is None:
            raise LLMError("Story selection referenced an unknown candidate")
        return selected.model_copy(update={"selection_reason": choice.rationale})


def build_story_grouping_payload(materials: Sequence[SourceMaterial]) -> dict[str, object]:
    """Provide analyses plus bounded source excerpts for cross-source interpretation."""
    return {
        "sources": [
            {
                "id": material.source.id,
                "type": material.source.type,
                "name": material.source.name,
                "analysis": material.analysis.model_dump(mode="json")
                if material.analysis
                else None,
                "segments": [
                    {
                        "id": segment.id,
                        "text": segment.text[:2_000],
                        "start": segment.start,
                        "end": segment.end,
                    }
                    for segment in material.content.segments[:40]
                ],
                "assets": [asset.model_dump(mode="json") for asset in material.content.assets],
            }
            for material in materials
        ]
    }
