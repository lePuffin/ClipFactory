"""Deterministic source independence and Claim evidence rules."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from clipfactory.domain.models import (
    Claim,
    ClaimKind,
    ClaimStatus,
    Evidence,
    SupportLevel,
    compute_support_level,
    verify_evidence_excerpt,
)
from clipfactory.research.discovery import RetrievedArticle


@dataclass(frozen=True, slots=True)
class GroundedSource:
    id: UUID
    article: RetrievedArticle
    origin_publisher: str
    syndication_of: UUID | None = None


class ClaimEvidenceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: UUID
    excerpt: str = Field(min_length=1)


class ClaimDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    kind: ClaimKind
    evidence: list[ClaimEvidenceDraft] = Field(min_length=1)


def detect_syndication(
    articles: Sequence[RetrievedArticle],
    *,
    threshold: float = 0.8,
    source_ids: dict[str, UUID] | None = None,
) -> list[GroundedSource]:
    """Link near-copies to the earliest matching source and retain origin publisher."""
    ids = dict(source_ids or {})
    for article in articles:
        if article.canonical_url not in ids:
            ids[article.canonical_url] = uuid4()
    ordered = sorted(articles, key=lambda article: _published_key(article.reference.published_at))
    accepted: list[GroundedSource] = []
    for article in ordered:
        publisher = article.reference.publisher
        wire_origin = _wire_origin(article.text)
        origin = wire_origin or publisher
        match = next(
            (
                source
                for source in accepted
                if _jaccard(_five_word_shingles(article.text), _five_word_shingles(source.article.text)) >= threshold
            ),
            None,
        )
        accepted.append(
            GroundedSource(
                id=ids[article.canonical_url],
                article=article,
                origin_publisher=match.origin_publisher if match else origin,
                syndication_of=match.id if match else None,
            )
        )
    return accepted


def independent_source_count(sources: Sequence[GroundedSource]) -> int:
    return len(
        {
            source.origin_publisher.casefold()
            for source in sources
            if source.syndication_of is None and source.article.quality_tier != "blocked"
        }
    )


def build_verified_claims(
    story_id: UUID,
    drafts: Sequence[ClaimDraft],
    sources: Sequence[GroundedSource],
    *,
    contradictions: Sequence[Sequence[int]] = (),
) -> list[Claim]:
    by_id = {source.id: source for source in sources}
    verified: list[tuple[ClaimDraft, list[Evidence], SupportLevel]] = []
    for draft in drafts:
        evidence = [
            Evidence(
                source_id=item.source_id,
                excerpt=item.excerpt,
                verified=item.source_id in by_id
                and verify_evidence_excerpt(item.excerpt, by_id[item.source_id].article.text),
            )
            for item in draft.evidence
        ]
        origins = {
            by_id[item.source_id].origin_publisher.casefold()
            for item in evidence
            if item.verified
            and item.source_id in by_id
            and by_id[item.source_id].syndication_of is None
            and by_id[item.source_id].article.quality_tier != "blocked"
        }
        verified.append((draft, evidence, compute_support_level(len(origins))))

    rejected_indexes: set[int] = set()
    for group in contradictions:
        valid_indexes = [index for index in group if 0 <= index < len(verified)]
        if len(valid_indexes) < 2:
            continue
        strongest = max(
            valid_indexes,
            key=lambda index: (
                _support_weight(verified[index][2]),
                len([evidence for evidence in verified[index][1] if evidence.verified]),
                -index,
            ),
        )
        rejected_indexes.update(index for index in valid_indexes if index != strongest)

    claims: list[Claim] = []
    for index, (draft, evidence, support) in enumerate(verified):
        accepted = support != SupportLevel.UNSUPPORTED and index not in rejected_indexes
        claims.append(
            Claim(
                story_id=story_id,
                text=draft.text,
                kind=draft.kind,
                evidence=evidence,
                support_level=support,
                status=ClaimStatus.ACCEPTED if accepted else ClaimStatus.REJECTED,
                rejection_reason=None if accepted else ("contradicted" if index in rejected_indexes else "unsupported"),
            )
        )
    return claims


def _published_key(value: datetime | None) -> tuple[int, float]:
    return (1, value.timestamp()) if value is not None else (0, 0.0)


def _five_word_shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[\w']+", text.casefold())
    return {tuple(words[index : index + 5]) for index in range(max(0, len(words) - 4))}


def _jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _wire_origin(text: str) -> str | None:
    opening = text[:240]
    match = re.search(r"(?:^|[\n(])\s*(Reuters|Associated Press|AP)\s*(?:\)|[-:]|—)", opening, re.IGNORECASE)
    if not match:
        return None
    return "Associated Press" if match.group(1).casefold() == "ap" else match.group(1)


def _support_weight(support: SupportLevel) -> int:
    return {
        SupportLevel.UNSUPPORTED: 0,
        SupportLevel.SINGLE_SOURCE: 1,
        SupportLevel.CORROBORATED: 2,
    }[support]
