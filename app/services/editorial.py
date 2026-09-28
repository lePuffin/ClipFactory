"""Deterministic editorial ranking around structured, provenance-bound LLM assessments."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    AngleEvaluation,
    AngleEvaluations,
    AngleGeneration,
    EditorialAngle,
    EditorialDecision,
    EditorialScores,
    HookCandidate,
    HookGeneration,
    SourceMaterial,
    StoryCandidate,
    StoryEvaluation,
    StoryEvaluations,
)
from app.prompts.angle_evaluation import SYSTEM_PROMPT as ANGLE_EVALUATION_PROMPT
from app.prompts.angle_generation import SYSTEM_PROMPT as ANGLE_GENERATION_PROMPT
from app.prompts.hook_generation import SYSTEM_PROMPT as HOOK_GENERATION_PROMPT
from app.prompts.story_evaluation import SYSTEM_PROMPT as STORY_EVALUATION_PROMPT
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model
from app.services.reel_validation import hydrate_evidence


@dataclass(frozen=True, slots=True)
class EditorialOutcome:
    """The selected story, angle, hook, and retained decision record for one reel."""

    story_candidates: tuple[StoryCandidate, ...]
    story: StoryCandidate
    angle: EditorialAngle
    hook: HookCandidate
    decision: EditorialDecision


class EditorialEngine(Protocol):
    """Produces an explicit editorial decision from grouped story candidates."""

    def develop(
        self,
        stories: Sequence[StoryCandidate],
        materials: Sequence[SourceMaterial],
    ) -> EditorialOutcome: ...


class OpenRouterEditorialEngine:
    """Combines structured LLM evaluation with deterministic local selection."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenRouterJSONClient(settings)

    def develop(
        self,
        stories: Sequence[StoryCandidate],
        materials: Sequence[SourceMaterial],
    ) -> EditorialOutcome:
        evaluated_stories, story_evaluations = self.evaluate_stories(stories, materials)
        story = self.select_story(evaluated_stories)
        angles = self.generate_angles(story, materials)
        evaluated_angles, _ = self.evaluate_angles(story, angles, materials)
        angle = self.select_angle(evaluated_angles)
        hooks = self.generate_hooks(story, angle, materials)
        hook = self.select_hook(hooks)
        return EditorialOutcome(
            story_candidates=evaluated_stories,
            story=story,
            angle=angle,
            hook=hook,
            decision=EditorialDecision(
                story_evaluations=list(story_evaluations),
                angles=list(evaluated_angles),
                selected_angle=angle,
                hooks=list(hooks),
                selected_hook=hook,
            ),
        )

    def evaluate_stories(
        self,
        stories: Sequence[StoryCandidate],
        materials: Sequence[SourceMaterial],
    ) -> tuple[tuple[StoryCandidate, ...], tuple[StoryEvaluation, ...]]:
        if not stories:
            raise LLMError("At least one story candidate is required for editorial evaluation")
        evaluations = self.client.generate(
            STORY_EVALUATION_PROMPT,
            build_story_evaluation_payload(stories, materials),
            lambda content: parse_json_model(content, StoryEvaluations),
            maximum_tokens=3_000,
        )
        _validate_evaluation_ids(
            [evaluation.story_id for evaluation in evaluations.evaluations],
            [story.id for story in stories],
            "story",
        )
        evaluations_by_id = {
            evaluation.story_id: evaluation for evaluation in evaluations.evaluations
        }
        evaluated = tuple(
            _apply_story_evaluation(
                story,
                evaluations_by_id[story.id],
                self.settings.editorial_score_weights,
            )
            for story in stories
        )
        return rank_stories(evaluated, self.settings.editorial_score_weights), tuple(
            evaluations.evaluations
        )

    def select_story(self, stories: Sequence[StoryCandidate]) -> StoryCandidate:
        if not stories:
            raise LLMError("At least one evaluated story candidate is required")
        selected = rank_stories(stories, self.settings.editorial_score_weights)[0]
        reason = _selection_reason(selected.selection_reason, selected.overall_score)
        return selected.model_copy(update={"selection_reason": reason})

    def generate_angles(
        self,
        story: StoryCandidate,
        materials: Sequence[SourceMaterial],
    ) -> tuple[EditorialAngle, ...]:
        generated = self.client.generate(
            ANGLE_GENERATION_PROMPT,
            build_angle_generation_payload(story, materials),
            lambda content: parse_json_model(content, AngleGeneration),
            maximum_tokens=3_000,
        )
        angle_ids = [angle.id for angle in generated.angles]
        if len(angle_ids) != len(set(angle_ids)):
            raise LLMError("Editorial angle generation returned duplicate angle IDs")
        allowed_source_ids = set(story.source_ids)
        return tuple(
            angle.model_copy(
                update={
                    "evidence": hydrate_evidence(angle.evidence, materials, allowed_source_ids),
                }
            )
            for angle in generated.angles
        )

    def evaluate_angles(
        self,
        story: StoryCandidate,
        angles: Sequence[EditorialAngle],
        materials: Sequence[SourceMaterial],
    ) -> tuple[tuple[EditorialAngle, ...], tuple[AngleEvaluation, ...]]:
        if not angles:
            raise LLMError("At least one editorial angle is required for evaluation")
        evaluations = self.client.generate(
            ANGLE_EVALUATION_PROMPT,
            build_angle_evaluation_payload(story, angles, materials),
            lambda content: parse_json_model(content, AngleEvaluations),
            maximum_tokens=3_000,
        )
        _validate_evaluation_ids(
            [evaluation.angle_id for evaluation in evaluations.evaluations],
            [angle.id for angle in angles],
            "angle",
        )
        evaluations_by_id = {
            evaluation.angle_id: evaluation for evaluation in evaluations.evaluations
        }
        evaluated = tuple(
            _apply_angle_evaluation(
                angle,
                evaluations_by_id[angle.id],
                self.settings.editorial_score_weights,
            )
            for angle in angles
        )
        return rank_angles(evaluated, self.settings.editorial_score_weights), tuple(
            evaluations.evaluations
        )

    def select_angle(self, angles: Sequence[EditorialAngle]) -> EditorialAngle:
        if not angles:
            raise LLMError("At least one evaluated editorial angle is required")
        selected = rank_angles(angles, self.settings.editorial_score_weights)[0]
        reason = _selection_reason(selected.selection_reason, selected.overall_score)
        return selected.model_copy(update={"selection_reason": reason})

    def generate_hooks(
        self,
        story: StoryCandidate,
        angle: EditorialAngle,
        materials: Sequence[SourceMaterial],
    ) -> tuple[HookCandidate, ...]:
        generated = self.client.generate(
            HOOK_GENERATION_PROMPT,
            build_hook_generation_payload(story, angle, materials),
            lambda content: parse_json_model(content, HookGeneration),
            maximum_tokens=2_000,
        )
        hook_ids = [hook.id for hook in generated.hooks]
        if len(hook_ids) != len(set(hook_ids)):
            raise LLMError("Hook generation returned duplicate hook IDs")
        allowed_source_ids = set(story.source_ids)
        return tuple(
            hook.model_copy(
                update={"evidence": hydrate_evidence(hook.evidence, materials, allowed_source_ids)}
            )
            for hook in generated.hooks
        )

    def select_hook(self, hooks: Sequence[HookCandidate]) -> HookCandidate:
        if not hooks:
            raise LLMError("At least one hook candidate is required")
        selected = sorted(hooks, key=lambda hook: (-hook.score, hook.id))[0]
        reason = _selection_reason(selected.selection_reason or selected.rationale, selected.score)
        return selected.model_copy(update={"selection_reason": reason})


