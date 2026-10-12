"""Retire metadata and remove only the owning Run's external production inputs."""

import asyncio
from uuid import UUID

from clipfactory.domain.models import AssetStatus
from clipfactory.ports.assets import AssetRepository
from clipfactory.ports.storage import MediaStorage


async def retire_run_external_assets(run_id: UUID, *, assets: AssetRepository, storage: MediaStorage) -> None:
    errors: list[OSError] = []
    for asset in await asyncio.to_thread(assets.external_for_run, run_id):
        await asyncio.to_thread(assets.update, asset.id, status=AssetStatus.RETIRED)
        try:
            await storage.delete(asset.storage_key)
        except OSError as exc:
            errors.append(exc)
    if errors:
        raise OSError(f"Could not delete {len(errors)} retired external input file(s)") from errors[0]
