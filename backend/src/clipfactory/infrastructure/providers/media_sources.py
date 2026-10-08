"""Licensed media APIs: Pexels/Pixabay licences, Unsplash tracking, Commons per-file attribution."""

import hashlib
import json
import re
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from clipfactory.infrastructure.http import ResponseTooLarge, SafeHTTPClient, UnsafeURL
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.media_sources import DownloadedMedia, MediaCandidate, MediaSearchRequest
from clipfactory.ports.storage import MediaStorage


class HTTPMediaSource:
    name = "media"

    def __init__(self, http: SafeHTTPClient, storage: MediaStorage, *, api_key: str | None = None) -> None:
        self.http = http
        self.storage = storage
        self.api_key = api_key

    async def _json(self, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            body, _, _ = await self.http.get_bytes(url, max_bytes=2000000, headers=headers)
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ProviderError(
                f"http_{status}",
                f"{self.name} search returned HTTP {status}",
                transient=status in {408, 429} or status >= 500,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("network_error", f"{self.name} could not be reached", transient=True) from exc
        except (ValueError, UnsafeURL, ResponseTooLarge) as exc:
            raise ProviderError(
                "invalid_response", f"{self.name} returned an invalid media response", transient=False
            ) from exc

    async def download(self, candidate: MediaCandidate, dest: str, max_bytes: int) -> DownloadedMedia:
        try:
            body, _, _ = await self.http.get_bytes(candidate.download_url, max_bytes=max_bytes)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ProviderError(
                f"http_{status}",
                f"{self.name} download returned HTTP {status}",
                transient=status in {408, 429} or status >= 500,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError("network_error", f"{self.name} download could not be reached", transient=True) from exc
        except (UnsafeURL, ResponseTooLarge) as exc:
            raise ProviderError(
                "invalid_media", f"{self.name} download was unsafe or exceeded its size limit", transient=False
            ) from exc
        digest = hashlib.sha256(body).hexdigest()
        await self.storage.put_bytes(dest, body)
        return DownloadedMedia(dest, len(body), digest)


def _query(request: MediaSearchRequest) -> str:
    if request.subjects:
        return " ".join(request.subjects)[:100]
    if request.tags:
        return " ".join(request.tags[:4])[:100]
    stopwords = {
        "a",
        "an",
        "the",
        "of",
        "and",
        "with",
        "in",
        "at",
        "by",
        "for",
        "to",
        "visual",
        "representation",
        "depiction",
        "image",
        "illustration",
        "showing",
        "providing",
        "being",
        "taking",
        "control",
        "support",
        "forces",
    }
    terms = [term for term in re.findall("[\\w]+", request.description) if term.casefold() not in stopwords]
    return " ".join(terms[:5])[:100]


class PexelsMediaSource(HTTPMediaSource):
    name = "pexels"

    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]:
        if not self.api_key:
            return []
        params = urlencode({"query": _query(request), "per_page": min(request.limit, 80)})
        candidates = []
        if request.media_type in {"video", "any"}:
            body = await self._json(f"https://api.pexels.com/videos/search?{params}", {"Authorization": self.api_key})
            for item in body.get("videos", []):
                files = [
                    entry
                    for entry in item.get("video_files", [])
                    if entry.get("file_type") == "video/mp4" and int(entry.get("height") or 0) >= 720
                ]
                if not files:
                    continue
                selected = min(files, key=lambda entry: abs(int(entry.get("height") or 0) - 1080))
                author = item.get("user", {}).get("name", "Pexels contributor")
                candidates.append(
                    MediaCandidate(
                        item["url"],
                        selected["link"],
                        self.name,
                        "Pexels License",
                        "video",
                        int(selected["width"]),
                        int(selected["height"]),
                        description=item.get("url", "").rsplit("/", 2)[-2].replace("-", " "),
                        author=author,
                        license_url="https://www.pexels.com/license/",
                        attribution_text=f"Video by {author} on Pexels: {item['url']}",
                        duration_seconds=float(item["duration"]),
                        preview_url=item.get("image"),
                    )
                )
        if request.media_type == "image" or (request.media_type == "any" and len(candidates) < request.limit):
            body = await self._json(f"https://api.pexels.com/v1/search?{params}", {"Authorization": self.api_key})
            for item in body.get("photos", []):
                author = item.get("photographer", "Pexels contributor")
                candidates.append(
                    MediaCandidate(
                        item["url"],
                        item["src"]["original"],
                        self.name,
                        "Pexels License",
                        "image",
                        int(item["width"]),
                        int(item["height"]),
                        description=item.get("alt") or _query(request),
                        preview_url=item["src"].get("medium"),
                        author=author,
                        license_url="https://www.pexels.com/license/",
                        attribution_text=f"Photo by {author} on Pexels: {item['url']}",
                    )
                )
        return candidates[: request.limit]


class PixabayMediaSource(HTTPMediaSource):
    name = "pixabay"

    def __init__(self, http: SafeHTTPClient, storage: MediaStorage, *, api_key: str | None = None) -> None:
        super().__init__(http, storage, api_key=api_key)
        self._cache: dict[tuple[str, str, int], tuple[float, list[MediaCandidate]]] = {}

    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]:
        if not self.api_key:
            return []
        cache_key = (_query(request), request.media_type, request.limit)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 86400:
            return list(cached[1])
        kinds = ("video", "image") if request.media_type == "any" else (request.media_type,)
        candidates = []
        for kind in kinds:
            endpoint = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
            params = urlencode(
                {
                    "key": self.api_key,
                    "q": _query(request),
                    "per_page": max(3, min(request.limit, 200)),
                    "safesearch": "true",
                }
            )
            body = await self._json(endpoint + "?" + params)
            for item in body.get("hits", []):
                if kind == "video":
                    files = [
                        entry
                        for entry in item.get("videos", {}).values()
                        if entry.get("url") and int(entry.get("height") or 0) >= 720
                    ]
                    if not files:
                        continue
                    selected = min(files, key=lambda entry: abs(int(entry["height"]) - 1080))
                    url, width, height = (selected["url"], selected["width"], selected["height"])
                else:
                    url = item.get("imageURL") or item.get("fullHDURL") or item.get("largeImageURL")
                    if not url:
                        continue
                    width, height = (item["imageWidth"], item["imageHeight"])
                author = item.get("user", "Pixabay contributor")
                candidates.append(
                    MediaCandidate(
                        item["pageURL"],
                        url,
                        self.name,
                        "Pixabay Content License",
                        kind,
                        int(width),
                        int(height),
                        description=item.get("tags", ""),
                        preview_url=item.get("previewURL") or item.get("pictureURL"),
                        author=author,
                        license_url="https://pixabay.com/service/license-summary/",
                        attribution_text=f"{author} / Pixabay: {item['pageURL']}",
                        duration_seconds=float(item["duration"]) if kind == "video" else None,
                    )
                )
            if len(candidates) >= request.limit:
                break
        result = candidates[: request.limit]
        self._cache[cache_key] = (time.monotonic(), result)
        return result


class UnsplashMediaSource(HTTPMediaSource):
    name = "unsplash"

    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]:
        if not self.api_key or request.media_type == "video":
            return []
        params = urlencode({"query": _query(request), "per_page": min(request.limit, 30), "content_filter": "high"})
        body = await self._json(
            f"https://api.unsplash.com/search/photos?{params}", {"Authorization": f"Client-ID {self.api_key}"}
        )
        candidates = []
        for item in body.get("results", []):
            author = item.get("user", {}).get("name", "Unsplash contributor")
            candidates.append(
                MediaCandidate(
                    item["links"]["html"],
                    item["urls"]["full"],
                    self.name,
                    "Unsplash License",
                    "image",
                    int(item["width"]),
                    int(item["height"]),
                    description=item.get("alt_description") or item.get("description") or _query(request),
                    author=author,
                    license_url="https://unsplash.com/license",
                    attribution_required=True,
                    attribution_text=f"Photo by {author} on Unsplash: {item['links']['html']}",
                    download_tracking_url=item["links"].get("download_location"),
                    preview_url=item["urls"].get("small"),
                )
            )
        return candidates

    async def download(self, candidate: MediaCandidate, dest: str, max_bytes: int) -> DownloadedMedia:
        if (
            not candidate.download_tracking_url
            or urlsplit(candidate.download_tracking_url).hostname != "api.unsplash.com"
        ):
            raise ProviderError(
                "invalid_response", "Unsplash download tracking URL is missing or invalid", transient=False
            )
        await self._json(candidate.download_tracking_url, {"Authorization": f"Client-ID {self.api_key}"})
        return await super().download(candidate, dest, max_bytes)


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain(value: str) -> str:
    parser = _PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


