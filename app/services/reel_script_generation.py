"""Provenance-preserving short-form script generation for selected stories."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    EditorialAngle,
    HookCandidate,
    ReelScript,
    ScriptSectionRole,
    SourceMaterial,
    StoryCandidate,
)
from app.prompts.reel_script import SYSTEM_PROMPT as LEGACY_SCRIPT_PROMPT
from app.prompts.script_generation import SYSTEM_PROMPT as SCRIPT_GENERATION_PROMPT
from app.prompts.script_validation import SYSTEM_PROMPT as SCRIPT_VALIDATION_PROMPT
from app.prompts.visual_intent import VISUAL_INTENT_REQUIREMENTS
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model
from app.services.reel_validation import hydrate_reel_script
from app.services.script_validation import validate_editorial_script

_MAXIMUM_EDITORIAL_SECTIONS = 6
_MAXIMUM_SECTION_DURATION_SECONDS = 30
_MAXIMUM_REPAIR_ASSETS = 24
_MAXIMUM_EDITORIAL_SCRIPT_REPAIR_ATTEMPTS = 3


class ReelScriptGenerator(Protocol):
    """Generates a validated rough-reel script from one selected story."""

    def generate(
        self,
        story: StoryCandidate,
        materials: Sequence[SourceMaterial],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
        angle: EditorialAngle | None = None,
        hook: HookCandidate | None = None,
    ) -> ReelScript: ...


class OpenRouterReelScriptGenerator:
    """Requests an evidence-backed script through the existing OpenRouter configuration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenRouterJSONClient(settings)

    def generate(
        self,
        story: StoryCandidate,
        materials: Sequence[SourceMaterial],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
        angle: EditorialAngle | None = None,
        hook: HookCandidate | None = None,
    ) -> ReelScript:
        if (angle is None) != (hook is None):
            raise ValueError("Editorial script generation requires both a selected angle and hook")
        if angle is None or hook is None:
            return self._generate_legacy_script(
                story,
                materials,
                minimum_duration_seconds,
                maximum_duration_seconds,
            )

        payload = build_editorial_script_payload(
            story,
            angle,
            hook,
            materials,
            minimum_duration_seconds,
            maximum_duration_seconds,
            self.settings.reel_words_per_minute,
        )
        script = _canonicalize_editorial_hook(
            self.client.generate(
                f"{SCRIPT_GENERATION_PROMPT}\n\n{VISUAL_INTENT_REQUIREMENTS}",
                payload,
                parse_editorial_reel_script,
                maximum_tokens=self.settings.llm_script_max_tokens,
            ),
            hook,
        )
        for repair_attempt in range(_MAXIMUM_EDITORIAL_SCRIPT_REPAIR_ATTEMPTS + 1):
            try:
                return validate_editorial_script(
                    script,
                    story,
                    angle,
                    hook,
                    materials,
                    minimum_duration_seconds,
                    maximum_duration_seconds,
                    self.settings.reel_words_per_minute,
                ).script
            except LLMError as error:
                if repair_attempt == _MAXIMUM_EDITORIAL_SCRIPT_REPAIR_ATTEMPTS:
                    raise
                script = _canonicalize_editorial_hook(
                    self.client.generate(
                        SCRIPT_VALIDATION_PROMPT,
                        build_editorial_script_repair_payload(
                            story,
                            angle,
                            hook,
                            materials,
                            script,
                            error,
                            minimum_duration_seconds,
                            maximum_duration_seconds,
                            self.settings.reel_words_per_minute,
                        ),
                        parse_editorial_reel_script,
                        maximum_tokens=self.settings.llm_script_max_tokens,
                    ),
                    hook,
                )

        raise AssertionError("Editorial script repair loop exhausted unexpectedly")

    def _generate_legacy_script(
        self,
        story: StoryCandidate,
        materials: Sequence[SourceMaterial],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
    ) -> ReelScript:
        script = self.client.generate(
            LEGACY_SCRIPT_PROMPT,
            build_reel_script_payload(
                story, materials, minimum_duration_seconds, maximum_duration_seconds
            ),
            lambda content: parse_json_model(content, ReelScript),
            maximum_tokens=4_000,
        )
        return hydrate_reel_script(
            script,
            story,
            materials,
            minimum_duration_seconds,
            maximum_duration_seconds,
        )


def build_reel_script_payload(
    story: StoryCandidate,
    materials: Sequence[SourceMaterial],
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
) -> dict[str, object]:
    """Bound script context to the selected story rather than every submitted source."""
    selected_source_ids = set(story.source_ids)
    return {
        "duration_range_seconds": {
            "minimum": minimum_duration_seconds,
            "maximum": maximum_duration_seconds,
        },
        "story": story.model_dump(mode="json"),
        "sources": [
            {
                "id": material.source.id,
                "type": material.source.type,
                "name": material.source.name,
                "segments": [
                    {
                        "id": segment.id,
                        "text": segment.text[:4_000],
                        "start": segment.start,
                        "end": segment.end,
                    }
                    for segment in material.content.segments[:60]
                ],
                "assets": [asset.model_dump(mode="json") for asset in material.content.assets],
            }
            for material in materials
            if material.source.id in selected_source_ids
        ],
    }


