"""Safe local filesystem implementation for media storage."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

_STORAGE_KEY = re.compile(r"^[a-z0-9][a-z0-9/_.-]*$")


class LocalStorageProvider:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def local_path(self, key: str) -> Path:
        if not _STORAGE_KEY.fullmatch(key) or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage key escapes the data directory")
        return path

    async def put_file(self, source: Path, key: str) -> str:
        target = self.local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        def copy_atomically() -> str:
            digest = hashlib.sha256()
            temporary = target.with_name(f".{target.name}.tmp")
            try:
                with source.open("rb") as source_file, temporary.open("wb") as output:
                    while chunk := source_file.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return digest.hexdigest()

        return await asyncio.to_thread(copy_atomically)

    async def put_bytes(self, key: str, value: bytes) -> str:
        target = self.local_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        def write_atomically() -> str:
            digest = hashlib.sha256(value).hexdigest()
            temporary = target.with_name(f".{target.name}.tmp")
            try:
                with temporary.open("wb") as output:
                    output.write(value)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            return digest

        return await asyncio.to_thread(write_atomically)

    async def read_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.local_path(key).read_bytes)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self.local_path(key)

        def read_all() -> bytes:
            return path.read_bytes()

        payload = await asyncio.to_thread(read_all)
        yield payload

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self.local_path(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.local_path(key).unlink, missing_ok=True)

    def work_dir(self, run_id: UUID) -> Path:
        path = self.local_path(f"work/{run_id}")
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def remove_work_dir(self, run_id: UUID) -> None:
        await asyncio.to_thread(shutil.rmtree, self.local_path(f"work/{run_id}"), True)
