"""Minimal storage operations consumed by media production use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class MediaStorage(Protocol):
    async def exists(self, key: str) -> bool: ...

    async def put_file(self, source: Path, key: str) -> str: ...

    async def put_bytes(self, key: str, value: bytes) -> str: ...

    async def read_bytes(self, key: str) -> bytes: ...

    def local_path(self, key: str) -> Path: ...
