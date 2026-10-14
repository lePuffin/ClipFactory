"""Resolve local framing evidence before building the immutable render contract."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from clipfactory.domain.portrait import FaceBox

logger = logging.getLogger(__name__)
FaceDetector = Callable[[Path], Awaitable[FaceBox | None]]


async def portrait_framing(
    path: Path,
    *,
    is_person_still: bool,
    retained: dict[str, Any] | None,
    detector: FaceDetector | None,
    source_sha256: str | None = None,
) -> tuple[FaceBox | None, dict[str, Any] | None]:
    if not is_person_still:
        return None, None
    if retained is not None and retained.get("source_sha256") == source_sha256:
        face = FaceBox(**retained["face_box"]) if retained.get("face_box") else None
        if face is None:
            logger.warning("portrait_framing_unavailable: retained fallback for %s", path.name)
        return face, {**retained, "version": "face-safe-v2"}
    try:
        face = await detector(path) if detector else None
    except (OSError, RuntimeError, ValueError):
        logger.warning("portrait_framing_unavailable: local detection failed for %s", path.name, exc_info=True)
        face = None
    if face is None:
        logger.warning("portrait_framing_unavailable: no confident dominant face for %s", path.name)
    return face, {
        "version": "face-safe-v2",
        "source_sha256": source_sha256,
        "detector_version": "local-frontal-face-v1",
        "status": "detected" if face else "unavailable",
        "face_box": asdict(face) if face else None,
        "fallback": None if face else "standard_fit",
    }
