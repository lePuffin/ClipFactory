from datetime import UTC, datetime
from typing import Any

import pytest
from test_asset_acquisition import Assets, Inspector, Source

from clipfactory.assets.acquisition import acquire_asset
from clipfactory.assets.selection import AssetRequirement
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.media_sources import MediaCandidate


@pytest.mark.unit
@pytest.mark.req("CF-REQ-207")
@pytest.mark.asyncio
async def test_more_relevant_later_provider_beats_first_provider(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)

    class RankedSource(Source):
        def __init__(self, name, description):
            super().__init__(storage)
            self.name = name
            self.description = description

        async def search(self, request):
            return [
                MediaCandidate(
                    f"https://{self.name}.example/1",
                    f"https://{self.name}.example/1.jpg",
                    self.name,
                    "CC0",
                    "image",
                    800,
                    1200,
                    self.description,
                )
            ]

    first = RankedSource("first", "Coffee beans")
    second = RankedSource("second", "Mokha Yemen port")
    result = await acquire_asset(
        AssetRequirement("image", "photo", "Mokha Yemen port", min_width=720),
        providers=[first, second],
        storage=storage,
        assets=Assets(),
        media=Inspector(),
        now=datetime(2026, 10, 5, tzinfo=UTC),
    )
    assert result is not None
    assert result.provenance.provider == "second"
    assert first.downloaded == []
    assert len(second.downloaded) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-202")
@pytest.mark.req("CF-REQ-206")
@pytest.mark.asyncio
async def test_identical_content_from_different_urls_cannot_repeat_used_asset(tmp_path) -> None:
    storage = LocalStorageProvider(tmp_path)
    assets = Assets()
    source = Source(storage)
    args: dict[str, Any] = dict(
        providers=[source], storage=storage, assets=assets, media=Inspector(), now=datetime(2026, 10, 5, tzinfo=UTC)
    )
    requirement = AssetRequirement("image", "photo", "Parliament vote", min_width=720)
    first = await acquire_asset(requirement, **args)
    assert first is not None
    second = await acquire_asset(requirement, excluded_asset_ids=frozenset({str(first.id)}), **args)
    assert second is None
    assert len(assets.items) == 1