def calculate_editorial_score(scores: EditorialScores, weights: Mapping[str, float]) -> float:
    """Calculate a normalized score with named dimensions and no hidden model ranking."""
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("At least one editorial score weight must be positive")
    weighted_total = sum(
        getattr(scores, dimension) * weight for dimension, weight in weights.items()
    )
    return round(weighted_total / total_weight, 6)


def rank_stories(
    stories: Sequence[StoryCandidate], weights: Mapping[str, float]
) -> tuple[StoryCandidate, ...]:
    """Apply local weighted scoring and use stable IDs to resolve ties predictably."""
    scored = tuple(
        story.model_copy(
            update={"overall_score": calculate_editorial_score(story.editorial_scores, weights)}
        )
        for story in stories
    )
    return tuple(sorted(scored, key=lambda story: (-story.overall_score, story.id)))


def rank_angles(
    angles: Sequence[EditorialAngle], weights: Mapping[str, float]
) -> tuple[EditorialAngle, ...]:
    """Apply the same inspectable weighted ranking to supplied editorial angles."""
    scored = tuple(
        angle.model_copy(
            update={"overall_score": calculate_editorial_score(angle.editorial_scores, weights)}
        )
        for angle in angles
    )
    return tuple(sorted(scored, key=lambda angle: (-angle.overall_score, angle.id)))


