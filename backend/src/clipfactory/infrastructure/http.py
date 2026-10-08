"""SSRF-aware HTTP client with redirect and response-size bounds."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx


class UnsafeURL(ValueError):
    """Raised when a URL or one of its resolved addresses is unsafe."""


class ResponseTooLarge(ValueError):
    """Raised when a streaming response exceeds its configured bound."""


Resolver = Callable[[str, int], list[str]]


def _resolve_addresses(host: str, port: int) -> list[str]:
    return [str(result[4][0]) for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


class SafeHTTPClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20,
        max_redirects: int = 5,
        resolver: Resolver = _resolve_addresses,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.transport = transport

    async def get_bytes(
        self, url: str, *, max_bytes: int, headers: dict[str, str] | None = None
    ) -> tuple[bytes, str, httpx.Headers]:
        current_url = url
        request_headers = httpx.Headers({"User-Agent": "ClipFactory/1.0", **(headers or {})})
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        ) as client:
            for redirect_count in range(self.max_redirects + 1):
                await self.validate_url(current_url)
                async with client.stream("GET", current_url, headers=request_headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location or redirect_count == self.max_redirects:
                            raise UnsafeURL("redirect limit exceeded")
                        redirected_url = urljoin(current_url, location)
                        if (urlsplit(redirected_url).scheme, urlsplit(redirected_url).netloc) != (
                            urlsplit(current_url).scheme,
                            urlsplit(current_url).netloc,
                        ):
                            request_headers.pop("Authorization", None)
                        current_url = redirected_url
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise ResponseTooLarge("response exceeds configured size limit")
                    return bytes(body), str(response.url), response.headers
        raise UnsafeURL("redirect limit exceeded")

    async def validate_url(self, url: str) -> None:
        if len(url) > 2048:
            raise UnsafeURL("URL exceeds 2048 characters")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise UnsafeURL("URL must be HTTP(S), include a host and contain no credentials")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = await asyncio.to_thread(self.resolver, parts.hostname, port)
        except (OSError, socket.gaierror) as exc:
            raise UnsafeURL("host could not be resolved") from exc
        if not addresses:
            raise UnsafeURL("host did not resolve")
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if not parsed.is_global:
                raise UnsafeURL("URL resolves to a non-public address")
