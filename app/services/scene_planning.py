"""LLM-assisted visual planning for a selected rough-reel script."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    ReelScript,
    ScenePlanning,
    SceneVisualType,
    SourceMaterial,
    StoryCandidate,
)
from app.models.source import ClipSourceType
from app.prompts.visual_planning import SYSTEM_PROMPT
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model


class ScenePlanner(Protocol):
    """Returns one visual proposal for each existing script section."""

    def plan(
        self,
        story: StoryCandidate,
        script: ReelScript,
        materials: Sequence[SourceMaterial],
    ) -> ScenePlanning: ...


class OpenRouterScenePlanner:
    """Requests source-specific visual choices through structured model output."""

    def __init__(self, settings: Settings) -> None:
        self.client = OpenRouterJSONClient(settings)

    def plan(
        self,
        story: StoryCandidate,
        script: ReelScript,
        materials: Sequence[SourceMaterial],
    ) -> ScenePlanning:
        selected_materials = [
            material for material in materials if material.source.id in set(story.source_ids)
        ]
        return self.client.generate(
            SYSTEM_PROMPT,
            build_visual_planning_payload(story, script, selected_materials),
            lambda content: validate_scene_planning(
                parse_json_model(content, ScenePlanning),
                script,
                story,
                selected_materials,
            ),
            maximum_tokens=3_000,
        )


def build_visual_planning_payload(
    story: StoryCandidate,
    script: ReelScript,
    materials: Sequence[SourceMaterial],
) -> dict[str, object]:
    """Expose only selected-story visuals and timestamped transcript ranges to the model."""
    return {
        "story": story.model_dump(mode="json"),
        "script_sections": [section.model_dump(mode="json") for section in script.sections],
        "visual_inventory": [
            {
                "source_id": material.source.id,
                "source_type": material.source.type,
                "duration": material.metadata.duration,
                "video_segments": [
                    {
                        "id": segment.id,
                        "text": segment.text[:1_500],
                        "start": segment.start,
                        "end": segment.end,
                    }
                    for segment in material.content.segments[:80]
                    if segment.start is not None and segment.end is not None
                ],
                "image_assets": [
                    asset.model_dump(mode="json") for asset in material.content.assets
                ],
            }
            for material in materials
        ],
    }


def validate_scene_planning(
    planning: ScenePlanning,
    script: ReelScript,
    story: StoryCandidate,
    materials: Sequence[SourceMaterial],
) -> ScenePlanning:
    """Validate LLM visual references before the selector or renderer sees them."""
    section_ids = {section.id for section in script.sections}
    proposed_ids = [scene.script_section_id for scene in planning.scenes]
    if len(proposed_ids) != len(set(proposed_ids)):
        raise LLMError("Visual planning returned duplicate script section IDs")
    if set(proposed_ids) != section_ids:
        raise LLMError("Visual planning must include exactly one scene for every script section")

    materials_by_id = {material.source.id: material for material in materials}
    selected_source_ids = set(story.source_ids)
    for proposal in planning.scenes:
        visual = proposal.visual
        if visual.type is SceneVisualType.TEXT_CARD:
            continue
        if visual.source_id not in selected_source_ids:
            raise LLMError("Visual planning referenced a source outside the selected story")
        material = materials_by_id.get(visual.source_id or "")
        if material is None:
            raise LLMError("Visual planning referenced an unavailable source")
        if visual.type is SceneVisualType.SOURCE_VIDEO:
            _validate_video_visual(material, visual.start, visual.end)
        else:
            _validate_image_visual(material, visual.type, visual.asset_id)
    return planning


def _validate_video_visual(
    material: SourceMaterial, start: float | None, end: float | None
) -> None:
    if material.source.type is not ClipSourceType.VIDEO:
        raise LLMError("A source video scene must reference a video source")
    if material.metadata.duration is None or start is None or end is None:
        raise LLMError("A source video scene requires known duration and timestamps")
    if start < 0 or end > material.metadata.duration or end <= start:
        raise LLMError("A source video scene has timestamps outside its source video")


def _validate_image_visual(
    material: SourceMaterial,
    visual_type: SceneVisualType,
    asset_id: str | None,
) -> None:
    asset = next((asset for asset in material.content.assets if asset.id == asset_id), None)
    if asset is None:
        raise LLMError("An image scene referenced an unknown source asset")
    expected_kind = (
        SceneVisualType.SOURCE_IMAGE
        if asset.kind.value == "source_image"
        else SceneVisualType.ARTICLE_IMAGE
    )
    if (
        asset.kind.value not in {"source_image", "article_image"}
        or visual_type is not expected_kind
    ):
        raise LLMError("An image scene used an incompatible visual asset type")
