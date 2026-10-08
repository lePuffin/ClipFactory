from uuid import uuid4

import pytest
from pydantic import ValidationError

from clipfactory.domain.models import (
    AssetOrigin,
    Claim,
    ClaimStatus,
    ContentProfile,
    DurationPolicy,
    Issue,
    IssueSeverity,
    Schedule,
    Stage,
    SupportLevel,
    compute_support_level,
    verify_evidence_excerpt,
)
from clipfactory.domain.routing import ISSUE_ROUTES, earliest_reentry


@pytest.mark.unit
@pytest.mark.req("CF-REQ-551")
def test_content_profile_rejects_invalid_duration_and_timezone() -> None:
    with pytest.raises(ValidationError):
        DurationPolicy(min_seconds=90, target_seconds=70, max_seconds=60)
    with pytest.raises(ValidationError):
        ContentProfile(schedule=Schedule(timezone="Mars/Base"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-113")
def test_evidence_normalizes_quotes_and_rejects_fabricated_words() -> None:
    excerpt = "The ‘new’ policy — starts now"  # noqa: RUF001
    assert verify_evidence_excerpt(excerpt, 'The "new" policy - starts now.')
    assert not verify_evidence_excerpt("The new secret policy starts now", "The new policy starts now")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-114")
def test_support_level_uses_independent_verified_source_count() -> None:
    assert compute_support_level(0) == SupportLevel.UNSUPPORTED
    assert compute_support_level(1) == SupportLevel.SINGLE_SOURCE
    assert compute_support_level(2) == SupportLevel.CORROBORATED


@pytest.mark.unit
@pytest.mark.req("CF-REQ-115")
def test_unsupported_claim_cannot_be_accepted() -> None:
    with pytest.raises(ValidationError):
        Claim(story_id=uuid4(), text="A claim", status=ClaimStatus.ACCEPTED)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-201")
def test_generated_asset_requires_generation_provenance() -> None:
    from clipfactory.domain.models import Provenance

    with pytest.raises(ValidationError):
        Provenance(origin=AssetOrigin.GENERATED, provider="fake", license="CC0")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-407")
def test_retry_uses_earliest_target_stage() -> None:
    routes = [ISSUE_ROUTES["visual_irrelevant"], ISSUE_ROUTES["claim_not_supported"]]
    assert earliest_reentry(routes) == Stage.WRITE_SCRIPT


@pytest.mark.unit
@pytest.mark.req("CF-REQ-400")
def test_evaluation_passes_only_when_no_blocking_issues() -> None:
    from clipfactory.domain.models import Evaluation, EvaluationLayer

    warning = Issue(code="caption_quality", severity=IssueSeverity.WARNING, stage=Stage.EVALUATE_CLIP, message="minor")
    evaluation = Evaluation(
        run_id=uuid4(), attempt=1, layer=EvaluationLayer.SEMANTIC, warnings=[warning], evaluator="fake"
    )
    assert evaluation.passed

    blocking = Issue(code="weak_hook", severity=IssueSeverity.BLOCKING, stage=Stage.WRITE_SCRIPT, message="weak")
    failed = Evaluation(run_id=uuid4(), attempt=1, layer=EvaluationLayer.SEMANTIC, issues=[blocking], evaluator="fake")
    assert not failed.passed
