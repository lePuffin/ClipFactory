from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from clipfactory.assets.title_cards import create_title_card_asset
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import AssetRow
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.storage import LocalStorageProvider


@pytest.mark.unit
@pytest.mark.req("CF-REQ-200")
@pytest.mark.req("CF-REQ-202")
@pytest.mark.req("CF-REQ-209")
@pytest.mark.asyncio
async def test_title_card_asset_is_content_addressed_and_reused(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    assets = AssetRepository(sessions)
    storage = LocalStorageProvider(tmp_path / "media")
    now = datetime(2026, 9, 30, tzinfo=UTC)

    first = await create_title_card_asset("Story headline", storage=storage, assets=assets, now=now)
    second = await create_title_card_asset("Story headline", storage=storage, assets=assets, now=now)

    assert first.asset.id == second.asset.id
    assert not first.reused
    assert second.reused
    assert await storage.exists(first.asset.storage_key)
    assert first.asset.provenance.license == "CC0"
    with sessions() as session:
        assert len(list(session.scalars(select(AssetRow)))) == 1
    engine.dispose()
