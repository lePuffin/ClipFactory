"""Signed URL tokens for temporary public delivery of a Clip during publishing."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID


def create_media_token(clip_id: UUID, *, now: datetime, ttl_minutes: int, key: bytes) -> str:
    if len(key) < 32:
        raise ValueError("media URL signing key must contain at least 32 bytes")
    if not 5 <= ttl_minutes <= 1440:
        raise ValueError("media URL TTL must be between 5 and 1440 minutes")
    issued_at = now.astimezone(UTC)
    expires_at = int((issued_at + timedelta(minutes=ttl_minutes)).timestamp())
    payload = f"{clip_id}.{expires_at}"
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def create_public_media_url(base_url: str, clip_id: UUID, *, now: datetime, ttl_minutes: int, key: bytes) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("public media base URL must be an HTTPS origin or path without query or fragment")
    token = create_media_token(clip_id, now=now, ttl_minutes=ttl_minutes, key=key)
    path = f"{parsed.path.rstrip('/')}/public/media/{token}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def verify_media_token(token: str, *, now: datetime, key: bytes) -> UUID | None:
    if len(key) < 32:
        return None
    parts = token.split(".")
    if len(parts) != 3 or len(parts[2]) != 64:
        return None
    raw_clip_id, raw_expiry, supplied_signature = parts
    payload = f"{raw_clip_id}.{raw_expiry}"
    expected_signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    try:
        clip_id = UUID(raw_clip_id)
        expires_at = int(raw_expiry)
    except ValueError:
        return None
    if now.astimezone(UTC).timestamp() >= expires_at:
        return None
    return clip_id
