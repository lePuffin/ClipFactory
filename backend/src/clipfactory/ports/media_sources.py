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


@dataclass(frozen=True, slots=True)
class PersonPortraits:
    """A named person bound to an authoritative identity with licensed real photographs (CF-REQ-268)."""

    name: str
    identity_ref: str
    identity_url: str
    candidates: tuple[MediaCandidate, ...]


class PersonPortraitSource(MediaSourceProvider, Protocol):
    """A media source that can also resolve a named human to licensed portraits (CF-REQ-268)."""

    async def find_person(self, name: str, limit: int = 3, min_short_side_px: int = 0) -> PersonPortraits | None:
        """Return the human matching ``name`` (empty candidates when no licensed photo of at least
        ``min_short_side_px`` on its short side), or None if unresolved."""
        ...
