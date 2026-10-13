from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from clipfactory.composition.spec import CompositionSpec, VisualInput
from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.settings_validation import CompositionSettings
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.production.editorial import render_brand_mark
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.production_stages import ProductionStageService

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


class Production:
    def __init__(self, claims: list[Any]) -> None:
        self.claims = claims

    def package_context(self, package_id: Any) -> dict[str, Any]:
        return {"claims": self.claims}


class Runs:
    def __init__(self) -> None:
        self.events: list[str] = []

    def append_event(self, run_id: Any, event_type: str, message: str, **kwargs: Any) -> dict[str, Any]:
        self.events.append(message)
        return {}


def _overlay_service(tmp_path: Path, claims: list[Any], runs: Runs) -> ProductionStageService:
    return ProductionStageService(
        production=Production(claims),
        runs=runs,
        assets=None,
        evaluations=None,
        storage=LocalStorageProvider(tmp_path),
        llm=None,
        tts=None,
        transcription=None,
        media=None,
        clock=lambda: datetime.now(UTC),
    )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-259")
@pytest.mark.req("CF-REQ-269")
@pytest.mark.skipif(not FONT.is_file(), reason="system DejaVu font is required to measure labels")
@pytest.mark.asyncio
async def test_top_panel_shows_a_continuous_context_summary_never_a_source(tmp_path: Path) -> None:
    claim_id, source_id = uuid4(), uuid4()
    claim = SimpleNamespace(id=claim_id, evidence=[SimpleNamespace(source_id=source_id, verified=True)])
    runs = Runs()
    service = _overlay_service(tmp_path, [claim], runs)
    segments = [
        {"script_segment_index": 0, "start_seconds": 1.5, "end_seconds": 6.0},
        {"script_segment_index": 1, "start_seconds": 6.0, "end_seconds": 12.0},
        {"script_segment_index": 2, "start_seconds": 12.0, "end_seconds": 20.0},
        {"script_segment_index": 3, "start_seconds": 20.0, "end_seconds": 30.0},
    ]
    claims = [str(claim_id)]
    script = {
        "editorial_overlays": [
            {"segment_index": 0, "kind": "source", "text": "Reuters", "claim_ids": [], "source_ids": [str(source_id)]},
            {"segment_index": 0, "kind": "place", "text": "Moscow", "secondary": "", "claim_ids": claims},
            {"segment_index": 2, "kind": "person", "text": "Vladimir Putin", "claim_ids": claims},
            {"segment_index": 3, "kind": "number", "text": "12 drones", "claim_ids": claims},
        ],
        "buzz_lines": [
            {"segment_index": 0, "text": "Ignored when a cue exists", "claim_ids": claims},
            {"segment_index": 2, "text": "Kyiv answers Moscow's warning!", "claim_ids": claims},
        ],
    }

    overlays, recorded = await service._editorial_overlays(
        uuid4(), 1, uuid4(), script, segments, FONT, ContentProfile(), 27.0
    )

    assert [item["text"] for item in recorded] == ["Moscow", "Kyiv answers Moscow's warning!", "12 drones"]
    assert all(item["kind"] != "source" for item in recorded)
    assert [(item.start_seconds, item.end_seconds) for item in overlays] == [(0.0, 12.0), (12.0, 20.0), (20.0, 27.0)]
    assert all(item.path.is_file() for item in overlays)
    assert recorded[0]["source_ids"] == [str(source_id)]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-259")
@pytest.mark.skipif(not FONT.is_file(), reason="system DejaVu font is required to measure labels")
@pytest.mark.asyncio
async def test_unreadable_context_label_extends_the_previous_summary(tmp_path: Path) -> None:
    claim_id = uuid4()
    claim = SimpleNamespace(id=claim_id, evidence=[SimpleNamespace(source_id=uuid4(), verified=True)])
    runs = Runs()
    service = _overlay_service(tmp_path, [claim], runs)
    segments = [
        {"script_segment_index": 0, "start_seconds": 0.0, "end_seconds": 6.0},
        {"script_segment_index": 1, "start_seconds": 6.0, "end_seconds": 7.0},
    ]
    script = {
        "editorial_overlays": [
            {"segment_index": 0, "kind": "place", "text": "Moscow", "claim_ids": [str(claim_id)]},
            {
                "segment_index": 1,
                "kind": "number",
                "text": "Way too many words to read here",
                "claim_ids": [str(claim_id)],
            },
        ]
    }

    overlays, recorded = await service._editorial_overlays(
        uuid4(), 1, uuid4(), script, segments, FONT, ContentProfile(), 7.0
    )

    assert len(overlays) == 1
    assert (overlays[0].start_seconds, overlays[0].end_seconds) == (0.0, 7.0)
    assert recorded[0]["end_seconds"] == 7.0
    assert any("skipped" in message for message in runs.events)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
