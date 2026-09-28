import pytest

from app.core.exceptions import LLMError
from app.models.reel import (
    ContentSegment,
    EditorialAngle,
    EvidenceReference,
    ExtractedContent,
    HookCandidate,
    PreferredVisualType,
    ReelScript,
    ReelScriptSection,
    ScriptSectionRole,
    SourceMaterial,
    StatementType,
    StoryCandidate,
    StoryConflict,
    StoryKeyPoint,
)
from app.models.source import ClipSourceOrigin, ClipSourceType, Source
from app.services.script_validation import estimate_spoken_duration, validate_editorial_script


def _material(source_id: str = "article-01", text: str | None = None) -> SourceMaterial:
    return SourceMaterial(
        source=Source(
            id=source_id,
            type=ClipSourceType.ARTICLE,
            origin=ClipSourceOrigin.ARTICLE_TEXT,
            name="Earnings report",
            reference="Earnings report " * 12,
        ),
        content=ExtractedContent(
            segments=[
                ContentSegment(
                    id=f"{source_id}-p-001",
                    text=text
                    or "The company raised its annual outlook after strong sales.",
                )
            ]
        ),
    )


def _story() -> StoryCandidate:
    evidence = [EvidenceReference(source_id="article-01", segment_id="article-01-p-001")]
    return StoryCandidate(
        id="story_01",
        title="Company raises outlook",
        topic="company earnings outlook",
        importance=0.9,
        source_ids=["article-01"],
        key_points=[
            StoryKeyPoint(text="The outlook was raised after strong sales.", evidence=evidence)
        ],
    )


def _angle() -> EditorialAngle:
    return EditorialAngle(
        id="angle_01",
        angle="Why the outlook changed",
        rationale="It leads with the supported news.",
        audience_interest_rationale="It gives viewers useful context.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
    )


def _hook(text: str = "The company raised its outlook.") -> HookCandidate:
    return HookCandidate(
        id="hook_01",
        text=text,
        rationale="It leads with the reported change.",
        evidence=[EvidenceReference(source_id="article-01", segment_id="article-01-p-001")],
        score=0.9,
    )


def _script(hook_text: str = "The company raised its outlook.") -> ReelScript:
    evidence = [EvidenceReference(source_id="article-01", segment_id="article-01-p-001")]
    return ReelScript(
        story_id="story_01",
        angle_id="angle_01",
        hook_id="hook_01",
        title="Company raises outlook",
        hook=hook_text,
        sections=[
            ReelScriptSection(
                id="section_01",
                role=ScriptSectionRole.HOOK,
                text=hook_text,
                duration_seconds=5,
                evidence=evidence,
                visual_intent="Show the reported company announcement.",
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
            ReelScriptSection(
                id="section_02",
                role=ScriptSectionRole.IMPLICATION,
                text="Strong sales support the change.",
                duration_seconds=5,
                evidence=evidence,
                visual_intent="Show the source material supporting the sales result.",
                preferred_visual_type=PreferredVisualType.TEXT_CARD,
            ),
        ],
    )


def test_duration_estimation_and_validation_normalize_scene_timing() -> None:
    result = validate_editorial_script(
        _script(),
        _story(),
        _angle(),
        _hook(),
        [_material()],
        minimum_duration_seconds=4,
        maximum_duration_seconds=6,
        words_per_minute=120,
    )

    assert estimate_spoken_duration("One two three four five.", 150) == 2
    assert result.report.word_count == 10
    assert result.report.estimated_duration_seconds == 5
    assert result.script.planned_duration == 5
    assert result.script.sections[0].duration_seconds == 2.5


def test_script_validation_rejects_an_unsupported_claim() -> None:
    unsupported_hook = "Profits doubled overnight now."

    with pytest.raises(LLMError, match="unsupported claims"):
        validate_editorial_script(
            _script(unsupported_hook),
            _story(),
            _angle(),
            _hook(unsupported_hook),
            [_material()],
            minimum_duration_seconds=4,
            maximum_duration_seconds=6,
            words_per_minute=120,
        )


def test_script_validation_rejects_an_overlong_spoken_section() -> None:
    overlong_hook = "The company raised its annual outlook after strong sales. " * 8

    with pytest.raises(LLMError, match="longer than 30 seconds"):
        validate_editorial_script(
            _script(overlong_hook),
            _story(),
            _angle(),
            _hook(overlong_hook),
            [_material()],
            minimum_duration_seconds=4,
            maximum_duration_seconds=60,
            words_per_minute=120,
        )


def test_script_validation_rejects_unknown_visual_assets() -> None:
    script = _script().model_copy(
        update={
            "sections": [
                _script().sections[0].model_copy(update={"candidate_asset_ids": ["missing-asset"]}),
                _script().sections[1],
            ]
        }
    )

    with pytest.raises(LLMError, match="unknown visual asset"):
        validate_editorial_script(
            script,
            _story(),
            _angle(),
            _hook(),
            [_material()],
            minimum_duration_seconds=4,
            maximum_duration_seconds=6,
            words_per_minute=120,
        )


def test_script_validation_requires_attribution_for_combined_conflicting_sources() -> None:
    conflict_story = _story().model_copy(
        update={
            "source_ids": ["article-01", "article-02"],
            "conflicts": [
                StoryConflict(
                    description="The sources give different outlook assessments.",
                    evidence=[
                        EvidenceReference(source_id="article-01", segment_id="article-01-p-001"),
                        EvidenceReference(source_id="article-02", segment_id="article-02-p-001"),
                    ],
                )
            ],
        }
    )
    conflict_hook = "Sources disagree about the outlook."
    script = _script(conflict_hook).model_copy(
        update={
            "sections": [
                _script(conflict_hook).sections[0].model_copy(
                    update={
                        "evidence": [
                            EvidenceReference(
                                source_id="article-01",
                                segment_id="article-01-p-001",
                            ),
                            EvidenceReference(
                                source_id="article-02",
                                segment_id="article-02-p-001",
                            ),
                        ],
                        "statement_type": StatementType.FACT,
                    }
                ),
                _script(conflict_hook).sections[1],
            ]
        }
    )

    with pytest.raises(LLMError, match="must attribute the source conflict"):
        validate_editorial_script(
            script,
            conflict_story,
            _angle(),
            _hook(conflict_hook),
            [_material(), _material("article-02", "The company maintained its annual outlook.")],
            minimum_duration_seconds=4,
            maximum_duration_seconds=6,
            words_per_minute=120,
        )