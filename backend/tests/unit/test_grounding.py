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
    is_fragment,
    is_page_metadata,
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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-115")
def test_page_furniture_claims_are_rejected_as_page_metadata() -> None:
    text = (
        "Spain's Prime Minister Pedro Sanchez began campaigning on Saturday for a snap vote. Prices rose 5%. "
        "Issued on: 11/10/2026 - 10:37 Modified: 11/10/2026 - 10:37 "
        "Our correspondent Sarah Morris tells us more. Video by: Sarah MORRIS"
    )
    source = GroundedSource(uuid4(), article("https://f.example/1", "F", text, datetime(2026, 10, 11, tzinfo=UTC)), "F")
    texts = [
        "Sanchez began campaigning on Saturday for a snap vote",
        "Prices rose 5%",
        "Issued on: 11/10/2026 - 10:37",
        "Modified: 11/10/2026 - 10:37",
        "Our correspondent Sarah Morris tells us more.",
        "Video by: Sarah MORRIS",
        "11/10/2026 - 10:37",
    ]
    excerpts = [
        "began campaigning on Saturday for a snap vote",
        "Prices rose 5%",
        "Issued on: 11/10/2026 - 10:37",
        "Modified: 11/10/2026 - 10:37",
        "Our correspondent Sarah Morris tells us more.",
        "Video by: Sarah MORRIS",
        "11/10/2026 - 10:37",
    ]
    drafts = [
        ClaimDraft(text=claim, kind=ClaimKind.FACT, evidence=[ClaimEvidenceDraft(source_id=source.id, excerpt=quote)])
        for claim, quote in zip(texts, excerpts, strict=True)
    ]
    claims = build_verified_claims(uuid4(), drafts, [source])
    assert [claim.status for claim in claims[:2]] == [ClaimStatus.ACCEPTED, ClaimStatus.ACCEPTED]
    assert all(claim.status == ClaimStatus.REJECTED for claim in claims[2:])
    assert {claim.rejection_reason for claim in claims[2:]} == {"page_metadata"}


@pytest.mark.unit
@pytest.mark.req("CF-REQ-115")
@pytest.mark.parametrize(
    ("text", "metadata"),
    [
        ("Video Duration 30 minutes 36 seconds 30:36", True),
        ("The event was published on 11 Oct 2026", True),
        ("The report was published in March and cited by lawmakers.", False),
        ("Keywords for this article elections France Left wing Socialist Party (France)", True),
        ("The illustrations in this video have been created by artists aided by AI-powered software.", True),
        ("True Crime Reports is an Al Jazeera Originals Production.", True),
        ("Vittorio Boiocchi, a lifelong Inter Milan fan, is shot outside his Milan home in 2022.", False),
        ("The film is a joint production with the BBC, the studio said on Monday.", False),
        ("The company generated images with AI and was fined 2 million euros.", False),
    ],
)
def test_runtime_labels_ai_disclaimers_and_production_credits_are_page_metadata(text: str, metadata: bool) -> None:
    assert is_page_metadata(text) is metadata


@pytest.mark.unit
@pytest.mark.req("CF-REQ-115")
@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("with a cyberattack disrupting the primary vote.", True),
        ("guest Joseph Downing, Senior Lecturer in Politics at Aston University.", True),
        ("“irresponsible threats” that “could potentially compromise”", True),
        ("an allegation he denies.", True),
        ("A cyberattack disrupted the Socialist primary vote on Thursday.", False),
        ("“We will not back down,” the minister said.", False),
        ("7,000 people were detained, media reports said.", False),
    ],
)
def test_sentence_fragments_are_not_atomic_claims(text: str, fragment: bool) -> None:
    assert is_fragment(text) is fragment


@pytest.mark.unit
@pytest.mark.req("CF-REQ-115")
def test_fragment_claims_are_rejected_with_reason_fragment() -> None:
    text = "A cyberattack disrupted the primary vote on Thursday, with officials investigating."
    source = GroundedSource(uuid4(), article("https://f.example/2", "F", text, datetime(2026, 10, 11, tzinfo=UTC)), "F")
    drafts = [
        ClaimDraft(text=claim, kind=ClaimKind.FACT, evidence=[ClaimEvidenceDraft(source_id=source.id, excerpt=quote)])
        for claim, quote in [
            ("A cyberattack disrupted the primary vote on Thursday", "A cyberattack disrupted the primary vote"),
            ("with officials investigating.", "with officials investigating."),
        ]
    ]
    claims = build_verified_claims(uuid4(), drafts, [source])
    assert claims[0].status == ClaimStatus.ACCEPTED
    assert (claims[1].status, claims[1].rejection_reason) == (ClaimStatus.REJECTED, "fragment")
