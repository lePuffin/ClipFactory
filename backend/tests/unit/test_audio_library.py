from datetime import UTC, datetime
from typing import Any

import pytest
from test_asset_acquisition import Assets

from clipfactory.assets.audio_library import AudioLibraryEntry, import_audio_entry
from clipfactory.infrastructure.storage import LocalStorageProvider


class Media:
    calls = 0

    async def probe(self, path):
        return {"streams": [{"codec_type": "audio"}], "format": {"duration": "1.5"}}

    async def decode(self, path):
        self.calls += 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-323")
@pytest.mark.asyncio
async def test_sfx_manifest_is_decoded_before_activation_and_deduplicated(tmp_path):
    (tmp_path / "cue.wav").write_bytes(b"fake fixture")
    entry = AudioLibraryEntry(
        file="cue.wav", category="sfx", title="Soft cue", artist="Owner", source="fixture", license="CC0"
    )
    media, assets = Media(), Assets()
    args: dict[str, Any] = dict(
        base_directory=tmp_path,
        assets=assets,
        storage=LocalStorageProvider(tmp_path / "data"),
        media=media,
        now=datetime(2026, 10, 6, tzinfo=UTC),
    )
    first = await import_audio_entry(entry, **args)
    second = await import_audio_entry(entry, **args)
    assert first.id == second.id
    assert len(assets.items) == 1
    assert media.calls == 2
    assert first.category == "sfx"
    assert first.duration_seconds == 1.5


@pytest.mark.unit
@pytest.mark.req("CF-REQ-323")
@pytest.mark.asyncio
async def test_audio_library_rejects_escaping_path(tmp_path):
    entry = AudioLibraryEntry(
        file="../cue.wav", category="sfx", title="Cue", artist="Owner", source="fixture", license="CC0"
    )
    with pytest.raises(ValueError, match="escapes"):
        await import_audio_entry(
            entry,
            base_directory=tmp_path,
            assets=Assets(),
            storage=LocalStorageProvider(tmp_path / "data"),
            media=Media(),
            now=datetime(2026, 10, 6, tzinfo=UTC),
        )