@pytest.mark.parametrize("has_date", [False, True])
async def test_persistent_logo_and_latest_cited_news_date(tmp_path: Path, has_date: bool) -> None:
    claim_id, source_id, newer_source_id, unverified_source_id = uuid4(), uuid4(), uuid4(), uuid4()
    claim = SimpleNamespace(
        id=claim_id,
        evidence=[
            SimpleNamespace(source_id=source_id, verified=True),
            SimpleNamespace(source_id=unverified_source_id, verified=False),
        ],
    )
    production = Production(
        [claim, SimpleNamespace(id=uuid4(), evidence=[SimpleNamespace(source_id=newer_source_id, verified=True)])]
    )
    date = datetime(2026, 10, 7, 23, 30, tzinfo=UTC)
    publications = {
        source_id: date if has_date else None,
        newer_source_id: datetime(2026, 10, 9, tzinfo=UTC),
        unverified_source_id: datetime(2026, 10, 10, tzinfo=UTC),
    }
    production.package_context = lambda package_id: {"claims": production.claims, "source_publications": publications}
    runs = Runs()
    storage = LocalStorageProvider(tmp_path / "data")
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=None,
        evaluations=None,
        storage=storage,
        llm=None,
        tts=None,
        transcription=None,
        media=None,
        clock=lambda: date,
    )
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 100), (0, 180, 220, 200)).save(logo)
    profile = ContentProfile()
    profile = profile.model_copy(update={"schedule": profile.schedule.model_copy(update={"timezone": "Europe/Lisbon"})})
    overlays, recorded = await service._identity_overlays(
        uuid4(),
        1,
        uuid4(),
        {"segments": [{"claim_ids": [str(claim_id)]}]},
        FONT,
        profile,
        70,
        {"logo_file": str(logo), "logo_opacity": 0.7},
    )
    assert len(overlays) == (3 if has_date else 2)
    brand = overlays[0]
    assert (brand.x, brand.y, brand.width, brand.height) == (584, 24, 112, 56)
    ai_tag = overlays[-1]
    assert recorded[-1]["kind"] == "ai_disclosure"
    assert recorded[-1]["text"] == "AI Generated"
    assert ai_tag.x == 24
    assert ai_tag.y > 1150
    for overlay in overlays:
        assert (overlay.start_seconds, overlay.end_seconds, overlay.fade_seconds) == (0, 70, 0)
        assert overlay.path.is_file()
    with Image.open(brand.path) as image:
        assert image.getchannel("A").getextrema() == (140, 140)
    if has_date:
        assert recorded[1]["text"] == "8 Oct 2026"
        assert recorded[1]["source_ids"] == [str(source_id)]
        assert recorded[1]["published_at"] == date.isoformat()
        assert overlays[1].y + overlays[1].height < 112
        assert overlays[1].x + overlays[1].width < brand.x
        assert not runs.events
    else:
        assert any("News date omitted" in message for message in runs.events)
    assert len(recorded[0]["sha256"]) == 64
    spec = CompositionSpec(
        segments=(VisualInput(logo, "image", 200, 100, 70),),
        narration_path=tmp_path / "narration.wav",
        caption_file=tmp_path / "captions.ass",
        output_path=tmp_path / "clip.mp4",
        narration_duration_seconds=68.7,
        overlays=tuple(overlays),
    )
    changed_logo = replace(brand, sha256="f" * 64)
    assert replace(spec, overlays=(changed_logo, *overlays[1:])).sha256() != spec.sha256()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_missing_logo_fails_composition_explicitly(tmp_path: Path) -> None:
    service = ProductionStageService(
        production=None,
        runs=None,
        assets=None,
        evaluations=None,
        storage=LocalStorageProvider(tmp_path),
        llm=None,
        tts=None,
        transcription=None,
        media=None,
        clock=lambda: datetime.now(UTC),
    )

    with pytest.raises(StageFailure, match="Configured logo is unavailable"):
        await service._identity_overlays(
            uuid4(),
            1,
            uuid4(),
            {"segments": []},
            FONT,
            ContentProfile(),
            70,
            {"logo_file": str(tmp_path / "missing.png")},
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
@pytest.mark.req("CF-REQ-752")
@pytest.mark.parametrize("opacity", [0, -0.1, 1.01, float("nan")])
def test_identity_settings_reject_invalid_opacity(opacity: float) -> None:
    with pytest.raises(ValidationError):
        CompositionSettings(logo_opacity=opacity)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_end_card_requires_reserved_tail() -> None:
    assert CompositionSettings().end_card_file is None
    with pytest.raises(ValidationError, match="tail_seconds"):
        CompositionSettings(end_card_file="branding/outro.mp4", tail_seconds=1)
    assert CompositionSettings(end_card_file="branding/outro.mp4", tail_seconds=3).tail_seconds == 3


@pytest.mark.unit
@pytest.mark.req("CF-REQ-360")
def test_owner_wordmark_crops_padding_and_preserves_white_letters() -> None:
    import io

    source = Path(__file__).resolve().parents[3] / "branding/inpulso_world/logo_letters.png"
    content, width, height = render_brand_mark(source, 112, 0.7)
    assert width == 112
    assert 25 <= height <= 30
    with Image.open(io.BytesIO(content)) as image:
        assert image.getchannel("A").getextrema() == (0, 178)
        visible_white = [
            pixel
            for pixel in image.getdata()
            if isinstance(pixel, tuple) and pixel[0:3] == (255, 255, 255) and pixel[3] > 100
        ]
        assert visible_white
