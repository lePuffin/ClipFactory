import hashlib
import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from clipfactory.assets.acquisition import acquire_asset
from clipfactory.assets.selection import AssetRequirement
from clipfactory.domain.models import AssetOrigin
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.media_sources import DownloadedMedia, MediaCandidate


class Assets:
    def __init__(self):
        self.items = []

    def by_hash(self, sha256):
        return next((asset for asset in self.items if asset.sha256 == sha256), None)

    def save(self, asset):
        self.items.append(asset)
        return asset


class Source:
    name = "fake"

    def __init__(self, storage, media_type="image"):
        self.storage = storage
        self.media_type = media_type
        self.downloaded = []

    async def search(self, request):
        return [
            MediaCandidate(
                f"https://source.example/{index}",
                f"https://source.example/{index}.jpg",
                self.name,
                "CC0",
                self.media_type,
                800,
                1200,
                description="Parliament vote" if index == 1 else "Forest",
            )
            for index in range(3)
        ]

    async def download(self, candidate, dest, max_bytes):
        self.downloaded.append(candidate)
        output = io.BytesIO()
        Image.new("RGB", (800, 1200), "red").save(output, format="JPEG")
        body = output.getvalue()
        await self.storage.put_bytes(dest, body)
        return DownloadedMedia(dest, len(body), hashlib.sha256(body).hexdigest())


class Inspector:
    async def probe(self, path):
        raise AssertionError("Images must not be probed as video")

    async def decode(self, path):
        raise AssertionError("Images must not be decoded as video")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-207")
@pytest.mark.req("CF-REQ-201")
@pytest.mark.req("CF-REQ-211")
@pytest.mark.asyncio
async def test_only_chosen_candidate_downloaded_and_external_provenance_is_persisted(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    assets = Assets()
    source = Source(storage)
    result = await acquire_asset(
        AssetRequirement("image", "photo", "Parliament vote", min_width=720),
        providers=[source],
        storage=storage,
        assets=assets,
        media=Inspector(),
        now=datetime(2026, 10, 5, tzinfo=UTC),
    )
    assert result is not None
    assert len(source.downloaded) == 1
    assert source.downloaded[0].url == "https://source.example/1"
    assert result.provenance.origin == AssetOrigin.EXTERNAL
    assert result.provenance.source_url == "https://source.example/1"
    assert result.width == 800
    assert result.height == 1200
    assert result.reusable
    assert await storage.exists(result.storage_key)
    assert not list((tmp_path / "work/media-downloads").glob("*.media"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-210")
@pytest.mark.asyncio
async def test_mislabeled_video_is_rejected_before_activation(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    assets = Assets()
    result = await acquire_asset(
        AssetRequirement("video", "broll", "Parliament vote", min_height=720),
        providers=[Source(storage, "video")],
        storage=storage,
        assets=assets,
        media=Inspector(),
        now=datetime(2026, 10, 5, tzinfo=UTC),
    )
    assert result is None
    assert assets.items == []


@pytest.mark.unit
@pytest.mark.req("CF-NFR-010")
@pytest.mark.req("CF-REQ-207")
@pytest.mark.asyncio
async def test_transient_search_is_retried_without_waiting_in_test(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    delays = []

    class TransientSource(Source):
        calls = 0

        async def search(self, request):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("rate_limited", "Limited", transient=True)
            return await super().search(request)

    async def record_delay(seconds):
        delays.append(seconds)

    source = TransientSource(storage)
    result = await acquire_asset(
        AssetRequirement("image", "photo", "Parliament vote", min_width=720),
        providers=[source],
        storage=storage,
        assets=Assets(),
        media=Inspector(),
        now=datetime(2026, 10, 5, tzinfo=UTC),
        max_call_retries=1,
        sleep=record_delay,
    )
    assert result is not None
    assert source.calls == 2
    assert len(delays) == 1
