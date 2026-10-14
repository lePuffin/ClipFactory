"""Deterministic local music selection from canonical Asset metadata."""

from __future__ import annotations

from collections.abc import Sequence

from clipfactory.domain.models import Asset, AssetStatus, MusicPolicy, Platform


def select_music(
    assets: Sequence[Asset],
    policy: MusicPolicy,
    *,
    platforms: Sequence[Platform],
    clip_duration_seconds: float,
) -> Asset | None:
    if not policy.enabled:
        return None
    enabled = set(platforms)
    eligible = [
        asset
        for asset in assets
        if asset.category == "music"
        and asset.status == AssetStatus.ACTIVE
        and asset.music is not None
        and bool(asset.provenance.license.strip())
        and (asset.music.allowed_platforms is None or enabled <= set(asset.music.allowed_platforms))
        and (asset.music.loopable or (asset.duration_seconds or 0) >= clip_duration_seconds)
    ]
    wanted_moods = {value.casefold() for value in policy.mood_tags}

    def rank(asset: Asset) -> tuple[int, int, float, str]:
        assert asset.music is not None
        mood_overlap = len(wanted_moods & {value.casefold() for value in asset.music.mood})
        energy_match = int(policy.energy is not None and asset.music.energy == policy.energy)
        last_used = asset.last_used_at.timestamp() if asset.last_used_at else 0.0
        return (-mood_overlap, -energy_match, last_used, asset.music.title.casefold())

    return min(eligible, key=rank) if eligible else None
