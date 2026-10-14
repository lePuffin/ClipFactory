from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from clipfactory.publishing.media_urls import create_media_token, create_public_media_url, verify_media_token

KEY = b"k" * 32
NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
@pytest.mark.req("CF-NFR-114")
def test_signed_media_token_binds_one_clip_and_expiry() -> None:
    clip_id = uuid4()
    token = create_media_token(clip_id, now=NOW, ttl_minutes=60, key=KEY)

    assert verify_media_token(token, now=NOW + timedelta(minutes=59), key=KEY) == clip_id
    assert verify_media_token(token, now=NOW + timedelta(minutes=60), key=KEY) is None
    assert verify_media_token(token[:-1] + ("0" if token[-1] != "0" else "1"), now=NOW, key=KEY) is None


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
@pytest.mark.req("CF-NFR-114")
@pytest.mark.parametrize("ttl_minutes", [4, 1441])
def test_signed_media_token_rejects_expiry_outside_configured_bounds(ttl_minutes: int) -> None:
    with pytest.raises(ValueError, match="TTL"):
        create_media_token(uuid4(), now=NOW, ttl_minutes=ttl_minutes, key=KEY)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-461")
def test_public_media_url_uses_https_and_places_only_the_token_in_its_path() -> None:
    clip_id = uuid4()
    url = create_public_media_url(
        "https://media.example.test/proxy/",
        clip_id,
        now=NOW,
        ttl_minutes=60,
        key=KEY,
    )

    assert url.startswith("https://media.example.test/proxy/public/media/")
    assert "?" not in url
    assert verify_media_token(url.rsplit("/", 1)[-1], now=NOW, key=KEY) == clip_id

    with pytest.raises(ValueError, match="HTTPS"):
        create_public_media_url("http://media.example.test", clip_id, now=NOW, ttl_minutes=60, key=KEY)
