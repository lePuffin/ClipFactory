from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from clipfactory.assets.retention import retire_run_external_assets
from clipfactory.assets.selection import AssetRequirement, choose_reusable_asset
from clipfactory.domain.models import Asset, AssetOrigin, AssetStatus, Provenance
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.storage import LocalStorageProvider

NOW = datetime(2026, 10, 11, tzinfo=UTC)


def asset(key, *, origin=AssetOrigin.EXTERNAL, status=AssetStatus.ACTIVE):
    return Asset(
        media_type="image",
        category="photo",
        storage_key=key,
        sha256=uuid4().hex * 2,
        mime_type="image/png",
        size_bytes=4,
        description="parliament",
        tags=["parliament"],
        subjects=["parliament"],
        status=status,
        provenance=Provenance(
            origin=origin,
            provider="fake",
            license="CC BY 4.0",
            source_url="https://example.org/photo",
            attribution_required=True,
            attribution_text="Author — CC BY 4.0",
            acquired_at=NOW,
            generation={"model": "fake"} if origin in {AssetOrigin.GENERATED, AssetOrigin.RENDERED} else None,
        ),
        created_at=NOW,
    )


@pytest.fixture
def resources(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.db'}")
    Base.metadata.create_all(engine)
    yield AssetRepository(create_session_factory(engine)), LocalStorageProvider(tmp_path / "storage")
    engine.dispose()


@pytest.mark.req("CF-REQ-214")
@pytest.mark.req("CF-REQ-203")
@pytest.mark.req("CF-REQ-212")
@pytest.mark.asyncio
async def test_cleanup_is_run_scoped_preserves_metadata_generated_and_legacy(resources):
    assets, storage = resources
    run_id, other_id = uuid4(), uuid4()
    external = asset(f"assets/external-runs/{run_id}/input.png").model_copy(
        update={"usage_count": 7, "last_used_at": NOW}
    )
    others = [
        asset(f"assets/external-runs/{other_id}/input.png"),
        asset("assets/legacy.png"),
        asset("assets/generated.png", origin=AssetOrigin.GENERATED),
        asset("assets/rendered.png", origin=AssetOrigin.RENDERED),
        asset("assets/imported.png", origin=AssetOrigin.IMPORTED),
    ]
    for item in [external, *others]:
        assets.save(item)
        await storage.put_bytes(item.storage_key, b"data")
    await retire_run_external_assets(run_id, assets=assets, storage=storage)
    await retire_run_external_assets(run_id, assets=assets, storage=storage)
    saved = assets.get(external.id)
    assert saved is not None
    assert saved.status == AssetStatus.RETIRED
    assert saved.provenance == external.provenance
    assert saved.usage_count == 7
    assert saved.last_used_at is not None
    assert saved.last_used_at.replace(tzinfo=UTC) == NOW
    assert not await storage.exists(external.storage_key)
    assert all([await storage.exists(item.storage_key) for item in others])
    for item in others:
        saved_other = assets.get(item.id)
        assert saved_other is not None
        assert saved_other.status == AssetStatus.ACTIVE


@pytest.mark.req("CF-REQ-205")
@pytest.mark.req("CF-REQ-211")
@pytest.mark.parametrize("status", [AssetStatus.ACTIVE, AssetStatus.RETIRED])
def test_external_assets_never_cross_run_reuse(status):
    external = asset("assets/external.png", status=status)
    generated = asset("assets/generated.png", origin=AssetOrigin.GENERATED)
    requirement = AssetRequirement("image", "photo", "parliament", ("parliament",), ("parliament",))
    assert choose_reusable_asset(requirement, [external], now=NOW) is None
    match = choose_reusable_asset(requirement, [external, generated], now=NOW)
    assert match is not None
    assert match.asset.id == generated.id


@pytest.mark.req("CF-REQ-200")
def test_library_filter_applies_before_pagination_and_total(resources):
    assets, _ = resources
    removed = asset("assets/removed.png", status=AssetStatus.RETIRED)
    generated = asset("assets/generated.png", origin=AssetOrigin.GENERATED, status=AssetStatus.RETIRED)
    active = asset("assets/live.png")
    for item in [removed, generated, active]:
        assets.save(item)
    assert assets.count(saved_only=True) == 2
    assert assets.count(status=AssetStatus.RETIRED, saved_only=True) == 1
    assert [item.id for item in assets.list(status=AssetStatus.RETIRED, saved_only=True)] == [generated.id]
    assert len(assets.list(limit=1, saved_only=True)) == 1
    assert assets.list(offset=2, saved_only=True) == []
    retained = assets.get(removed.id)
    assert retained is not None
    assert retained.provenance == removed.provenance
    assert retained.status == AssetStatus.RETIRED


@pytest.mark.req("CF-REQ-214")
@pytest.mark.asyncio
async def test_cleanup_retires_all_rows_when_one_file_deletion_fails(resources) -> None:
    assets, storage = resources
    run_id = uuid4()
    inputs = [asset(f"assets/external-runs/{run_id}/{index}.png") for index in range(2)]
    for item in inputs:
        assets.save(item)
        await storage.put_bytes(item.storage_key, b"data")

    class FailingStorage(LocalStorageProvider):
        async def delete(self, key: str) -> None:
            if key == inputs[0].storage_key:
                raise OSError("fixture deletion failure")
            await storage.delete(key)

    with pytest.raises(OSError, match="Could not delete 1 retired external input"):
        await retire_run_external_assets(run_id, assets=assets, storage=FailingStorage(storage.root))
    for item in inputs:
        retired = assets.get(item.id)
        assert retired is not None
        assert retired.status == AssetStatus.RETIRED
    assert await storage.exists(inputs[0].storage_key)
    assert not await storage.exists(inputs[1].storage_key)
