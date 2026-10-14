from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from clipfactory.assets.selection import AssetRequirement, choose_reusable_asset, rank_media_candidates
from clipfactory.domain.models import Asset, AssetOrigin, AssetStatus, Provenance
from clipfactory.ports.media_sources import MediaCandidate


def asset(
    *,
    description: str,
    tags: list[str],
    subjects: list[str],
    last_used_at: datetime | None = None,
    status: AssetStatus = AssetStatus.ACTIVE,
) -> Asset:
    return Asset(
        media_type="image",
        category="photo",
        storage_key=f"assets/{uuid4()}.png",
        sha256="a" * 64,
        mime_type="image/png",
        size_bytes=100,
        width=1200,
        height=1600,
        description=description,
        tags=tags,
        subjects=subjects,
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="manual", license="CC0"),
        status=status,
        last_used_at=last_used_at,
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-204")
@pytest.mark.req("CF-REQ-205")
def test_asset_selection_prefers_subject_tag_match_and_excludes_retired_assets() -> None:
    requirement = AssetRequirement(
        media_type="image",
        category="photo",
        description="UK Parliament vote",
        subjects=("UK Parliament",),
        tags=("parliament", "vote"),
        min_width=720,
    )
    matching = asset(description="Parliament exterior", tags=["parliament", "vote"], subjects=["UK Parliament"])
    retired = asset(
        description="Parliament exterior",
        tags=["parliament", "vote"],
        subjects=["UK Parliament"],
        status=AssetStatus.RETIRED,
    )
    result = choose_reusable_asset(requirement, [retired, matching], now=datetime(2026, 9, 30, tzinfo=UTC))
    assert result is not None
    assert result.asset.id == matching.id
    assert result.score == pytest.approx(1.0)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-206")
def test_asset_selection_uses_recent_asset_only_when_no_alternative_matches() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    requirement = AssetRequirement("image", "photo", "bridge flood", subjects=("bridge",), tags=("bridge", "flood"))
    recent = asset(
        description="Bridge flood",
        tags=["bridge", "flood"],
        subjects=["bridge"],
        last_used_at=now - timedelta(days=1),
    )
    alternative = asset(
        description="Bridge flood",
        tags=["bridge", "flood"],
        subjects=["bridge"],
        last_used_at=now - timedelta(days=10),
    )
    result = choose_reusable_asset(requirement, [recent, alternative], now=now)
    assert result is not None
    assert result.asset.id == alternative.id


@pytest.mark.unit
@pytest.mark.req("CF-REQ-207")
@pytest.mark.req("CF-REQ-210")
def test_external_candidates_rank_relevance_and_reject_unknown_license_and_small_images() -> None:
    requirement = AssetRequirement("image", "photo", "Parliament vote", min_width=720)
    unrelated = MediaCandidate(
        "https://media.example/1", "https://media.example/1.jpg", "fake", "CC0", "image", 1200, 800, "Forest"
    )
    relevant = MediaCandidate(
        "https://media.example/2", "https://media.example/2.jpg", "fake", "CC0", "image", 1000, 1600, "Parliament vote"
    )
    unlicensed = MediaCandidate(
        "https://media.example/3", "https://media.example/3.jpg", "fake", "", "image", 1200, 1600, "Parliament vote"
    )
    small = MediaCandidate(
        "https://media.example/4", "https://media.example/4.jpg", "fake", "CC0", "image", 400, 300, "Parliament vote"
    )
    assert rank_media_candidates(requirement, [unrelated, unlicensed, small, relevant]) == [relevant, unrelated]
