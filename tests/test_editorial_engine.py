import pytest

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import (
    AngleEvaluation,
    AngleEvaluations,
    AngleGeneration,
    ContentSegment,
    EditorialAngle,
    EditorialScores,
    EvidenceReference,
    ExtractedContent,
    HookCandidate,
    HookGeneration,
    SourceMaterial,
    StoryCandidate,
    StoryEvaluation,
    StoryEvaluations,
    StoryKeyPoint,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.editorial import OpenRouterEditorialEngine, rank_angles, rank_stories


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)

    def generate(self, *_: object, **__: object) -> object:
        return next(self.responses)


def _material() -> SourceMaterial:
    return SourceMaterial(
        source=Source(
            id="video-01",
            type=ClipSourceType.VIDEO,
            origin=ClipSourceOrigin.UPLOAD,
            name="briefing.mp4",
            reference="briefing.mp4",
        ),
        content=ExtractedContent(
            segments=[
                ContentSegment(
                    id="video-01-seg-001",
                    text="The company raised its annual revenue outlook after strong sales.",
                    start=12,
                    end=18,
                )
            ]
        ),
    )


def _story(story_id: str) -> StoryCandidate:
    evidence = [EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")]
    return StoryCandidate(
        id=story_id,
        title="Company raises outlook",
        topic="company earnings outlook",
        importance=0.8,
        source_ids=["video-01"],
        key_points=[
            StoryKeyPoint(text="The outlook was raised after strong sales.", evidence=evidence)
        ],
        visual_availability=0.8,
    )


def _scores(importance: float) -> EditorialScores:
    return EditorialScores(
        importance=importance,
        novelty=importance,
        audience_interest=importance,
        clarity=importance,
        storytelling_potential=importance,
        factual_support=importance,
        visual_potential=importance,
        source_coverage=importance,
    )


def test_story_and_angle_ranking_are_weighted_and_deterministic() -> None:
    settings = Settings(_env_file=None)
    first = _story("story_02").model_copy(update={"editorial_scores": _scores(0.8)})
    second = _story("story_01").model_copy(update={"editorial_scores": _scores(0.8)})
    ranked_stories = rank_stories([first, second], settings.editorial_score_weights)
    angle_a = EditorialAngle(
        id="angle_02",
        angle="Why the change matters",
        rationale="It connects the reported change to the viewer.",
        audience_interest_rationale="The consequence is useful context.",
        evidence=[EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")],
        editorial_scores=_scores(0.7),
    )
    angle_b = angle_a.model_copy(update={"id": "angle_01"})

    ranked_angles = rank_angles([angle_a, angle_b], settings.editorial_score_weights)

    assert [story.id for story in ranked_stories] == ["story_01", "story_02"]
    assert [angle.id for angle in ranked_angles] == ["angle_01", "angle_02"]
    assert ranked_stories[0].overall_score == 0.8
    assert ranked_angles[0].overall_score == 0.7


def test_editorial_engine_preserves_evidence_through_selection() -> None:
    settings = Settings(_env_file=None, llm_api_key="test-key")
    engine = OpenRouterEditorialEngine(settings)
    engine.client = FakeClient(  # type: ignore[assignment]
        [
            StoryEvaluations(
                evaluations=[
                    StoryEvaluation(
                        story_id="story_01",
                        scores=_scores(0.7),
                        rationale="Supported by the source transcript.",
                    ),
                    StoryEvaluation(
                        story_id="story_02",
                        scores=_scores(0.9),
                        rationale="It is clearer and more useful for viewers.",
                    ),
                ]
            ),
            AngleGeneration(
                angles=[
                    EditorialAngle(
                        id="angle_01",
                        angle="Why the outlook changed",
                        rationale="It leads with the supported development.",
                        audience_interest_rationale="Viewers get a concise explanation.",
                        evidence=[
                            EvidenceReference(
                                source_id="video-01",
                                segment_id="video-01-seg-001",
                            )
                        ],
                    )
                ]
            ),
            AngleEvaluations(
                evaluations=[
                    AngleEvaluation(
                        angle_id="angle_01",
                        scores=_scores(0.85),
                        rationale="It has the strongest factual support.",
                    )
                ]
            ),
            HookGeneration(
                hooks=[
                    HookCandidate(
                        id="hook_01",
                        text="The outlook just changed.",
                        rationale="It opens with the supported change.",
                        evidence=[
                            EvidenceReference(
                                source_id="video-01",
                                segment_id="video-01-seg-001",
                            )
                        ],
                        score=0.8,
                    ),
                    HookCandidate(
                        id="hook_02",
                        text="Strong sales changed the outlook.",
                        rationale="It leads with the supplied cause.",
                        evidence=[
                            EvidenceReference(
                                source_id="video-01",
                                segment_id="video-01-seg-001",
                            )
                        ],
                        score=0.9,
                    ),
                ]
            ),
        ]
    )

    outcome = engine.develop([_story("story_01"), _story("story_02")], [_material()])

    assert outcome.story.id == "story_02"
    assert outcome.story.overall_score == 0.9
    assert outcome.angle.id == "angle_01"
    assert outcome.hook.id == "hook_02"
    assert outcome.angle.evidence[0].start == 12
    assert outcome.hook.evidence[0].end == 18
    assert outcome.decision.selected_angle is not None
    assert outcome.decision.selected_hook is not None


def test_hook_generation_rejects_unknown_evidence() -> None:
    settings = Settings(_env_file=None, llm_api_key="test-key")
    engine = OpenRouterEditorialEngine(settings)
    story = _story("story_01")
    angle = EditorialAngle(
        id="angle_01",
        angle="Why the outlook changed",
        rationale="It is grounded in the transcript.",
        audience_interest_rationale="It gives viewers useful context.",
        evidence=[EvidenceReference(source_id="video-01", segment_id="video-01-seg-001")],
    )
    engine.client = FakeClient(  # type: ignore[assignment]
        [
            HookGeneration(
                hooks=[
                    HookCandidate(
                        id="hook_01",
                        text="The outlook just changed.",
                        rationale="It opens with the story.",
                        evidence=[
                            EvidenceReference(
                                source_id="video-01",
                                segment_id="video-01-seg-999",
                            )
                        ],
                        score=0.8,
                    )
                ]
            )
        ]
    )

    with pytest.raises(LLMError, match="unknown source segment"):
        engine.generate_hooks(story, angle, [_material()])
