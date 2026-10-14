"""Stable profile-owned branding paths for new Run snapshots."""

import re
import unicodedata
from pathlib import Path
from typing import Any
from uuid import UUID


def allocate_branding_folder(root: Path, profile_id: UUID, name: str) -> str:
    legacy = root / str(profile_id)
    if legacy.is_symlink():
        target = legacy.resolve(strict=True)
        if target.parent != root.resolve() or not target.is_dir():
            raise ValueError("Legacy branding alias must point to a folder inside the branding root")
        return target.name
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:160].rstrip("-") or "profile"
    if (root / slug).exists() or (root / slug).is_symlink():
        slug = f"{slug}-{profile_id}"
    return slug


def profile_branding_directory(root: Path, profile_id: UUID, folder: str | None = None) -> Path:
    root = root.resolve()
    if folder is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,199}", folder):
        raise ValueError("Invalid profile branding folder")
    directory = root / (folder or str(profile_id))
    if directory.is_symlink() and folder is not None:
        raise ValueError("Named profile branding folder must not be a symbolic link")
    if directory.resolve().parent != root:
        raise ValueError("Profile branding directory must remain inside the branding root")
    legacy = root / str(profile_id)
    if folder is not None and legacy.is_symlink() and legacy.resolve() != directory.resolve():
        raise ValueError("Legacy branding alias does not match this profile's named folder")
    if folder is not None and legacy.exists() and not legacy.is_symlink():
        if directory.exists():
            raise ValueError("Both legacy and named profile branding folders exist; refusing to merge assets")
        legacy.rename(directory)
        legacy.symlink_to(folder, target_is_directory=True)
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def profile_branding_settings(
    root: Path, profile_id: UUID, settings: dict[str, Any], folder: str | None = None
) -> dict[str, Any]:
    directory = profile_branding_directory(root, profile_id, folder)
    for filename in ("logo_letters.png", "logo_badge.png", "outro.mp4", "outro.png", "outro-voice.wav"):
        if (directory / filename).resolve().parent != directory:
            raise ValueError(f"Profile branding input must remain inside its folder: {filename}")
    composition = dict(settings.get("composition", {}))
    composition.update(
        branding_directory=str(directory),
        logo_file=str(directory / "logo_letters.png"),
        end_card_file=str(directory / "outro.mp4"),
        tail_seconds=max(3.0, float(composition.get("tail_seconds", 1.0))),
    )
    return {**settings, "composition": composition}
