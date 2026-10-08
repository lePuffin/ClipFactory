import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from clipfactory.assets.generation import generate_video_asset
from clipfactory.domain.models import Asset, AssetOrigin, ContentProfile, Provenance, Stage
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, GeneratedMedia, GenerationProgress, VideoGenerationRequest
from clipfactory.workflow.production_stages import ProductionStageService

NOW = datetime(2026, 10, 7, tzinfo=UTC)


class FakeVideoProvider:
    name = "wan_local"

    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure
        self.calls: list[VideoGenerationRequest] = []

    def is_configured(self) -> bool:
        return True

    def estimate_cost(self, request: VideoGenerationRequest) -> Decimal:
        return Decimal("0")

    async def generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia:
        self.calls.append(request)
        if self.failure:
            raise ProviderError("generation_failed", "Insufficient VRAM", transient=False)
        if progress is not None:
            await progress("Wan generation worker is active", {"generation_phase": "heartbeat"})
            await progress("Wan: inference", {"generation_phase": "inference", "step": 1, "total_steps": 25})
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, b"\x00\x00\x00\x18ftypmp42" + str(request.seed).encode())
        return GeneratedMedia(destination, "fake-wan", "Apache-2.0", {"fps": 16})


def fake_assets() -> MagicMock:
    assets = MagicMock()
    assets.list.return_value = []
    assets.by_hash.return_value = None
    assets.save.side_effect = lambda asset: asset
    return assets


