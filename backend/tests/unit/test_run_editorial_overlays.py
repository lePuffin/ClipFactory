from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from clipfactory.domain.models import ContentProfile
from clipfactory.infrastructure.storage import LocalStorageProvider
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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-259")
@pytest.mark.skipif(not FONT.is_file(), reason="system DejaVu font is required to measure labels")
@pytest.mark.asyncio
async def test_normal_run_renders_grounded_labels_at_segment_time_and_skips_unreadable(tmp_path: Path) -> None:
    claim_id, source_id = uuid4(), uuid4()
    claim = SimpleNamespace(id=claim_id, evidence=[SimpleNamespace(source_id=source_id, verified=True)])
    runs = Runs()
    service = ProductionStageService(
        production=Production([claim]),
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
    segments = [
        {"script_segment_index": 0, "start_seconds": 0.0, "end_seconds": 6.0},
        {"script_segment_index": 1, "start_seconds": 6.0, "end_seconds": 7.0},
    ]
    script = {
        "editorial_overlays": [
            {"segment_index": 0, "kind": "place", "text": "Moscow", "secondary": "", "claim_ids": [str(claim_id)]},
            {"segment_index": 1, "kind": "number", "text": "Too short to read", "claim_ids": [str(claim_id)]},
        ]
    }

    overlays, recorded = await service._editorial_overlays(
        uuid4(), 1, uuid4(), script, segments, FONT, ContentProfile(), 12.0
    )

    assert len(overlays) == 1
    assert overlays[0].start_seconds == pytest.approx(0.4)
    assert overlays[0].end_seconds == pytest.approx(5.4)
    assert overlays[0].path.is_file()
    assert recorded[0]["source_ids"] == [str(source_id)]
    assert any("skipped" in message for message in runs.events)
