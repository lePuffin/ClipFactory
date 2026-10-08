"""Provider-neutral licensed media discovery and bounded download contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaSearchRequest:
    description: str
    media_type: str
    subjects: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    limit: int = 10


@dataclass(frozen=True, slots=True)
class MediaCandidate:
    url: str
    download_url: str
    source: str
    license: str
    media_type: str
    width: int
    height: int
    description: str = ""
    author: str | None = None
    license_url: str | None = None
    attribution_required: bool = False
    attribution_text: str | None = None
    duration_seconds: float | None = None
    download_tracking_url: str | None = None
    preview_url: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    storage_key: str
    size_bytes: int
    sha256: str


class MediaSourceProvider(Protocol):
    name: str

    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]: ...

    async def download(self, candidate: MediaCandidate, dest: str, max_bytes: int) -> DownloadedMedia: ...
