"""Resolve immutable Run research without consulting live settings or profiles."""

from collections.abc import Mapping
from typing import Any

from clipfactory.domain.models import ResearchPolicy
from clipfactory.domain.research_policy import ResearchControls


def run_research_policy(profile_snapshot: Mapping[str, Any], settings_snapshot: Mapping[str, Any]) -> ResearchPolicy:
    raw = dict(profile_snapshot.get("research", {}))
    # Old Runs split controls between the two snapshots. Presence, not truthiness,
    # distinguishes them from new complete policies (especially feeds: []).
    legacy = settings_snapshot.get("research", {})
    for key, default in ResearchControls().model_dump(mode="json").items():
        if key not in raw:
            raw[key] = legacy.get(key, default)
    return ResearchPolicy.model_validate(raw)
