"""Short-lived staging of Clips into a statically served public share (CF-REQ-461)."""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_LOGGER = logging.getLogger(__name__)


class PublicMediaStaging:
    """Copies a Clip to ``{token}.mp4`` in the share and removes it after the platform call."""

    def __init__(self, directory: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._directory = directory
        self._clock = clock or (lambda: datetime.now(UTC))

    def _available(self) -> bool:
        try:
            return self._directory.is_dir() and os.access(self._directory, os.W_OK)
        except OSError:
            return False

    def stage(self, clip_file: Path, signed_url: str) -> str:
        """Return the URL to hand to the platform; falls back to ``signed_url`` when the share is unavailable."""
        if not self._available():
            return signed_url
        self._sweep()
        parsed = urlsplit(signed_url)
        token = parsed.path.rsplit("/", 1)[-1]
        target = self._directory / f"{token}.mp4"
        temporary = self._directory / f".{token}.partial"
        try:
            shutil.copyfile(clip_file, temporary)
            temporary.replace(target)
        except OSError:
            _LOGGER.warning("public media staging failed; using the backend-served URL")
            temporary.unlink(missing_ok=True)
            return signed_url
        return urlunsplit((parsed.scheme, parsed.netloc, f"{parsed.path}.mp4", "", ""))

    def release(self, staged_url: str) -> None:
        name = urlsplit(staged_url).path.rsplit("/", 1)[-1]
        if not name.endswith(".mp4") or "/" in name:
            return
        try:
            (self._directory / name).unlink(missing_ok=True)
        except OSError:
            _LOGGER.warning("public media staged copy could not be removed")

    def _sweep(self) -> None:
        now = self._clock().timestamp()
        try:
            entries = list(self._directory.glob("*.mp4"))
        except OSError:
            return
        for entry in entries:
            parts = entry.name.split(".")
            if len(parts) != 4:
                continue
            try:
                expired = int(parts[1]) <= now
            except ValueError:
                continue
            if expired:
                entry.unlink(missing_ok=True)
