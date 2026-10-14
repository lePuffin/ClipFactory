"""Provider-neutral media execution errors."""

from pathlib import Path
from typing import Any, Protocol


class MediaInspector(Protocol):
    async def probe(self, path: Path, /) -> dict[str, Any]: ...

    async def decode(self, path: Path, /) -> None: ...


class MediaProcessError(RuntimeError):
    def __init__(self, code: str, message: str, *, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.stderr_tail = stderr_tail