def build_story_evaluation_payload(
    stories: Sequence[StoryCandidate], materials: Sequence[SourceMaterial]
) -> dict[str, object]:
    """Bound evaluator input to candidates and their source-backed editorial context."""
    source_ids = {source_id for story in stories for source_id in story.source_ids}
    return {
        "stories": [story.model_dump(mode="json") for story in stories],
        "source_context": _source_context(materials, source_ids),
    }


def build_angle_generation_payload(
    story: StoryCandidate, materials: Sequence[SourceMaterial]
) -> dict[str, object]:
    """Expose only selected-story evidence and available visuals to angle generation."""
    return {
        "story": story.model_dump(mode="json"),
        "source_context": _source_context(materials, set(story.source_ids)),
    }


def build_angle_evaluation_payload(
    story: StoryCandidate,
    angles: Sequence[EditorialAngle],
    materials: Sequence[SourceMaterial],
) -> dict[str, object]:
    """Give the evaluator only the selected story, generated angles, and source facts."""
    return {
        "story": story.model_dump(mode="json"),
        "angles": [angle.model_dump(mode="json") for angle in angles],
        "source_context": _source_context(materials, set(story.source_ids)),
    }


def build_hook_generation_payload(
    story: StoryCandidate,
    angle: EditorialAngle,
    materials: Sequence[SourceMaterial],
) -> dict[str, object]:
    """Keep hooks grounded in the selected story, angle, and source evidence."""
    return {
        "story": story.model_dump(mode="json"),
        "angle": angle.model_dump(mode="json"),
        "source_context": _source_context(materials, set(story.source_ids)),
    }


def _apply_story_evaluation(
    story: StoryCandidate,
    evaluation: StoryEvaluation,
    weights: Mapping[str, float],
) -> StoryCandidate:
    score = calculate_editorial_score(evaluation.scores, weights)
    return story.model_copy(
        update={
            "editorial_scores": evaluation.scores,
            "overall_score": score,
            "selection_reason": evaluation.rationale,
        }
    )


def _apply_angle_evaluation(
    angle: EditorialAngle,
    evaluation: AngleEvaluation,
    weights: Mapping[str, float],
) -> EditorialAngle:
    score = calculate_editorial_score(evaluation.scores, weights)
    return angle.model_copy(
        update={
            "editorial_scores": evaluation.scores,
            "overall_score": score,
            "selection_reason": evaluation.rationale,
        }
    )


def _validate_evaluation_ids(
    returned_ids: Sequence[str], expected_ids: Sequence[str], record_type: str
) -> None:
    if len(returned_ids) != len(set(returned_ids)):
        raise LLMError(f"Editorial {record_type} evaluation returned duplicate IDs")
    if set(returned_ids) != set(expected_ids):
        raise LLMError(f"Editorial {record_type} evaluation must cover every supplied candidate")


def _selection_reason(rationale: str, score: float) -> str:
    return f"{rationale} Deterministic weighted editorial score: {score:.2f}."[:800]


def _source_context(
    materials: Sequence[SourceMaterial], source_ids: set[str]
) -> list[dict[str, object]]:
    return [
        {
            "id": material.source.id,
            "type": material.source.type,
            "name": material.source.name,
            "analysis": material.analysis.model_dump(mode="json") if material.analysis else None,
            "segments": [
                {
                    "id": segment.id,
                    "text": segment.text[:2_000],
                    "start": segment.start,
                    "end": segment.end,
                }
                for segment in material.content.segments[:60]
            ],
            "assets": [asset.model_dump(mode="json") for asset in material.content.assets],
        }
        for material in materials
        if material.source.id in source_ids
    ]