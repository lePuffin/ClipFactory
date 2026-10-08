"""Deterministic Asset library matching; no provider or LLM calls."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from clipfactory.domain.models import Asset, AssetStatus
from clipfactory.ports.media_sources import MediaCandidate


@dataclass(frozen=True, slots=True)
class AssetRequirement:
    media_type: str
    category: str
    description: str
    subjects: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    min_width: int = 0
    min_height: int = 0


@dataclass(frozen=True, slots=True)
class AssetMatch:
    asset: Asset
    score: float


def refined_media_queries(requirement: AssetRequirement, declared: Sequence[str] = ()) -> tuple[str, ...]:
    """Refine keywords without changing the Shot Intent used for ranking/review/import."""
    original = " ".join(requirement.description.split()).casefold()
    seen = {original}
    output: list[str] = []
    choices = declared or (
        " ".join(requirement.subjects),
        " ".join((*requirement.subjects, *requirement.tags)),
        " ".join(requirement.tags),
    )
    for value in choices:
        query = " ".join(re.findall(r"[\w'-]+", value)[:12])[:120].strip()
        if query and query.casefold() not in seen:
            seen.add(query.casefold())
            output.append(query)
        if len(output) == 2:
            break
    return tuple(output)


def rank_media_candidates(requirement: AssetRequirement, candidates: Sequence[MediaCandidate]) -> list[MediaCandidate]:
    query = _terms(" ".join((requirement.description, *requirement.subjects, *requirement.tags)))
    ranked: list[tuple[float, int, MediaCandidate]] = []
    for index, candidate in enumerate(candidates):
        if not candidate.license.strip():
            continue
        if requirement.media_type != "any" and candidate.media_type != requirement.media_type:
            continue
        if candidate.media_type == "image" and min(candidate.width, candidate.height) < requirement.min_width:
            continue
        if candidate.media_type == "video" and candidate.height < requirement.min_height:
            continue
        terms = _terms(" ".join((candidate.description, candidate.url)))
        overlap = len(query & terms) / len(query) if query else 0.0
        portrait = candidate.height >= candidate.width or min(candidate.width, candidate.height) >= 720
        score = overlap + 0.15 * portrait + 0.2 * (candidate.media_type == requirement.media_type) + 0.1 / (index + 1)
        ranked.append((score, -index, candidate))
    return [candidate for _, _, candidate in sorted(ranked, key=lambda item: (item[0], item[1]), reverse=True)]


def choose_reusable_asset(
    requirement: AssetRequirement,
    assets: Sequence[Asset],
    *,
    now: datetime,
    cooldown_days: int = 3,
    minimum_match: float = 0.6,
    already_used: frozenset[str] = frozenset(),
) -> AssetMatch | None:
    eligible = [asset for asset in assets if _eligible(asset, requirement, already_used)]
    cooled = [
        asset
        for asset in eligible
        if asset.last_used_at is None
        or (now - _aware(asset.last_used_at, now)).total_seconds() >= cooldown_days * 86_400
    ]
    matches = _rank(requirement, cooled or eligible)
    return next((match for match in matches if match.score >= minimum_match), None)


def _eligible(asset: Asset, requirement: AssetRequirement, already_used: frozenset[str]) -> bool:
    if asset.status != AssetStatus.ACTIVE or not asset.reusable or str(asset.id) in already_used:
        return False
    if requirement.media_type != "any" and asset.media_type != requirement.media_type:
        return False
    if asset.category != requirement.category:
        return False
    if requirement.min_width and (asset.width or 0) < requirement.min_width:
        return False
    if requirement.min_height and (asset.height or 0) < requirement.min_height:
        return False
    return bool(asset.provenance.license.strip())


def _rank(requirement: AssetRequirement, assets: Sequence[Asset]) -> list[AssetMatch]:
    subjects = {_normalize(value) for value in requirement.subjects if _normalize(value)}
    tags = {_normalize(value) for value in requirement.tags if _normalize(value)}
    query = _terms(" ".join((requirement.description, *requirement.subjects, *requirement.tags)))
    matches: list[AssetMatch] = []
    for asset in assets:
        asset_subjects = {_normalize(value) for value in asset.subjects if _normalize(value)}
        asset_tags = {_normalize(value) for value in asset.tags if _normalize(value)}
        asset_text = _terms(" ".join((asset.description, *asset.subjects, *asset.tags)))
        subject_score = _jaccard(subjects, asset_subjects)
        tag_score = _jaccard(tags, asset_tags)
        text_score = len(query & asset_text) / len(query) if query else 0.0
        matches.append(AssetMatch(asset, 0.5 * subject_score + 0.3 * tag_score + 0.2 * text_score))
    return sorted(
        matches,
        key=lambda match: (
            match.score,
            match.asset.quality_score or 0.0,
            -_timestamp(match.asset.last_used_at),
            match.asset.description.casefold(),
        ),
        reverse=True,
    )


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[\w']+", value.casefold()))


def _terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[\w']+", value.casefold()) if len(term) > 2}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _aware(value: datetime, reference: datetime) -> datetime:
    return value.replace(tzinfo=reference.tzinfo) if value.tzinfo is None else value


def _timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else 0.0
