"""Bounded candidate previews from licensed provider URLs or local library media."""

import asyncio
import io
from uuid import UUID

import httpx
from PIL import Image

from clipfactory.infrastructure.http import ResponseTooLarge, UnsafeURL
from clipfactory.ports.assets import AssetReader
from clipfactory.ports.llm import ImageInput
from clipfactory.ports.media_sources import MediaCandidate
from clipfactory.ports.storage import MediaStorage


class CandidatePreviews:
    def __init__(self, http, assets: AssetReader, storage: MediaStorage, media) -> None:
        self.http, self.assets, self.storage, self.media = http, assets, storage, media

    async def __call__(self, candidate: MediaCandidate) -> ImageInput | None:
        try:
            if candidate.url.startswith("asset:"):
                asset = await asyncio.to_thread(self.assets.get, UUID(candidate.url[6:]))
                if asset is None:
                    return None
                path = self.storage.local_path(asset.storage_key)
                if asset.media_type == "video":
                    body = await self.media.extract_frame(path, min(0.5, (asset.duration_seconds or 0) / 2), 512)
                else:
                    body = await asyncio.to_thread(path.read_bytes)
            else:
                url = candidate.preview_url or (candidate.download_url if candidate.media_type == "image" else None)
                if not url:
                    return None
                body, _, _ = await self.http.get_bytes(url, max_bytes=5_000_000)
            content = await asyncio.to_thread(_jpeg, body)
            return ImageInput(content, "image/jpeg", {"candidate_url": candidate.url})
        except (httpx.HTTPError, UnsafeURL, ResponseTooLarge, OSError, ValueError, Image.DecompressionBombError):
            return None


def _jpeg(body: bytes) -> bytes:
    with Image.open(io.BytesIO(body)) as image:
        if image.width * image.height > 40_000_000:
            raise ValueError("Candidate preview exceeds pixel bound")
        image.thumbnail((512, 512))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="JPEG", quality=75)
        return output.getvalue()