def fake_inspector() -> MagicMock:
    media = MagicMock()
    media.probe = AsyncMock(
        return_value={
            "streams": [{"codec_type": "video", "width": 720, "height": 1280}],
            "format": {"duration": "5"},
        }
    )
    media.decode = AsyncMock()
    return media


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.req("CF-REQ-210")
@pytest.mark.req("CF-REQ-215")
@pytest.mark.req("CF-REQ-656")
@pytest.mark.req("CF-REQ-604")
@pytest.mark.parametrize("media_type", ["image", "video"])
@pytest.mark.parametrize("candidate_state", ["empty", "rejected", "accepted"])
@pytest.mark.parametrize("strategy", ["generate_allowed", "reuse_first"])
async def test_missing_media_falls_back_to_generated_video_with_provenance(
    tmp_path: Path, media_type: str, candidate_state: str, strategy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, package_id = uuid4(), uuid4()
    plan: dict[str, Any] = {
        "version": 1,
        "segments": [
            {
                "index": 0,
                "narration_text": "The grid needs repair",
                "objective": "Show energy infrastructure",
                "planned_duration_seconds": 5,
                "requirement": {
                    "media_type": media_type,
                    "category": "photo",
                    "description": "Electricity substation",
                    "subjects": [],
                    "tags": ["electricity"],
                    "strategy": strategy,
                },
            }
        ],
    }
    production, runs, evaluations = MagicMock(), MagicMock(), MagicMock()
    production.current_visual_plan.return_value = plan
    runs.get.return_value = {
        "attempt": 1,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {},
    }
    provider, assets = FakeVideoProvider(), fake_assets()
    watchdog = MagicMock()
    monkeypatch.setattr("clipfactory.workflow.production_stages.renew_generation_watchdog", watchdog)
    existing: Asset | None = None
    if candidate_state != "empty":
        existing = Asset(
            media_type=media_type,
            category="photo",
            storage_key="assets/existing.mp4",
            sha256="a" * 64,
            mime_type="video/mp4" if media_type == "video" else "image/png",
            size_bytes=100,
            width=720,
            height=1280,
            description="Electricity substation",
            tags=["electricity"],
            provenance=Provenance(origin=AssetOrigin.IMPORTED, provider="fixture", license="CC0"),
        )
        assets.list.return_value = [existing]
        runs.get.return_value["settings_snapshot"] = {"assets": {"reuse_min_match_score": 0}}

        async def review(*args: Any, **kwargs: Any) -> dict[int, list[Any]]:
            return {0: list(args[1][0].candidates) if candidate_state == "accepted" else []}

        monkeypatch.setattr("clipfactory.workflow.production_stages.review_media_candidates", review)
    storage = LocalStorageProvider(tmp_path)
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=evaluations,
        storage=storage,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=fake_inspector(),
        clock=lambda: NOW,
        video_providers=[provider],
    )
    result = await service.select_assets(
        {"run_id": str(run_id), "story_package_id": str(package_id), "attempt": 1, "trigger": "run_now"}
    )
    assert result["last_evaluation_ids"] == [str(evaluations.save.call_args.args[0].id)]
    assert evaluations.save.call_args.args[0].passed
    selecting = [
        call for call in runs.append_event.call_args_list if call.args[2] == "Selecting Asset for Visual 1 of 1"
    ]
    assert len(selecting) == 1
    assert selecting[0].kwargs["payload"] == {"segment_index": 0, "segment_count": 1}
    if candidate_state == "accepted":
        assert existing is not None
        assert provider.calls == []
        assets.save.assert_not_called()
        assert plan["segments"][0]["selected_asset_id"] == str(existing.id)
        assert plan["segments"][0]["generated"] is False
        return
    assert len(provider.calls) == 1
    selected = assets.save.call_args.args[0]
    assert selected.media_type == "video"
    assert selected.provenance.origin == AssetOrigin.GENERATED
    assert selected.provenance.generation["model"] == "fake-wan"
    assert selected.provenance.generation["seed"] == provider.calls[0].seed
    assert selected.provenance.generation["prompt"] == provider.calls[0].prompt
    assert selected.provenance.generation["parameters"] == {"fps": 16}
    assert "generated" in selected.tags
    assert plan["segments"][0]["selected_asset_id"] == str(selected.id)
    assert plan["segments"][0]["selection_reason"] == "generated"
    assert plan["segments"][0]["requirement"]["media_type"] == "video"
    assert plan["segments"][0]["generated"] is True
    assert await storage.exists(selected.storage_key)
    assert not list((tmp_path / "generated-media/pending").glob("*"))
    assert evaluations.save.call_args.args[0].issues == []
    persisted_phases = [call.kwargs["payload"].get("generation_phase") for call in runs.append_event.call_args_list]
    assert "heartbeat" not in persisted_phases
    assert "inference" in persisted_phases
    assert watchdog.call_count > len([phase for phase in persisted_phases if phase is not None])


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.req("CF-REQ-215")
@pytest.mark.parametrize("restriction", ["disabled", "strategy", "person", "profile_order", "provider_failure"])
@pytest.mark.parametrize("strategy", ["generate_allowed", "reuse_first"])
async def test_generation_respects_permissions_and_failure_remains_blocking(
    tmp_path: Path, restriction: str, strategy: str
) -> None:
    profile = ContentProfile.model_validate(
        {
            "visual_style": {"allow_generated_media": restriction != "disabled"},
            **({"generation": {"video_providers": []}} if restriction == "profile_order" else {}),
        }
    )
    run_id, package_id = uuid4(), uuid4()
    plan = {
        "version": 1,
        "segments": [
            {
                "index": 0,
                "narration_text": "Grid",
                "objective": "Energy",
                "planned_duration_seconds": 5,
                "requirement": {
                    "media_type": "image",
                    "category": "photo",
                    "description": "Energy",
                    "subjects": ["Ada Lovelace"] if restriction == "person" else [],
                    "tags": [],
                    "strategy": "acquire_only" if restriction == "strategy" else strategy,
                },
            }
        ],
    }
    production, runs, evaluations = MagicMock(), MagicMock(), MagicMock()
    production.current_visual_plan.return_value = plan
    runs.get.return_value = {"attempt": 1, "profile_snapshot": profile.model_dump(mode="json"), "settings_snapshot": {}}
    provider = FakeVideoProvider(failure=restriction == "provider_failure")
    assets = fake_assets()
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=evaluations,
        storage=LocalStorageProvider(tmp_path),
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=fake_inspector(),
        clock=lambda: NOW,
        video_providers=[provider],
    )
    await service.select_assets(
        {"run_id": str(run_id), "story_package_id": str(package_id), "attempt": 1, "trigger": "run_now"}
    )
    assert len(provider.calls) == (1 if restriction == "provider_failure" else 0)
    assets.save.assert_not_called()
    assert evaluations.save.call_args.args[0].issues[0].code == "missing_asset"
    if restriction == "provider_failure":
        assert any(
            call.kwargs.get("payload", {}).get("error_code") == "generation_failed"
            for call in runs.append_event.call_args_list
        )


