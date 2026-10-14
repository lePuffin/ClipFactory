from pathlib import Path
from uuid import uuid4

import pytest

from clipfactory.infrastructure.storage import LocalStorageProvider


@pytest.mark.unit
@pytest.mark.req("CF-NFR-105")
def test_local_storage_rejects_traversal_and_absolute_keys(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path)
    for key in ("../etc/passwd", "/abs", "a/../../b", "a/.."):
        with pytest.raises(ValueError, match="invalid storage key"):
            storage.local_path(key)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-202")
@pytest.mark.asyncio
async def test_local_storage_writes_and_reads_atomically(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path / "data")
    source = tmp_path / "input.bin"
    source.write_bytes(b"clipfactory-media")
    digest = await storage.put_file(source, "assets/ab/example.bin")
    assert len(digest) == 64
    assert await storage.exists("assets/ab/example.bin")
    assert b"".join([part async for part in storage.open("assets/ab/example.bin")]) == source.read_bytes()
    assert storage.work_dir(uuid4()).is_dir()
