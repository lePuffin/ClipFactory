from datetime import UTC, datetime
from uuid import uuid4

import pytest

from clipfactory.domain.models import ClaimKind, ClaimStatus, SupportLevel
from clipfactory.ports.news import ArticleRef
from clipfactory.research.discovery import RetrievedArticle
from clipfactory.research.grounding import (
    ClaimDraft,
    ClaimEvidenceDraft,
    GroundedSource,
    build_verified_claims,
    detect_syndication,
    independent_source_count,
)


def article(url: str, publisher: str, text: str, published_at: datetime) -> RetrievedArticle:
    reference = ArticleRef(url, "Story", publisher, published_at)
    return RetrievedArticle(reference, url, "Story", text, None, "hash", "high")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-104")
def test_near_duplicate_is_syndicated_and_counts_one_independent_source() -> None:
    timestamp = datetime(2026, 9, 30, tzinfo=UTC)
    repeated_text = "The five word statement repeated for this important news event. " * 8
    original = article("https://reuters.example/a", "Reuters", "Reuters - " + repeated_text, timestamp)
    copy = article("https://blog.example/a", "Blog", repeated_text, timestamp)
    sources = detect_syndication([copy, original], threshold=0.8)
    assert len(sources) == 2
    assert sources[1].syndication_of == sources[0].id
    assert independent_source_count(sources) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-104")
def test_syndication_preserves_partial_source_ids_and_assigns_missing_ids() -> None:
    timestamp = datetime(2026, 9, 30, tzinfo=UTC)
    text = "The five word statement repeated for this important news event. " * 8
    original = article("https://reuters.example/a", "Reuters", text, timestamp)
    copy = article("https://blog.example/a", "Blog", text, timestamp)
    selected_id = uuid4()
    selected_ids = {copy.canonical_url: selected_id}

    sources = detect_syndication([original, copy], source_ids=selected_ids)

    assert len(sources) == 2
    assert sources[1].id == selected_id
    assert sources[0].id != selected_id
    assert sources[1].syndication_of == sources[0].id
    assert selected_ids == {copy.canonical_url: selected_id}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-113")
@pytest.mark.req("CF-REQ-114")
@pytest.mark.req("CF-REQ-115")
def test_claims_require_verified_evidence_and_contradictions_are_resolved_deterministically() -> None:
    timestamp = datetime(2026, 9, 30, tzinfo=UTC)
    source_a_article = article(
        "https://a.example/1", "A", "The project costs 12 million dollars according to the report.", timestamp
    )
    source_b_article = article(
        "https://b.example/1", "B", "The project costs 15 million dollars according to the report.", timestamp
    )
    source_a = GroundedSource(uuid4(), source_a_article, "A")
    source_b = GroundedSource(uuid4(), source_b_article, "B")
    drafts = [
        ClaimDraft(
            text="It costs 12 million",
            kind=ClaimKind.FIGURE,
            evidence=[ClaimEvidenceDraft(source_id=source_a.id, excerpt="costs 12 million dollars")],
        ),
        ClaimDraft(
            text="It costs 15 million",
            kind=ClaimKind.FIGURE,
            evidence=[ClaimEvidenceDraft(source_id=source_b.id, excerpt="costs 15 million dollars")],
        ),
        ClaimDraft(
            text="It costs 99 million",
            kind=ClaimKind.FIGURE,
            evidence=[ClaimEvidenceDraft(source_id=source_b.id, excerpt="costs 99 million dollars")],
        ),
    ]
    claims = build_verified_claims(uuid4(), drafts, [source_a, source_b], contradictions=[[0, 1]])
    assert claims[0].support_level == SupportLevel.SINGLE_SOURCE
    assert claims[0].status == ClaimStatus.ACCEPTED
    assert claims[1].status == ClaimStatus.REJECTED
    assert claims[1].rejection_reason == "contradicted"
    assert claims[2].support_level == SupportLevel.UNSUPPORTED
    assert claims[2].status == ClaimStatus.REJECTED
