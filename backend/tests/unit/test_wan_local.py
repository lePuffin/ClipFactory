import asyncio
import importlib
import importlib.util
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.infrastructure.providers.wan_local import WanLocalVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, VideoGenerationRequest


def settings(tmp_path: Path, **overrides: object) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "_env_file": None,
        "DATABASE_URL": "sqlite://",
        "DATA_DIR": tmp_path,
        "WAN_FPS": 4,
        "WAN_INFERENCE_STEPS": 2,
        **overrides,
    }
    return EnvironmentSettings(**values)


def mock_runtime(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    torch = MagicMock()
    torch.cuda.is_available.return_value = True
    original_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name: torch if name == "torch" else original_import(name))
    return torch


def fake_pipeline() -> MagicMock:
    pipeline = MagicMock()

    def inference(**kwargs: object) -> SimpleNamespace:
        callback = kwargs.get("callback_on_step_end")
        if callable(callback):
            for step in range(int(str(kwargs["num_inference_steps"]))):
                callback(pipeline, step, None, {})
        return SimpleNamespace(
            frames=[
                [
                    Image.new("RGB", (int(str(kwargs["width"])), int(str(kwargs["height"]))), (20, 40, index))
                    for index in range(int(str(kwargs["num_frames"])))
                ]
            ]
        )

    pipeline.side_effect = inference
    return pipeline


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
async def test_wan_lazily_downloads_to_data_cache_and_reuses_loaded_pipeline(tmp_path, monkeypatch) -> None:
    torch = mock_runtime(monkeypatch)
    pipeline = fake_pipeline()
    factory = MagicMock(return_value=pipeline)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    provider = WanLocalVideoProvider(settings(tmp_path), media, pipeline_factory=factory)
    request = VideoGenerationRequest("Illustrative power grid", "people, text", 65, 79, 1, 42)
    assert factory.call_count == 0
    assert provider.estimate_cost(request) == 0

    first = await provider.generate(request, tmp_path / "work/first.mp4")
    await provider.generate(request, tmp_path / "work/second.mp4")

    factory.assert_called_once_with(
        "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        cache_dir=str(tmp_path / "models/wan"),
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    pipeline.enable_sequential_cpu_offload.assert_called_once()
    pipeline.vae.enable_tiling.assert_called_once()
    assert pipeline.call_count == 2
    assert first.parameters == {"width": 80, "height": 80, "num_frames": 5, "fps": 4, "num_inference_steps": 2}
    assert first.license == "Apache-2.0"
    assert torch.Generator.call_args.kwargs == {"device": "cpu"}
    assert media.ffmpeg.await_count == 2
    assert not list((tmp_path / "work").glob("wan-frames-*"))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
async def test_wan_downloads_only_after_local_cache_miss_and_new_instance_uses_cache(tmp_path, monkeypatch) -> None:
    mock_runtime(monkeypatch)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    pipeline = fake_pipeline()
    factory = MagicMock(side_effect=[FileNotFoundError("Missing weights"), pipeline])
    progress = AsyncMock()
    request = VideoGenerationRequest("Grid", "", 64, 80, 1, 1)
    provider = WanLocalVideoProvider(settings(tmp_path), media, pipeline_factory=factory)
    await provider.generate(request, tmp_path / "first.mp4", progress=progress)
    assert [call.kwargs["local_files_only"] for call in factory.call_args_list] == [True, False]
    assert any(call.args[1]["generation_phase"] == "downloading_model" for call in progress.await_args_list)
    cached_factory = MagicMock(return_value=pipeline)
    restarted = WanLocalVideoProvider(settings(tmp_path), media, pipeline_factory=cached_factory)
    await restarted.generate(request, tmp_path / "second.mp4")
    assert cached_factory.call_args.kwargs["local_files_only"] is True
    assert cached_factory.call_args.kwargs["cache_dir"] == factory.call_args.kwargs["cache_dir"]


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.parametrize("error", [OSError("Corrupt model"), PermissionError("Cannot read cache")])
async def test_wan_does_not_download_again_for_non_missing_cache_errors(tmp_path, monkeypatch, error) -> None:
    mock_runtime(monkeypatch)
    factory = MagicMock(side_effect=error)
    provider = WanLocalVideoProvider(settings(tmp_path), MagicMock(), pipeline_factory=factory)
    with pytest.raises(ProviderError, match="loading/download failed"):
        await provider.generate(VideoGenerationRequest("Grid", "", 64, 80, 1, 1), tmp_path / "output.mp4")
    factory.assert_called_once()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-759")
async def test_wan_updated_runtime_steps_and_fps_reach_loaded_pipeline(tmp_path, monkeypatch) -> None:
    from clipfactory.infrastructure.settings_validation import apply_runtime_environment

    mock_runtime(monkeypatch)
    baseline = settings(tmp_path)
    runtime = baseline.model_copy()
    pipeline = fake_pipeline()
    factory = MagicMock(return_value=pipeline)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    provider = WanLocalVideoProvider(runtime, media, pipeline_factory=factory)
    request = VideoGenerationRequest("Grid", "", 64, 80, 1, 1)
    await provider.generate(request, tmp_path / "first.mp4")
    apply_runtime_environment(runtime, baseline, {"wan_inference_steps": 25, "wan_fps": 8})
    result = await provider.generate(request, tmp_path / "second.mp4")
    assert pipeline.call_args.kwargs["num_inference_steps"] == 25
    assert result.parameters["fps"] == 8
    assert media.ffmpeg.call_args.args[0][2] == "8"
    factory.assert_called_once()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.req("CF-REQ-604")
async def test_wan_reports_real_inference_steps_and_phases(tmp_path, monkeypatch) -> None:
    mock_runtime(monkeypatch)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    provider = WanLocalVideoProvider(
        settings(tmp_path), media, pipeline_factory=MagicMock(return_value=fake_pipeline())
    )
    progress = AsyncMock()
    await provider.generate(
        VideoGenerationRequest("Grid", "", 64, 80, 1, 1), tmp_path / "output.mp4", progress=progress
    )
    payloads = [call.args[1] for call in progress.await_args_list]
    assert [item["generation_phase"] for item in payloads] == [
        "waiting",
        "loading_model",
        "cached_model_loaded",
        "inference",
        "inference",
        "inference",
        "saving_frames",
        "encoding",
    ]
    assert [item["step"] for item in payloads if "step" in item] == [0, 1, 2]
    assert all(item["model"] == settings(tmp_path).wan_model and item["provider"] == "wan_local" for item in payloads)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-656")
async def test_wan_heartbeats_continue_while_loading_and_stop_when_finished(tmp_path, monkeypatch) -> None:
    provider = WanLocalVideoProvider(settings(tmp_path), MagicMock())
    sleep = asyncio.sleep

    async def fast_heartbeat(seconds: float) -> None:
        await sleep(0.005 if seconds == 10 else seconds)

    async def generation(*args, **kwargs):
        await sleep(0.025)
        return "finished"

    monkeypatch.setattr(asyncio, "sleep", fast_heartbeat)
    monkeypatch.setattr(provider, "_generate", generation)
    progress = AsyncMock()
    result = await provider.generate(
        VideoGenerationRequest("Grid", "", 64, 80, 1, 1), tmp_path / "out.mp4", progress=progress
    )
    assert result == "finished"
    assert progress.await_count > 0
    assert all(call.args[1]["generation_phase"] == "heartbeat" for call in progress.await_args_list)
    count = progress.await_count
    await sleep(0.02)
    assert progress.await_count == count


@pytest.mark.unit
@pytest.mark.req("CF-REQ-657")
async def test_owner_abort_interrupts_wan_at_next_step_and_does_not_encode(tmp_path, monkeypatch) -> None:
    mock_runtime(monkeypatch)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    provider = WanLocalVideoProvider(
        settings(tmp_path), media, pipeline_factory=MagicMock(return_value=fake_pipeline())
    )
    abort = Event()
    token = GENERATION_ABORT.set(abort)

    async def progress(message, payload):
        if payload.get("step") == 1:
            abort.set()

    try:
        with pytest.raises(ProviderError, match="stopped by owner") as error:
            await provider.generate(
                VideoGenerationRequest("Grid", "", 64, 80, 1, 1), tmp_path / "out.mp4", progress=progress
            )
        assert error.value.code == "generation_stopped"
        media.ffmpeg.assert_not_called()
    finally:
        GENERATION_ABORT.reset(token)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-208")
@pytest.mark.parametrize("failure", ["download", "inference", "cuda", "dependencies"])
async def test_wan_errors_are_actionable_and_no_placeholder_is_returned(tmp_path, monkeypatch, failure) -> None:
    torch = mock_runtime(monkeypatch)
    factory = MagicMock(return_value=fake_pipeline())
    if failure == "download":
        factory.side_effect = OSError("Offline")
    elif failure == "inference":
        factory.return_value.side_effect = RuntimeError("Out of memory")
    elif failure == "cuda":
        torch.cuda.is_available.return_value = False
    else:
        monkeypatch.setattr(importlib.util, "find_spec", lambda _: None)
    media = MagicMock()
    media.ffmpeg = AsyncMock()
    provider = WanLocalVideoProvider(
        settings(tmp_path), media, pipeline_factory=None if failure == "dependencies" else factory
    )
    with pytest.raises(ProviderError) as error:
        await provider.generate(VideoGenerationRequest("Grid", "", 64, 80, 1, 0), tmp_path / "work/output.mp4")
    assert (
        error.value.code
        == {
            "download": "generation_model_load_failed",
            "inference": "generation_failed",
            "cuda": "generation_device_unavailable",
            "dependencies": "generation_dependencies_missing",
        }[failure]
    )
    assert not error.value.transient
    media.ffmpeg.assert_not_called()
    assert not list(tmp_path.rglob("wan-frames-*"))


@pytest.mark.integration
@pytest.mark.req("CF-REQ-208")
@pytest.mark.req("CF-REQ-210")
async def test_wan_mock_inference_encodes_a_real_decodable_video(tmp_path, monkeypatch) -> None:
    mock_runtime(monkeypatch)
    media = MediaRunner()
    provider = WanLocalVideoProvider(
        settings(tmp_path, WAN_DEVICE="cpu"), media, pipeline_factory=MagicMock(return_value=fake_pipeline())
    )
    output = await provider.generate(VideoGenerationRequest("Grid", "", 64, 80, 1, 1), tmp_path / "output.mp4")
    probe = await media.probe(output.path)
    await media.decode(output.path)
    stream = next(item for item in probe["streams"] if item["codec_type"] == "video")
    assert (stream["width"], stream["height"], stream["nb_frames"]) == (64, 80, "5")
    assert float(probe["format"]["duration"]) == 1.25
