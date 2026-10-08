import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from clipfactory.domain.models import Asset, AssetOrigin, ContentProfile, Provenance
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.workflow.saved_news_render import SavedNewsRenderer, SavedNewsRenderRequest


class Font:
    def getlength(self, text):
        return len(text) * 20.0

    def getmetrics(self):
        return (48, 12)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-361")
@pytest.mark.req("CF-REQ-417")
@pytest.mark.asyncio
async def test_saved_render_reuses_retained_inputs_and_persists_pending_output(tmp_path):
    storage = LocalStorageProvider(tmp_path)
    await storage.put_bytes("assets/photo.jpg", b"fake image")
    await storage.put_bytes("cache/tts/voice.wav", b"retained narration")
    logo = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse((5, 5, 195, 195), fill=(0, 180, 255, 255))
    logo_path = tmp_path / "brand.png"
    logo.save(logo_path, format="PNG")
    await storage.put_file(logo_path, "assets/brand.png")
    asset = Asset(
        media_type="image",
        category="photo",
        storage_key="assets/photo.jpg",
        sha256="a" * 64,
        mime_type="image/jpeg",
        size_bytes=10,
        width=720,
        height=1280,
        description="Location context",
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="fake", license="CC0"),
    )
    logo_asset = Asset(
        media_type="image",
        category="graphic",
        storage_key="assets/brand.png",
        sha256="c" * 64,
        mime_type="image/png",
        size_bytes=100,
        width=400,
        height=200,
        description="Owner-provided brand mark",
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="manual_import", license="owner-provided"),
    )
    profile = ContentProfile().model_dump(mode="json")
    stored = []

    class Repository:
        def context(self, clip_id):
            return {
                "profile": profile,
                "settings": {},
                "package": {"claims": [], "source_attributions": ["Fixture Source"]},
                "sources": [],
                "clip": {
                    "metadata": {
                        "narration": {"narration_key": "cache/tts/voice.wav", "duration_seconds": 70},
                        "word_timings": [
                            {
                                "text": "word",
                                "start_seconds": index,
                                "end_seconds": index + 0.5,
                                "script_segment_index": 0,
                            }
                            for index in range(70)
                        ],
                        "visual_segments": [
                            {
                                "selected_asset_id": str(asset.id),
                                "start_seconds": 0,
                                "end_seconds": 71.3,
                                "motion": "ken_burns",
                                "transition_in": "cut",
                            }
                        ],
                    }
                },
            }

        def save_revision(self, revision_id, clip_id, value, now):
            stored.append(value)

    class Assets:
        def get(self, asset_id):
            return {asset.id: asset, logo_asset.id: logo_asset}.get(asset_id)

    class Media:
        command = None

        async def ffmpeg(self, arguments, **kwargs):
            self.command = arguments
            await asyncio.to_thread(Path(arguments[-1]).write_bytes, b"rendered fixture")
            return (b"", b"")

        async def probe(self, media_path):
            return {"format": {"duration": "71.3"}, "streams": []}

        async def decode(self, media_path):
            return None

    media = Media()
    renderer = SavedNewsRenderer(
        repository=Repository(),
        assets=Assets(),
        storage=storage,
        media=media,
        font_file=Path("fake.ttf"),
        clock=lambda: datetime(2026, 10, 6, tzinfo=UTC),
        font_loader=lambda _path, _size: Font(),
    )
    result = await renderer.execute(SavedNewsRenderRequest(base_clip_id=uuid4(), brand_mark_asset_id=logo_asset.id))
    assert media.command is not None
    command = media.command
    mark_input = next(
        Path(command[index + 1])
        for index, argument in enumerate(command[:-1])
        if argument == "-i" and Path(command[index + 1]).name == "brand-mark.png"
    )
    with Image.open(mark_input) as rendered_logo:
        assert rendered_logo.mode == "RGBA"
        assert rendered_logo.size == (112, 56)
        assert rendered_logo.getchannel("A").getextrema()[0] == 0
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "overlay=x=584:y=24:eof_action=pass:enable='between(t,0,71.3)'" in filter_graph
    assert result["status"] == "pending_review"
    assert (
        result["research_calls"]
        == result["openrouter_calls"]
        == result["tts_calls"]
        == result["transcription_calls"]
        == 0
    )
    assert await storage.read_bytes("cache/tts/voice.wav") == b"retained narration"
    assert result["request"]["brand_mark_asset_id"] == str(logo_asset.id)
    assert len([overlay for overlay in result["request"]["overlays"]]) == 0
    assert await storage.exists(result["storage_key"])
    assert len(stored) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-361")
@pytest.mark.parametrize(
    ("segment_indexes", "accepted"),
    [((0, 0), True), ((0, 1), False)],
)
@pytest.mark.asyncio
async def test_saved_render_allows_only_adjacent_same_segment_asset_continuations(tmp_path, segment_indexes, accepted):
    storage = LocalStorageProvider(tmp_path)
    await storage.put_bytes("assets/photo.jpg", b"fake image")
    await storage.put_bytes("cache/tts/voice.wav", b"retained narration")
    asset = Asset(
        media_type="image",
        category="photo",
        storage_key="assets/photo.jpg",
        sha256="a" * 64,
        mime_type="image/jpeg",
        size_bytes=10,
        width=720,
        height=1280,
        description="Location context",
        provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="fake", license="CC0"),
    )
    profile = ContentProfile().model_dump(mode="json")

    class Repository:
        def context(self, clip_id):
            return {
                "profile": profile,
                "settings": {},
                "package": {"claims": [], "source_attributions": []},
                "sources": [],
                "clip": {
                    "metadata": {
                        "narration": {"narration_key": "cache/tts/voice.wav", "duration_seconds": 70},
                        "word_timings": [
                            {
                                "text": "word",
                                "start_seconds": index,
                                "end_seconds": index + 0.5,
                                "script_segment_index": 0,
                            }
                            for index in range(70)
                        ],
                        "visual_segments": [
                            {
                                "selected_asset_id": str(asset.id),
                                "script_segment_index": segment_index,
                                "start_seconds": start,
                                "end_seconds": end,
                                "motion": "none",
                                "transition_in": "cut",
                            }
                            for segment_index, (start, end) in zip(
                                segment_indexes, ((0, 35.65), (35.65, 71.3)), strict=True
                            )
                        ],
                    }
                },
            }

        def save_revision(self, revision_id, clip_id, value, now):
            return None

    class Assets:
        def get(self, asset_id):
            return asset if asset_id == asset.id else None

    class Media:
        async def ffmpeg(self, arguments, **kwargs):
            await asyncio.to_thread(Path(arguments[-1]).write_bytes, b"rendered fixture")
            return (b"", b"")

        async def probe(self, media_path):
            return {"format": {"duration": "71.3"}, "streams": []}

        async def decode(self, media_path):
            return None

    renderer = SavedNewsRenderer(
        repository=Repository(),
        assets=Assets(),
        storage=storage,
        media=Media(),
        font_file=Path("fake.ttf"),
        clock=lambda: datetime(2026, 10, 6, tzinfo=UTC),
        font_loader=lambda _path, _size: Font(),
    )
    request = SavedNewsRenderRequest(base_clip_id=uuid4())
    if accepted:
        assert (await renderer.execute(request))["status"] == "pending_review"
    else:
        with pytest.raises(ValueError, match="repeats an Asset"):
            await renderer.execute(request)