class WikimediaCommonsMediaSource(HTTPMediaSource):
    name = "wikimedia_commons"

    def __init__(self, http: SafeHTTPClient, storage: MediaStorage, *, user_agent: str) -> None:
        super().__init__(http, storage)
        self.user_agent = user_agent

    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]:
        if request.media_type == "video":
            return []
        params = urlencode(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": _query(request),
                "gsrnamespace": 6,
                "gsrlimit": min(request.limit, 50),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|thumbmime|extmetadata",
                "iiurlwidth": 1600,
            }
        )
        body = await self._json("https://commons.wikimedia.org/w/api.php?" + params, {"User-Agent": self.user_agent})
        candidates = []
        pages = sorted(body.get("query", {}).get("pages", {}).values(), key=lambda item: item.get("index", 0))
        for page in pages:
            for info in page.get("imageinfo", [])[:1]:
                if info.get("mime") not in {"image/jpeg", "image/png"} and info.get("thumbmime") not in {
                    "image/jpeg",
                    "image/png",
                }:
                    continue
                metadata = info.get("extmetadata", {})
                license_name = _plain(metadata.get("LicenseShortName", {}).get("value", ""))
                if re.search("\\b(?:NC|ND)\\b", license_name, re.IGNORECASE):
                    continue
                if not (license_name.startswith(("CC BY", "CC0")) or license_name.lower() == "public domain"):
                    continue
                author = _plain(metadata.get("Artist", {}).get("value", "")) or None
                url = info["descriptionurl"]
                candidates.append(
                    MediaCandidate(
                        url,
                        info.get("thumburl") or info["url"],
                        self.name,
                        license_name,
                        "image",
                        int(info.get("thumbwidth") or info["width"]),
                        int(info.get("thumbheight") or info["height"]),
                        description=_plain(metadata.get("ImageDescription", {}).get("value", page["title"])),
                        author=author,
                        license_url=metadata.get("LicenseUrl", {}).get("value"),
                        attribution_required=license_name.startswith("CC BY"),
                        attribution_text=f"{author or 'Wikimedia Commons contributor'}; "
                        + f"{page['title']}; {license_name}; {url}",
                    )
                )
        return candidates