def build_editorial_script_payload(
    story: StoryCandidate,
    angle: EditorialAngle,
    hook: HookCandidate,
    materials: Sequence[SourceMaterial],
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
    words_per_minute: int,
) -> dict[str, object]:
    """Bound script generation to the selected story, angle, hook, and usable visuals."""
    selected_source_ids = set(story.source_ids)
    return {
        "duration_range_seconds": {
            "minimum": minimum_duration_seconds,
            "maximum": maximum_duration_seconds,
        },
        "words_per_minute": words_per_minute,
        "story": story.model_dump(mode="json"),
        "selected_angle": angle.model_dump(mode="json"),
        "selected_hook": hook.model_dump(mode="json"),
        "required_hook_text": hook.text,
        "maximum_section_duration_seconds": _MAXIMUM_SECTION_DURATION_SECONDS,
        "maximum_sections": _editorial_section_limit(maximum_duration_seconds),
        "sources": [
            {
                "id": material.source.id,
                "type": material.source.type,
                "name": material.source.name,
                "segments": [
                    {
                        "id": segment.id,
                        "text": segment.text[:4_000],
                        "start": segment.start,
                        "end": segment.end,
                    }
                    for segment in material.content.segments[:60]
                ],
                "assets": [asset.model_dump(mode="json") for asset in material.content.assets],
            }
            for material in materials
            if material.source.id in selected_source_ids
        ],
    }


def build_editorial_script_repair_payload(
    story: StoryCandidate,
    angle: EditorialAngle,
    hook: HookCandidate,
    materials: Sequence[SourceMaterial],
    candidate_script: ReelScript,
    validation_error: LLMError,
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
    words_per_minute: int,
) -> dict[str, object]:
    """Provide only the evidence and IDs needed to repair a generated script."""
    selected_source_ids = set(story.source_ids)
    return {
        "duration_range_seconds": {
            "minimum": minimum_duration_seconds,
            "maximum": maximum_duration_seconds,
        },
        "words_per_minute": words_per_minute,
        "maximum_section_duration_seconds": _MAXIMUM_SECTION_DURATION_SECONDS,
        "maximum_sections": _editorial_section_limit(maximum_duration_seconds),
        "required_ids": {
            "story_id": story.id,
            "angle_id": angle.id,
            "hook_id": hook.id,
        },
        "required_hook_text": hook.text,
        "allowed_source_ids": story.source_ids,
        "selected_story": {
            "id": story.id,
            "title": story.title,
            "topic": story.topic,
            "summary": story.summary,
            "key_points": [point.model_dump(mode="json") for point in story.key_points],
            "conflicts": [conflict.model_dump(mode="json") for conflict in story.conflicts],
        },
        "selected_angle": {
            "id": angle.id,
            "angle": angle.angle,
            "evidence": [reference.model_dump(mode="json") for reference in angle.evidence],
        },
        "selected_hook": {
            "id": hook.id,
            "text": hook.text,
            "evidence": [reference.model_dump(mode="json") for reference in hook.evidence],
        },
        "available_assets": [
            {
                "id": asset.id,
                "source_id": asset.source_id,
                "type": asset.kind.value,
                "label": asset.label,
            }
            for material in materials
            if material.source.id in selected_source_ids
            for asset in material.content.assets
        ][:_MAXIMUM_REPAIR_ASSETS],
        "candidate_script": candidate_script.model_dump(mode="json"),
        "validation_failures": [" ".join(str(validation_error).split())[:1_000]],
    }


def parse_editorial_reel_script(content: str) -> ReelScript:
    """Accept harmless wire-format drift before enforcing the editorial contract."""
    return parse_json_model(
        content,
        ReelScript,
        normalizer=_normalize_editorial_reel_script_payload,
    )


def _canonicalize_editorial_hook(script: ReelScript, hook: HookCandidate) -> ReelScript:
    """Keep the previously selected, evidence-backed hook as the script opening."""
    first_section = script.sections[0].model_copy(
        update={
            "role": ScriptSectionRole.HOOK,
            "text": hook.text,
            "evidence": hook.evidence,
        }
    )
    return script.model_copy(
        update={
            "hook": hook.text,
            "hook_id": hook.id,
            "sections": [first_section, *script.sections[1:]],
        }
    )


def _normalize_editorial_reel_script_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    hook = normalized.get("hook")
    if isinstance(hook, dict) and isinstance(hook.get("text"), str):
        normalized["hook"] = hook["text"]

    sections = normalized.get("sections")
    if not isinstance(sections, list):
        return normalized
    normalized_sections: list[object] = []
    for section in sections:
        if not isinstance(section, dict):
            normalized_sections.append(section)
            continue
        normalized_section = dict(section)
        duration = normalized_section.get("duration_seconds")
        if (
            isinstance(duration, int | float)
            and not isinstance(duration, bool)
            and duration > _MAXIMUM_SECTION_DURATION_SECONDS
        ):
            normalized_section["duration_seconds"] = _MAXIMUM_SECTION_DURATION_SECONDS
        normalized_sections.append(normalized_section)
    normalized["sections"] = normalized_sections
    return normalized


def _editorial_section_limit(maximum_duration_seconds: int) -> int:
    return min(
        _MAXIMUM_EDITORIAL_SECTIONS,
        max(3, (maximum_duration_seconds + 9) // 10),
    )
