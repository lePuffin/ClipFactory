"""Licensed media APIs: Pexels/Pixabay licences, Unsplash tracking, Commons per-file attribution."""

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from clipfactory.infrastructure.http import ResponseTooLarge, SafeHTTPClient, UnsafeURL
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.media_sources import DownloadedMedia, MediaCandidate, MediaSearchRequest, PersonPortraits
from clipfactory.ports.storage import MediaStorage

_POLITE_ATTEMPTS = 4


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

    def _download_headers(self) -> dict[str, str] | None:
        return None

    async def download(self, candidate: MediaCandidate, dest: str, max_bytes: int) -> DownloadedMedia:
        try:
            body, _, _ = await self.http.get_bytes(
                candidate.download_url, max_bytes=max_bytes, headers=self._download_headers()
            )
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
    polite_retry_base_seconds = 3.0

    def __init__(self, http: SafeHTTPClient, storage: MediaStorage, *, user_agent: str) -> None:
        super().__init__(http, storage)
        self.user_agent = user_agent

    def _download_headers(self) -> dict[str, str] | None:
        # Wikimedia throttles generic agents on upload.wikimedia.org far harder than policy-compliant ones.
        return {"User-Agent": self.user_agent}

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
        pages = sorted(body.get("query", {}).get("pages", {}).values(), key=lambda item: item.get("index", 0))
        return self._candidates(pages)

    def _candidates(self, pages: list[dict[str, Any]]) -> list[MediaCandidate]:
        candidates = []
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
                open_government = re.fullmatch(r"OGL\s*v?3(?:\.0)?", license_name, re.IGNORECASE) is not None
                if not (
                    license_name.startswith(("CC BY", "CC0"))
                    or license_name.lower() == "public domain"
                    or open_government
                ):
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
                        attribution_required=license_name.startswith("CC BY") or open_government,
                        attribution_text=f"{author or 'Wikimedia Commons contributor'}; "
                        + f"{page['title']}; {license_name}; {url}",
                    )
                )
        return candidates

    async def _polite_json(self, url: str, headers: dict[str, str]) -> dict[str, Any]:
        """Wikimedia APIs rate-limit bursts; back off on transient errors instead of failing the shot."""
        for attempt in range(_POLITE_ATTEMPTS):
            try:
                return await self._json(url, headers)
            except ProviderError as exc:
                if not exc.transient or attempt == _POLITE_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(self.polite_retry_base_seconds * 2**attempt)
        raise AssertionError("unreachable")

    async def _depicted_portraits(
        self, entity_id: str, label: str, limit: int, min_short_side_px: int, headers: dict[str, str]
    ) -> list[MediaCandidate]:
        """Commons files whose structured "depicts" (P180) is this human and whose title names them (CF-REQ-268)."""
        body = await self._polite_json(
            "https://commons.wikimedia.org/w/api.php?"
            + urlencode(
                {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": f"haswbstatement:P180={entity_id} filetype:bitmap",
                    "gsrnamespace": 6,
                    "gsrlimit": 20,
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|thumbmime|extmetadata",
                    "iiurlwidth": 1600,
                }
            ),
            headers,
        )
        name_tokens = set(_name_tokens(label))
        pages = [
            page
            for page in body.get("query", {}).get("pages", {}).values()
            if name_tokens and name_tokens <= set(_name_tokens(str(page.get("title", ""))))
        ]
        pages.sort(key=lambda page: int(page.get("index", 0)))
        found = [item for item in self._candidates(pages) if min(item.width, item.height) >= min_short_side_px]
        # Upright framing first: a portrait-format file is more likely a single-person portrait.
        found.sort(key=lambda item: item.width > item.height)
        return found[:limit]

    async def find_person(self, name: str, limit: int = 3, min_short_side_px: int = 0) -> PersonPortraits | None:
        """Resolve a human through Wikidata and return licensed Commons portraits (CF-REQ-268).

        P18 images come first; when none meets ``min_short_side_px``, Commons files whose structured
        "depicts" statement is the same Wikidata item (and whose title names the person) are used instead.
        """
        headers = {"User-Agent": self.user_agent}
        wikidata = "https://www.wikidata.org/w/api.php?"
        search = await self._polite_json(
            wikidata
            + urlencode(
                {
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": "en",
                    "uselang": "en",
                    "type": "item",
                    "limit": 10,
                    "search": name,
                }
            ),
            headers,
        )
        ids = [str(item["id"]) for item in search.get("search", []) if str(item.get("id", "")).startswith("Q")]
        surname_only = len(_normalized_name(name).split()) == 1
        if surname_only:
            # Prefix search misses "Keir Starmer" for "Starmer"; full-text search over humans finds full names.
            humans = await self._polite_json(
                wikidata
                + urlencode(
                    {
                        "action": "query",
                        "format": "json",
                        "list": "search",
                        "srnamespace": 0,
                        "srlimit": 10,
                        "srsearch": f"{name} haswbstatement:P31=Q5",
                    }
                ),
                headers,
            )
            found = [str(item.get("title", "")) for item in humans.get("query", {}).get("search", [])]
            ids = list(dict.fromkeys([*ids, *(item for item in found if item.startswith("Q"))]))[:50]
        if not ids:
            return None
        entities = (
            await self._polite_json(
                wikidata
                + urlencode(
                    {
                        "action": "wbgetentities",
                        "format": "json",
                        "ids": "|".join(ids),
                        "props": "labels|aliases|sitelinks",
                        "languages": "en|mul",
                    }
                ),
                headers,
            )
        ).get("entities", {})
        ranked = sorted(
            (
                (match, len(entity.get("sitelinks", {})), position, entity_id)
                for position, entity_id in enumerate(ids)
                if (entity := entities.get(entity_id)) and (match := _person_name_match(name, entity))
            ),
            key=lambda item: (-item[0], -item[1], item[2]),
        )
        if surname_only:
            # A bare surname is ambiguous: accept only a clearly dominant, widely linked bearer (CF-REQ-268).
            ranked.sort(key=lambda item: (-item[1], item[2]))
            if not ranked or ranked[0][1] < _SURNAME_MIN_SITELINKS:
                return None
            if len(ranked) > 1 and ranked[0][1] < _SURNAME_DOMINANCE * ranked[1][1]:
                return None
        for _, _, _, entity_id in ranked[: 1 if surname_only else 4]:
            claims = (
                await self._polite_json(
                    wikidata
                    + urlencode({"action": "wbgetclaims", "format": "json", "entity": entity_id, "property": "P31"}),
                    headers,
                )
            ).get("claims", {})
            if "Q5" not in _claim_values(claims, "P31"):
                continue
            images = _claim_values(
                (
                    await self._polite_json(
                        wikidata
                        + urlencode(
                            {"action": "wbgetclaims", "format": "json", "entity": entity_id, "property": "P18"}
                        ),
                        headers,
                    )
                ).get("claims", {}),
                "P18",
            )[:limit]
            candidates: list[MediaCandidate] = []
            if images:
                body = await self._polite_json(
                    "https://commons.wikimedia.org/w/api.php?"
                    + urlencode(
                        {
                            "action": "query",
                            "format": "json",
                            "titles": "|".join(f"File:{image}" for image in images),
                            "prop": "imageinfo",
                            "iiprop": "url|size|mime|thumbmime|extmetadata",
                            "iiurlwidth": 1600,
                        }
                    ),
                    headers,
                )
                order = {f"File:{image}".replace("_", " "): index for index, image in enumerate(images)}
                pages = sorted(
                    body.get("query", {}).get("pages", {}).values(),
                    key=lambda item: order.get(str(item.get("title", "")).replace("_", " "), len(order)),
                )
                candidates = self._candidates(list(pages))
            candidates = [item for item in candidates if min(item.width, item.height) >= min_short_side_px]
            labels = entities[entity_id].get("labels", {})
            label = (labels.get("en") or labels.get("mul") or {}).get("value") or name
            if not candidates:
                candidates = await self._depicted_portraits(entity_id, label, limit, min_short_side_px, headers)
            return PersonPortraits(
                label, f"wikidata:{entity_id}", f"https://www.wikidata.org/wiki/{entity_id}", tuple(candidates)
            )
        return None