@pytest.mark.unit
@pytest.mark.req("CF-REQ-210")
async def test_generated_video_below_resolution_is_not_imported(tmp_path: Path) -> None:
    media = fake_inspector()
    media.probe.return_value["streams"][0]["height"] = 480
    assets, progress = fake_assets(), AsyncMock()
    result = await generate_video_asset(
        VideoGenerationRequest("Grid", "", 720, 1280, 5, 1),
        providers=[FakeVideoProvider()],
        storage=LocalStorageProvider(tmp_path),
        assets=assets,
        media=media,
        now=NOW,
        progress=progress,
        max_video_bytes=300000000,
        min_video_height_px=720,
    )
    assert result is None
    assets.save.assert_not_called()
    assert progress.call_args.args[1]["error_code"] == "resolution_too_low"
    retained = list((tmp_path / "generated-media/pending").glob("*.mp4"))
    assert len(retained) == 1
    metadata = await asyncio.to_thread(Path(str(retained[0]) + ".json").read_text)
    assert json.loads(metadata)["model"] == "fake-wan"
    assert progress.call_args.args[1]["recovery_storage_key"] == str(retained[0].relative_to(tmp_path))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.parametrize("cancel_phase", ["generation", "import"])
async def test_cancelled_run_still_imports_generated_media(tmp_path: Path, cancel_phase: str) -> None:
    started, release = asyncio.Event(), asyncio.Event()

    class BlockingProvider(FakeVideoProvider):
        async def generate(
            self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
        ) -> GeneratedMedia:
            if cancel_phase == "generation":
                started.set()
                await release.wait()
            return await super().generate(request, destination, progress=progress)

    media = fake_inspector()
    if cancel_phase == "import":

        async def decode(path: Path) -> None:
            started.set()
            await release.wait()

        media.decode.side_effect = decode
    assets, storage = fake_assets(), LocalStorageProvider(tmp_path)
    task = asyncio.create_task(
        generate_video_asset(
            VideoGenerationRequest("Grid", "", 720, 1280, 5, 1),
            providers=[BlockingProvider()],
            storage=storage,
            assets=assets,
            media=media,
            now=NOW,
            progress=AsyncMock(),
            max_video_bytes=300000000,
            min_video_height_px=720,
        )
    )
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assets.save.assert_called_once()
    saved = assets.save.call_args.args[0]
    assert saved.reusable
    assert saved.provenance.origin == AssetOrigin.GENERATED
    assert await storage.exists(saved.storage_key)
    assert not list((tmp_path / "generated-media/pending").glob("*"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
async def test_library_save_failure_keeps_output_and_metadata(tmp_path: Path) -> None:
    assets = fake_assets()
    assets.save.side_effect = OSError("Database unavailable")
    with pytest.raises(OSError, match="Database unavailable"):
        await generate_video_asset(
            VideoGenerationRequest("Grid", "", 720, 1280, 5, 1),
            providers=[FakeVideoProvider()],
            storage=LocalStorageProvider(tmp_path),
            assets=assets,
            media=fake_inspector(),
            now=NOW,
            progress=AsyncMock(),
            max_video_bytes=300000000,
            min_video_height_px=720,
        )
    files = list((tmp_path / "generated-media/pending").glob("*.mp4"))
    assert len(files) == 1
    metadata = await asyncio.to_thread(Path(str(files[0]) + ".json").read_text)
    assert json.loads(metadata)["license"] == "Apache-2.0"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
async def test_explicit_owner_stop_does_not_wait_for_generation_completion(tmp_path: Path) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingProvider(FakeVideoProvider):
        async def generate(self, request, destination, *, progress=None):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("Blocking generation should only exit by cancellation")

    abort = Event()
    token = GENERATION_ABORT.set(abort)
    assets = fake_assets()
    try:
        task = asyncio.create_task(
            generate_video_asset(
                VideoGenerationRequest("Grid", "", 720, 1280, 5, 1),
                providers=[BlockingProvider()],
                storage=LocalStorageProvider(tmp_path),
                assets=assets,
                media=fake_inspector(),
                now=NOW,
                progress=AsyncMock(),
                max_video_bytes=300000000,
                min_video_height_px=720,
            )
        )
        await entered.wait()
        abort.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assets.save.assert_not_called()
    finally:
        GENERATION_ABORT.reset(token)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-162")
@pytest.mark.req("CF-REQ-208")
@pytest.mark.parametrize("generated", [False, True])
async def test_composition_derives_synthetic_disclosure_from_used_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generated: bool
) -> None:
    run_id, package_id = uuid4(), uuid4()
    asset = Asset(
        media_type="video",
        category="broll",
        storage_key="assets/video.mp4",
        sha256="b" * 64,
        description="Illustrative power grid",
        mime_type="video/mp4",
        size_bytes=100,
        width=720,
        height=1280,
        provenance=Provenance(
            origin=AssetOrigin.GENERATED if generated else AssetOrigin.IMPORTED,
            provider="fixture",
            license="Apache-2.0",
            generation={"model": "fake"} if generated else None,
        ),
    )
    production, runs, assets = MagicMock(), MagicMock(), fake_assets()
    production.current_visual_plan.return_value = {
        "version": 1,
        "segments": [
            {
                "index": 0,
                "selected_asset_id": str(asset.id),
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "motion": "none",
                "transition_in": "cut",
            }
        ],
    }
    production.current_script.return_value = {
        "social_metadata": {
            "title": "Grid",
            "description": "Briefing",
            "hashtags": ["#a", "#b", "#c"],
            "contains_synthetic_media": not generated,
        },
    }
    artifacts = {
        Stage.GENERATE_NARRATION.value: {"narration_key": "audio/narration.wav", "duration_seconds": 5.0},
        Stage.TRANSCRIBE_NARRATION.value: {"words": [], "wer": 0},
        Stage.BUILD_CAPTIONS.value: {"caption_key": "captions/test.ass"},
        Stage.SELECT_ASSETS.value: {},
    }
    production.artifact.side_effect = lambda run, attempt, stage: artifacts[stage]
    assets.get.return_value = asset
    runs.get.return_value = {
        "attempt": 1,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {},
    }
    storage = MagicMock()
    storage.exists = AsyncMock(return_value=True)
    storage.work_dir.return_value = tmp_path
    storage.local_path.side_effect = lambda key: tmp_path / key
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=MagicMock(),
        storage=storage,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        media=fake_inspector(),
        clock=lambda: NOW,
    )
    monkeypatch.setattr(service, "_editorial_overlays", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(service, "_sound_cues", AsyncMock(return_value=()))
    monkeypatch.setattr(
        "clipfactory.workflow.production_stages.reconcile_visual_timing", lambda segments, words, **kwargs: segments
    )
    monkeypatch.setattr("clipfactory.workflow.production_stages.render_clip", AsyncMock())
    await service.compose_clip(
        {"run_id": str(run_id), "story_package_id": str(package_id), "attempt": 1, "trigger": "run_now"}
    )
    metadata = production.save_clip.call_args.kwargs["metadata"]["social_metadata"]
    assert metadata["contains_synthetic_media"] is generated
    assert metadata["synthetic_voice"] is True
