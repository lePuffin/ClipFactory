"""Offline tests for the isolated local Wan comparison command."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_cli_operations import FakePreflight, dependencies
from test_wan_local import settings

from clipfactory.cli import main
from clipfactory.infrastructure.wan_test import run_wan_test
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GeneratedMedia, VideoGenerationRequest

pytestmark = [pytest.mark.unit, pytest.mark.req("CF-REQ-267")]


def arguments(output: Path) -> list[str]:
    return [
        "wan-test",
        "--prompt",
        "A paper boat floating through a rain-filled city gutter at night.",
        "--output",
        str(output),
        "--steps",
        "25",
        "--fps",
        "16",
    ]


def test_dry_run_cli_uses_reference_recipe_without_operational_side_effects(tmp_path, monkeypatch, capsys) -> None:
    events: list[str] = []
    preflight = FakePreflight()
    deps = dependencies(tmp_path, preflight, events)
    forbidden = MagicMock(side_effect=AssertionError("dry-run tried to load or encode"))
    monkeypatch.setattr("clipfactory.infrastructure.wan_test.MediaRunner", forbidden)
    monkeypatch.setattr("clipfactory.infrastructure.wan_test.WanLocalVideoProvider.generate", forbidden)
    output = tmp_path / "paper-boat.mp4"

    assert main([*arguments(output), "--dry-run"], dependencies=deps) == 0
    recipe = json.loads(capsys.readouterr().out)
    assert recipe["provider"] == "wan_local"
    assert recipe["seed"] == 42
    assert recipe["allow_download"] is False
    assert recipe["parameters"]["width"] == 832
    assert recipe["parameters"]["height"] == 480
    assert recipe["parameters"]["num_frames"] == 80
    assert recipe["parameters"]["inference_num_frames"] == 81
    assert recipe["parameters"]["num_inference_steps"] == 25
    assert recipe["parameters"]["guidance_scale"] == 5
    assert recipe["parameters"]["flow_shift"] == 3
    assert not output.exists()
    assert not output.with_suffix(".mp4.json").exists()
    assert events == []
    assert preflight.runtime_calls == 0
    forbidden.assert_not_called()


@pytest.mark.parametrize(("flag", "value"), [("--steps", "0"), ("--fps", "61"), ("--guidance", "0")])
def test_invalid_cli_recipe_is_rejected_before_model_load(tmp_path, flag, value, capsys) -> None:
    events: list[str] = []
    assert (
        main(
            [*arguments(tmp_path / "test.mp4"), flag, value],
            dependencies=dependencies(tmp_path, FakePreflight(), events),
        )
        == 1
    )
    assert "FAIL Configuration" in capsys.readouterr().err
    assert events == []


@pytest.mark.parametrize(("flag", "value"), [("--seconds", "nan"), ("--width", "-1"), ("--seed", "-1")])
def test_invalid_request_is_actionable_without_starting_application(tmp_path, flag, value, capsys) -> None:
    events: list[str] = []
    assert (
        main(
            [*arguments(tmp_path / "test.mp4"), flag, value, "--dry-run"],
            dependencies=dependencies(tmp_path, FakePreflight(), events),
        )
        == 1
    )
    assert "Wan test failed" in capsys.readouterr().err
    assert events == []


@pytest.mark.parametrize("collision", ["video", "manifest"])
def test_cli_refuses_existing_outputs_without_overwriting(tmp_path, collision, capsys) -> None:
    output = tmp_path / "test.mp4"
    existing = output if collision == "video" else output.with_suffix(".mp4.json")
    existing.write_bytes(b"existing owner file")
    events: list[str] = []
    assert main([*arguments(output), "--dry-run"], dependencies=dependencies(tmp_path, FakePreflight(), events)) == 1
    assert existing.read_bytes() == b"existing owner file"
    assert "already exists" in capsys.readouterr().err
    assert events == []


@pytest.mark.parametrize("failure", ["none", "generation", "probe", "decode", "mismatch"])
async def test_manual_test_validates_output_and_manifest_or_removes_owned_partial_files(
    tmp_path, monkeypatch, failure
) -> None:
    configured = settings(tmp_path, WAN_FPS=16, WAN_INFERENCE_STEPS=25)
    output = tmp_path / "test.mp4"
    request = VideoGenerationRequest("A paper boat floating at night", "", 832, 480, 5, 42)
    media = MagicMock()
    media.probe = AsyncMock(
        return_value={
            "streams": [
                {
                    "codec_type": "video",
                    "width": 832,
                    "height": 480,
                    "nb_frames": "79" if failure == "mismatch" else "80",
                    "r_frame_rate": "16/1",
                }
            ],
            "format": {"duration": "5"},
        }
    )
    media.decode = AsyncMock()
    if failure == "probe":
        media.probe.side_effect = ProviderError("generation_invalid_output", "Invalid video", transient=False)
    elif failure == "decode":
        media.decode.side_effect = ProviderError("generation_invalid_output", "Invalid video", transient=False)
    monkeypatch.setattr("clipfactory.infrastructure.wan_test.MediaRunner", lambda *_args: media)

    async def fake_generate(self, request, destination, *, progress=None):
        assert self.allow_download is False
        if failure == "generation":
            raise ProviderError("generation_failed", "Local inference failed", transient=False)
        destination.write_bytes(b"test encoded video")
        return GeneratedMedia(destination, "fixture-wan", "Apache-2.0", self.generation_recipe(request))

    monkeypatch.setattr("clipfactory.infrastructure.wan_test.WanLocalVideoProvider.generate", fake_generate)
    if failure == "none":
        recipe = await run_wan_test(configured, request, output)
        assert output.read_bytes() == b"test encoded video"
        assert json.loads(output.with_suffix(".mp4.json").read_text()) == recipe
        assert recipe["validated"] is True
        media.probe.assert_awaited_once()
        media.decode.assert_awaited_once()
    else:
        with pytest.raises(ProviderError):
            await run_wan_test(configured, request, output)
        assert not output.exists()
        assert not output.with_suffix(".mp4.json").exists()
    assert not list(tmp_path.glob("wan-test-*"))