_SURNAME_MIN_SITELINKS = 20
_SURNAME_DOMINANCE = 2


def _name_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value.casefold()))


def _normalized_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in folded if char.isalnum() or char.isspace()).split())


def _person_name_match(name: str, entity: dict[str, Any]) -> int:
    """3 = exact label, 2 = exact alias, 1 = same first and last name tokens (spelling variants), 0 = unrelated.

    English and language-neutral (``mul``) labels and aliases both count; many names live only under ``mul``.
    """
    wanted = _normalized_name(name)
    labels = [entity.get("labels", {}).get(language, {}).get("value", "") for language in ("en", "mul")]
    aliases = [
        item.get("value", "") for language in ("en", "mul") for item in entity.get("aliases", {}).get(language, [])
    ]
    if wanted in {_normalized_name(item) for item in labels if item}:
        return 3
    normalized = [_normalized_name(item) for item in [*labels, *aliases] if item]
    if wanted in normalized:
        return 2
    parts = wanted.split()
    for item in normalized:
        tokens = item.split()
        if len(parts) == 1 and len(tokens) >= 2 and _similar_surname(parts[0], tokens[-1]):
            return 1
        if len(parts) >= 2 and len(tokens) >= 2 and parts[0] == tokens[0] and _similar_surname(parts[-1], tokens[-1]):
            return 1
    return 0


def _similar_surname(left: str, right: str) -> bool:
    """Transliteration variants such as Zelensky/Zelenskyy share a long common prefix."""
    return min(len(left), len(right)) >= 4 and (left.startswith(right[:5]) or right.startswith(left[:5]))


def _claim_values(claims: dict[str, Any], prop: str) -> list[str]:
    values: list[str] = []
    for claim in claims.get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and "id" in value:
            values.append(str(value["id"]))
        elif isinstance(value, str):
            values.append(value)
    return values
