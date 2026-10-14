import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import TypeAdapter, ValidationError

from clipfactory.assets.generation import generate_video_asset
from clipfactory.domain.graphics import (
    FunctionPlot,
    GraphicsError,
    GraphicsSpec,
    GroundedText,
    reusable_render_duration,
    sample_function,
    validate_graphics_claims,
)
from clipfactory.domain.models import AssetOrigin, Claim, ClaimStatus, ContentProfile, Stage, SupportLevel
from clipfactory.infrastructure.providers.graphics_process import run_graphics_process
from clipfactory.infrastructure.providers.graphics_templates import infographic_html
from clipfactory.infrastructure.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from clipfactory.infrastructure.providers.local_graphics import HyperFramesVideoProvider, ManimVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.settings_validation import apply_runtime_environment, runtime_environment_defaults
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.planning.script import VisualDraft, WriteScriptResult
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, GeneratedMedia, GenerationProgress, VideoGenerationRequest
from clipfactory.ports.llm import LLMMessage
from clipfactory.workflow.graph import (
    WorkflowState,
    _stage_node,
    renew_generation_watchdog,
    reset_stage_timeout,
    set_stage_timeout,
)
from clipfactory.workflow.llm_activity import ObservedLLMProvider
from clipfactory.workflow.production_stages import ProductionStageService

pytestmark = [pytest.mark.unit, pytest.mark.req("CF-REQ-263")]
NOW = datetime(2026, 10, 8, tzinfo=UTC)
CLAIM_ID = UUID("11111111-1111-4111-8111-111111111111")


def label(text: str) -> dict[str, Any]:
    return {"text": text, "claim_ids": [str(CLAIM_ID)]}


def payload(template: str = "statistic") -> dict[str, Any]:
    title = label("Synthetic study")
    items = [{"label": label("Group A"), "value": 42}, {"label": label("Group B"), "value": 21}]
    if template == "statistic":
        return {"template": template, "title": title, "item": items[0]}
    if template == "comparison":
        return {"template": template, "title": title, "items": items}
    if template == "timeline":
        return {
            "template": template,
            "title": title,
            "events": [
                {"date": label("2025"), "label": label("Group A")},
                {"date": label("2026"), "label": label("Group B")},
            ],
        }
    if template == "key_date":
        return {"template": template, "title": title, "date": label("2025")}
    if template == "relationship_diagram":
        return {
            "template": template,
            "title": title,
            "nodes": [{"id": "a", "label": label("Group A")}, {"id": "b", "label": label("Group B")}],
            "edges": [{"source": "a", "target": "b", "label": label("supports")}],
        }
    return {"template": template, "title": title, "function": "quadratic", "x_min": -3, "x_max": 3}


def claim() -> Claim:
    return Claim(
        id=CLAIM_ID,
        story_id=uuid4(),
        text="Synthetic study: Group A 42 supports Group B 21 in 2025 and 2026.",
        status=ClaimStatus.ACCEPTED,
        support_level=SupportLevel.CORROBORATED,
    )


def spec(template: str = "statistic") -> GraphicsSpec:
    return TypeAdapter(GraphicsSpec).validate_python(payload(template))


def request(template: str = "statistic") -> VideoGenerationRequest:
    return VideoGenerationRequest("Synthetic study", "", 720, 1280, 5, 0, spec(template))


def assets_and_media() -> tuple[MagicMock, MagicMock]:
    assets = MagicMock()
    assets.list.return_value = []
    assets.by_hash.return_value = None
    assets.save.side_effect = lambda asset: asset
    media = MagicMock()
    media.probe = AsyncMock(
        return_value={
            "streams": [{"codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "30/1"}],
            "format": {"duration": "5"},
        }
    )
    media.decode = AsyncMock()
    return assets, media


class FakeGraphics:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls: list[VideoGenerationRequest] = []

    def is_configured(self) -> bool:
        return True

    def estimate_cost(self, request: VideoGenerationRequest) -> Decimal:
        return Decimal("0")

    async def generate(
        self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
    ) -> GeneratedMedia:
        self.calls.append(request)
        if self.fail:
            raise ProviderError("graphics_render_failed", "Synthetic renderer failure", transient=False)
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, b"\x00\x00\x00\x18ftypmp42synthetic")
        if progress:
            await progress("", {"generation_phase": "heartbeat"})
            await progress("Rendering graphic", {"generation_phase": "rendering"})
        assert request.graphics_spec is not None
        return GeneratedMedia(
            destination,
            self.name,
            "MIT",
            {
                "graphics_spec": request.graphics_spec.model_dump(mode="json"),
                "template_version": "1",
                "fps": 30,
            },
        )


@pytest.mark.parametrize(
    "template", ["statistic", "comparison", "timeline", "key_date", "function_plot", "relationship_diagram"]
)
def test_supported_templates_are_bounded_and_grounded(template: str) -> None:
    validate_graphics_claims(spec(template), [claim()])


def test_old_draft_defaults_to_media() -> None:
    old = {
        "objective": "Power grid",
        "media_type": "any",
        "category": "photo",
        "description": "Substation",
        "subjects": [],
        "tags": ["energy"],
        "strategy": "reuse_first",
        "motion": "pan_left",
        "transition_in": "cut",
    }
    draft = VisualDraft.model_validate(old)
    assert draft.kind == "media"
    assert draft.graphics_spec is None
    assert draft.motion == "pan_left"


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        "https://example.test",
        "javascript:alert(1)",
        "eval(x)",
        "$(touch /tmp/bad)",
        "import(os)",
        "x; rm -rf /",
        "```python",
        "<svg/>",
    ],
)
def test_executable_markup_shell_and_url_input_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        GroundedText(text=text, claim_ids=[CLAIM_ID])


@pytest.mark.req("CF-REQ-263")
@pytest.mark.parametrize("text", ["Starlink price $10 a month", "AT&T subscribers", "Jio & Airtel", "\u20b9840 plan"])
def test_currency_and_ampersand_are_plain_factual_text(text: str) -> None:
    assert GroundedText(text=text, claim_ids=[CLAIM_ID]).text == text


@pytest.mark.parametrize("mutation", ["number", "other_item_number", "claim", "label", "rejected"])
def test_claim_id_is_not_permission_to_invent_facts(mutation: str) -> None:
    value = payload()
    accepted = claim()
    if mutation == "number":
        value["item"]["value"] = 43
    elif mutation == "other_item_number":
        value["item"]["value"] = 21
    elif mutation == "claim":
        value["item"]["label"]["claim_ids"] = [str(uuid4())]
    elif mutation == "label":
        value["item"]["label"]["text"] = "Group C"
    else:
        accepted = accepted.model_copy(update={"status": ClaimStatus.REJECTED})
    with pytest.raises(GraphicsError, match="Graphics") as failure:
        validate_graphics_claims(TypeAdapter(GraphicsSpec).validate_python(value), [accepted])
    assert failure.value.code == "unsupported_statement"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1e16])
def test_numeric_values_bounded(value: float) -> None:
    data = payload()
    data["item"]["value"] = value
    with pytest.raises(ValidationError):
        TypeAdapter(GraphicsSpec).validate_python(data)


@pytest.mark.parametrize("template", ["map", "html", "arbitrary_equation", "svg"])
def test_unsupported_templates_do_not_get_substitutes(template: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(GraphicsSpec).validate_python(payload(template))


def test_function_enum_sampling_is_fixed_not_eval() -> None:
    function = FunctionPlot(
        template="function_plot",
        title=GroundedText(**label("Synthetic study")),
        function="linear",
        a=2,
        b=1,
        x_min=-2,
        x_max=2,
    )
    samples = sample_function(function)
    assert len(samples) == 256
    assert samples[0] == (-2, -3)
    assert samples[-1] == (2, 5)
    assert samples == sample_function(function)
    with pytest.raises(ValidationError):
        FunctionPlot.model_validate({**function.model_dump(), "function": "__import__('os').system('id')"})


def test_numeric_grounding_preserves_sign_grouping_and_full_precision() -> None:
    data = payload()
    data["item"]["value"] = 123456789012345
    accepted = claim().model_copy(update={"text": "Synthetic study: Group A 123,456,789,012,345."})
    validate_graphics_claims(TypeAdapter(GraphicsSpec).validate_python(data), [accepted])
    data["item"]["value"] = 42
    accepted = claim().model_copy(update={"text": "Synthetic study: Group A -42."})
    with pytest.raises(GraphicsError):
        validate_graphics_claims(TypeAdapter(GraphicsSpec).validate_python(data), [accepted])


def test_claim_backed_person_name_is_text_not_depiction() -> None:
    data = payload("relationship_diagram")
    data["nodes"][0]["label"] = label("Jane Smith")
    accepted = claim().model_copy(update={"text": "Synthetic study: Jane Smith supports Group B."})
    validate_graphics_claims(TypeAdapter(GraphicsSpec).validate_python(data), [accepted])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("script_path", "/untrusted/anything.py"),
        ("html", "<script/>"),
        ("url", "https://example.test"),
    ],
)
def test_no_executable_path_or_fetch_fields(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(GraphicsSpec).validate_python({**payload(), field: value})


@pytest.mark.parametrize("mutation", ["template", "unsafe_label", "extra_code"])
async def test_graphics_schema_failures_are_not_repaired_by_another_llm_call(mutation: str) -> None:
    visual: dict[str, Any] = {
        "kind": "infographic",
        "objective": "Explain",
        "description": "Synthetic study",
        "media_type": "video",
        "category": "graphic",
        "strategy": "generate_allowed",
        "graphics_spec": payload(),
    }
    if mutation == "template":
        visual["graphics_spec"]["template"] = "map"
    elif mutation == "unsafe_label":
        visual["graphics_spec"]["title"]["text"] = "<script/>"
    else:
        visual["script_path"] = "/untrusted/code.js"
    output = {
        "segments": [{"text": "Synthetic study", "claim_ids": [str(CLAIM_ID)]}],
        "social_metadata": {"title": "Study", "description": "Synthetic", "hashtags": ["#a", "#b", "#c"]},
        "visuals": [visual],
    }
    calls: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        calls.append(incoming)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output)}}]})

    values: dict[str, Any] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql://unused/fixture",
        "LLM_API_KEY": "synthetic-nonsecret-key",
    }
    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = ObservedLLMProvider(
        OpenAICompatibleLLMProvider(EnvironmentSettings(**values), client=client),
        MagicMock(),
        max_schema_repairs=3,
    )
    try:
        with pytest.raises(ProviderError) as failure:
            await provider.generate_structured("write_script", [LLMMessage("user", "Synthetic")], WriteScriptResult)
        assert failure.value.code == (
            "unsupported_graphics_template" if mutation == "template" else "unsupported_statement"
        )
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.req("CF-REQ-264")
@pytest.mark.req("CF-REQ-265")
@pytest.mark.parametrize(
    ("kind", "template", "renderer"),
    [
        ("infographic", "comparison", "hyperframes"),
        ("scientific", "function_plot", "manim"),
    ],
)
async def test_runtime_dispatch_ignores_media_provider_order_and_imports(
    tmp_path: Path, kind: str, template: str, renderer: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    providers = [FakeGraphics("wan_local"), FakeGraphics("manim"), FakeGraphics("hyperframes")]
    assets, media = assets_and_media()
    production, runs = MagicMock(), MagicMock()
    plan = {
        "version": 1,
        "segments": [
            {
                "index": 0,
                "narration_text": "Synthetic study",
                "objective": "Explain study",
                "motion": "none",
                "planned_duration_seconds": 5,
                "requirement": {
                    "kind": kind,
                    "graphics_spec": payload(template),
                    "media_type": "video",
                    "category": "chart",
                    "description": "Synthetic study",
                    "subjects": [],
                    "tags": [],
                    "strategy": "generate_allowed",
                },
            }
        ],
    }
    production.current_visual_plan.return_value = plan
    production.package_context.return_value = {"claims": [claim()]}
    profile = ContentProfile()
    profile = profile.model_copy(
        update={"generation": profile.generation.model_copy(update={"video_providers": ["wan_local"]})}
    )
    runs.get.return_value = {"attempt": 1, "profile_snapshot": profile.model_dump(mode="json"), "settings_snapshot": {}}
    watchdog = MagicMock()
    monkeypatch.setattr("clipfactory.workflow.production_stages.renew_generation_watchdog", watchdog)
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=MagicMock(),
        storage=LocalStorageProvider(tmp_path),
        media=media,
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        video_providers=[providers[0]],
        graphics_providers=providers[1:],
    )
    await service.select_assets(
        {"run_id": str(uuid4()), "story_package_id": str(uuid4()), "attempt": 1, "trigger": "run_now"}
    )
    assert [len(provider.calls) for provider in providers] == ([0, 0, 1] if renderer == "hyperframes" else [0, 1, 0])
    saved = assets.save.call_args.args[0]
    assert saved.provenance.origin == AssetOrigin.RENDERED
    assert saved.provenance.provider == renderer
    assert saved.provenance.generation["parameters"]["graphics_spec"] == spec(template).model_dump(mode="json")
    assert saved.reusable
    media.decode.assert_awaited_once()
    assert watchdog.call_count >= 2
    phases = [call.kwargs["payload"] for call in runs.append_event.call_args_list]
    assert all(item.get("generation_phase") != "heartbeat" for item in phases)
    rendering = next(item for item in phases if item.get("generation_phase") == "rendering")
    assert rendering["segment_index"] == 0
    assert rendering["segment_count"] == 1
    assert "progress_fraction" not in rendering
    assert plan["segments"][0]["selection_reason"] == "rendered"
    assets.list.return_value = [saved]
    for provider in providers:
        provider.fail = True
    await service.select_assets(
        {"run_id": str(uuid4()), "story_package_id": str(uuid4()), "attempt": 1, "trigger": "run_now"}
    )
    assert plan["segments"][0]["selection_reason"] == "reused"
    assert sum(len(provider.calls) for provider in providers) == 1


@pytest.mark.req("CF-REQ-264")
@pytest.mark.parametrize(
    ("permission", "strategy", "subjects"),
    [
        (False, "generate_allowed", []),
        (True, "acquire_only", []),
        (True, "generate_allowed", ["Jane Smith"]),
    ],
)
async def test_graphics_preserve_policy_and_named_person_guard(
    tmp_path: Path, permission: bool, strategy: str, subjects: list[str]
) -> None:
    provider = FakeGraphics("hyperframes")
    assets, media = assets_and_media()
    production = MagicMock()
    production.package_context.return_value = {"claims": [claim()]}
    service = ProductionStageService(
        production=production,
        runs=MagicMock(),
        assets=assets,
        evaluations=MagicMock(),
        storage=LocalStorageProvider(tmp_path),
        media=media,
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        graphics_providers=[provider],
    )
    profile = ContentProfile()
    profile = profile.model_copy(
        update={"visual_style": profile.visual_style.model_copy(update={"allow_generated_media": permission})}
    )
    segment = {
        "index": 0,
        "planned_duration_seconds": 5,
        "requirement": {
            "kind": "infographic",
            "graphics_spec": payload(),
            "category": "graphic",
            "description": "Synthetic study",
            "subjects": subjects,
            "tags": [],
            "strategy": strategy,
        },
    }
    with pytest.raises(GraphicsError, match="permission"):
        await service._select_graphic(segment, profile, uuid4(), {}, [], set(), AsyncMock(), 1)
    assert provider.calls == []


@pytest.mark.req("CF-REQ-265")
async def test_graphics_failure_explicit_and_recovery_metadata_retained(tmp_path: Path) -> None:
    first, fallback = FakeGraphics("hyperframes", fail=True), FakeGraphics("wan_local")
    assets, media = assets_and_media()
    storage = LocalStorageProvider(tmp_path)
    with pytest.raises(ProviderError) as failure:
        await generate_video_asset(
            request(),
            providers=[first, fallback],
            storage=storage,
            assets=assets,
            media=media,
            now=NOW,
            progress=AsyncMock(),
            max_video_bytes=10000,
            min_video_height_px=720,
        )
    assert failure.value.code == "graphics_render_failed"
    assert fallback.calls == []
    assets.save.assert_not_called()
    metadata = await asyncio.to_thread(lambda: list(tmp_path.glob("generated-media/pending/*.json")))
    assert len(metadata) == 1
    assert json.loads(metadata[0].read_text())["graphics_spec"]["template"] == "statistic"


@pytest.mark.req("CF-REQ-265")
async def test_import_failure_retains_rendered_video_and_metadata_without_activation(tmp_path: Path) -> None:
    provider = FakeGraphics("hyperframes")
    assets, media = assets_and_media()
    media.decode.side_effect = ProviderError("graphics_render_failed", "Synthetic invalid video", transient=False)
    progress = AsyncMock()
    with pytest.raises(ProviderError):
        await generate_video_asset(
            request(),
            providers=[provider],
            storage=LocalStorageProvider(tmp_path),
            assets=assets,
            media=media,
            now=NOW,
            progress=progress,
            max_video_bytes=10000,
            min_video_height_px=720,
        )
    assets.save.assert_not_called()
    pending = await asyncio.to_thread(lambda: list(tmp_path.glob("generated-media/pending/*.mp4")))
    metadata = await asyncio.to_thread(lambda: list(tmp_path.glob("generated-media/pending/*.json")))
    assert len(pending) == 1
    assert len(metadata) == 1
    assert progress.call_args.args[1]["recovery_storage_key"]


@pytest.mark.req("CF-REQ-265")
@pytest.mark.parametrize("measurement", ["width", "duration", "fps", "nonfinite"])
async def test_wrong_renderer_output_is_never_activated(tmp_path: Path, measurement: str) -> None:
    provider = FakeGraphics("hyperframes")
    assets, media = assets_and_media()
    probe = media.probe.return_value
    if measurement == "width":
        probe["streams"][0]["width"] = 1080
    elif measurement == "duration":
        probe["format"]["duration"] = "2"
    elif measurement == "fps":
        probe["streams"][0]["r_frame_rate"] = "24/1"
    else:
        probe["format"]["duration"] = "nan"
    with pytest.raises(ProviderError):
        await generate_video_asset(
            request(),
            providers=[provider],
            storage=LocalStorageProvider(tmp_path),
            assets=assets,
            media=media,
            now=NOW,
            progress=AsyncMock(),
            max_video_bytes=10000,
            min_video_height_px=720,
        )
    assets.save.assert_not_called()


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-604")
async def test_owner_stop_cancels_graphics_import_worker(tmp_path: Path) -> None:
    assets, media = assets_and_media()
    entered, cancelled = asyncio.Event(), asyncio.Event()

    class WaitingGraphics(FakeGraphics):
        async def generate(
            self, request: VideoGenerationRequest, destination: Path, *, progress: GenerationProgress | None = None
        ) -> GeneratedMedia:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            raise AssertionError("unreachable")

    abort = Event()
    token = GENERATION_ABORT.set(abort)
    try:
        task = asyncio.create_task(
            generate_video_asset(
                request(),
                providers=[WaitingGraphics("hyperframes")],
                storage=LocalStorageProvider(tmp_path),
                assets=assets,
                media=media,
                now=NOW,
                progress=AsyncMock(),
                max_video_bytes=10000,
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


@pytest.mark.req("CF-REQ-265")
async def test_cancel_owned_renderer_not_unrelated_process(tmp_path: Path) -> None:
    unrelated = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
    owned_pid = tmp_path / "owned.pid"
    task = asyncio.create_task(
        run_graphics_process(
            [
                sys.executable,
                "-c",
                "import os,time,pathlib; pathlib.Path('owned.pid').write_text(str(os.getpid())); time.sleep(30)",
            ],
            cwd=tmp_path,
            timeout_seconds=30,
        )
    )
    try:
        async with asyncio.timeout(10):
            for _ in range(500):
                if await asyncio.to_thread(owned_pid.exists):
                    break
                await asyncio.sleep(0.02)
        pid = int(await asyncio.to_thread(owned_pid.read_text))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(2):
                await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert unrelated.returncode is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        unrelated.kill()
        await unrelated.wait()


@pytest.mark.req("CF-REQ-265")
async def test_renderer_timeout_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="timeout"):
        await run_graphics_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            cwd=tmp_path,
            timeout_seconds=0.05,
        )


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-656")
async def test_active_local_renderer_renews_watchdog_without_ui_progress(tmp_path: Path) -> None:
    visible: list[dict[str, object]] = []

    async def progress(message: str, payload: dict[str, object]) -> None:
        renew_generation_watchdog()
        if payload.get("generation_phase") != "heartbeat":
            visible.append(payload)

    class Executor:
        async def execute(self, stage: Stage, state: WorkflowState) -> dict[str, Any]:
            await run_graphics_process(
                [sys.executable, "-c", "import time; time.sleep(4)"],
                cwd=tmp_path,
                timeout_seconds=6,
                progress=progress,
            )
            return {}

        async def evaluation_passed(self, state: WorkflowState) -> bool:
            return True

    token = set_stage_timeout(2.5)
    try:
        assert (
            await _stage_node(Executor(), Stage.SELECT_ASSETS, None)(
                {"run_id": "synthetic-watchdog", "trigger": "run_now"}
            )
            == {}
        )
        assert visible == []
    finally:
        reset_stage_timeout(token)


@pytest.mark.req("CF-REQ-760")
def test_graphics_config_bounds_and_snapshot() -> None:
    values: dict[str, Any] = {"_env_file": None, "DATABASE_URL": "postgresql://unused/fixture"}
    environment = EnvironmentSettings(**values)
    assert runtime_environment_defaults(environment)["graphics_fps"] == 30
    assert runtime_environment_defaults(environment)["graphics_timeout_seconds"] == 180
    target = environment.model_copy(deep=True)
    apply_runtime_environment(target, environment, {"graphics_fps": 24, "graphics_timeout_seconds": 60})
    assert target.graphics_fps == 24
    assert target.graphics_timeout_seconds == 60
    assert environment.graphics_fps == 30
    with pytest.raises(ValidationError):
        apply_runtime_environment(target, environment, {"graphics_fps": 61})


@pytest.mark.req("CF-REQ-265")
@pytest.mark.parametrize(("renderer", "template"), [("hyperframes", "timeline"), ("manim", "function_plot")])
async def test_real_adapter_commands_and_render_output(
    tmp_path: Path, renderer: str, template: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    values: dict[str, Any] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql://unused/fixture",
        "HYPERFRAMES_PATH": tmp_path / "launcher.mjs",
        "MANIM_PATH": sys.executable,
    }
    settings = EnvironmentSettings(**values)
    package = tmp_path / "package"
    (package / "node_modules/gsap/dist").mkdir(parents=True)
    (package / "node_modules/gsap/dist/gsap.min.js").write_text("// synthetic local GSAP")
    settings.hyperframes_package_dir = package
    adapter = HyperFramesVideoProvider(settings) if renderer == "hyperframes" else ManimVideoProvider(settings)
    monkeypatch.setattr(adapter, "is_configured", lambda: True)
    commands: list[list[str]] = []
    destination = tmp_path / "out.mp4"

    async def run(arguments: list[str], **kwargs: Any) -> None:
        commands.append(arguments)
        if renderer == "hyperframes":
            if "render" in arguments:
                await asyncio.to_thread(destination.write_bytes, b"synthetic render")
        else:
            output = kwargs["cwd"] / "media/videos/scene/1280p30/graphic.mp4"
            await asyncio.to_thread(output.parent.mkdir, parents=True)
            await asyncio.to_thread(output.write_bytes, b"synthetic render")

    monkeypatch.setattr("clipfactory.infrastructure.providers.local_graphics.run_graphics_process", run)
    result = await adapter.generate(request(template), destination)
    assert result.path == destination
    assert result.parameters["template"] == template
    assert result.parameters["fps"] == 30
    assert len(commands) == (2 if renderer == "hyperframes" else 1)
    assert all("shell" not in command for command in commands)
    if renderer == "hyperframes":
        html = (tmp_path / "out-work/index.html").read_text()
        assert 'data-composition-id="graphic"' in html
        assert 'data-duration="5"' in html
        assert "https://" not in html
        assert 'window.__timelines["graphic"]' in html
    else:
        data = json.loads((tmp_path / "out-work/input.json").read_text())
        assert len(data["samples"]) == 256
        assert "--renderer" in commands[0]
        assert "cairo" in commands[0]


def test_infographic_html_has_only_trusted_local_runtime() -> None:
    html = infographic_html(request())
    assert "paused:true" in html
    assert "gsap.min.js" in html
    assert "Date.now" not in html
    assert "fetch(" not in html
    assert "<svg" not in html


@pytest.mark.req("CF-REQ-264")
async def test_missing_renderer_is_not_fake_success(tmp_path: Path) -> None:
    values: dict[str, Any] = {"_env_file": None, "DATABASE_URL": "postgresql://unused/fixture"}
    settings = EnvironmentSettings(**values)
    provider = HyperFramesVideoProvider(settings)
    assert not provider.is_configured()
    with pytest.raises(ProviderError, match="configure"):
        await provider.generate(request(), tmp_path / "never.mp4")


@pytest.mark.req("CF-REQ-263")
@pytest.mark.parametrize(
    ("kind", "expected_kind", "primary", "fallback"),
    [("scientific", "infographic", True, False), ("media", "media", False, True)],
)
def test_a_mislabelled_kind_is_normalized_from_the_supported_template(
    kind: str, expected_kind: str, primary: bool, fallback: bool
) -> None:
    draft = VisualDraft.model_validate(
        {
            "kind": kind,
            "objective": "Explain",
            "description": "Synthetic study",
            "media_type": "video",
            "category": "graphic",
            "strategy": "generate_allowed",
            "graphics_spec": payload(),
        }
    )
    assert draft.kind == expected_kind
    assert (draft.graphics_spec is not None) is primary
    assert (draft.fallback_graphics_spec is not None) is fallback


@pytest.mark.req("CF-REQ-263")
@pytest.mark.parametrize("fallback", [False, True])
def test_a_graphics_kind_without_a_template_becomes_media_without_new_content(fallback: bool) -> None:
    draft = VisualDraft.model_validate(
        {
            "kind": "infographic",
            "objective": "Explain",
            "description": "Synthetic",
            "media_type": "video",
            "category": "graphic",
            **({"fallback_graphics_spec": payload()} if fallback else {}),
        }
    )
    assert draft.kind == "media"
    assert draft.graphics_spec is None
    assert (draft.fallback_graphics_spec is not None) is fallback


@pytest.mark.req("CF-REQ-263")
def test_a_graphics_visual_keeps_its_primary_and_drops_a_redundant_fallback() -> None:
    draft = VisualDraft.model_validate(
        {
            "kind": "infographic",
            "objective": "Explain",
            "description": "Synthetic",
            "media_type": "video",
            "category": "graphic",
            "graphics_spec": payload(),
            "fallback_graphics_spec": payload(),
        }
    )
    assert draft.kind == "infographic"
    assert draft.graphics_spec is not None
    assert draft.fallback_graphics_spec is None


@pytest.mark.req("CF-REQ-263")
def test_an_unsupported_template_still_fails() -> None:
    with pytest.raises(ValidationError):
        VisualDraft.model_validate(
            {
                "kind": "infographic",
                "objective": "Explain",
                "description": "Synthetic",
                "media_type": "video",
                "category": "graphic",
                "graphics_spec": {**payload(), "template": "map"},
            }
        )


@pytest.mark.req("CF-REQ-265")
@pytest.mark.parametrize(
    ("template", "rendered", "planned", "reusable"),
    [
        ("key_date", 4.0, 2.8, True),
        ("key_date", 4.0, 2.0, False),
        ("key_date", 2.8, 4.0, False),
        ("timeline", 5.0, 4.0, False),
        ("timeline", 5.0, 4.5, True),
        ("comparison", 12.0, 6.0, False),
        ("function_plot", 5.0, 4.0, False),
        ("function_plot", 5.0, 5.02, True),
    ],
)
def test_longer_render_is_reusable_only_once_its_entrance_has_settled(
    template: str, rendered: float, planned: float, reusable: bool
) -> None:
    assert reusable_render_duration(spec(template), rendered, planned, 1 / 30) is reusable


@pytest.mark.req("CF-REQ-265")
async def test_retry_that_shortens_a_key_date_segment_reuses_the_identical_card(tmp_path: Path) -> None:
    hyperframes = FakeGraphics("hyperframes")
    assets, media = assets_and_media()
    production, runs = MagicMock(), MagicMock()
    segment: dict[str, Any] = {
        "index": 0,
        "narration_text": "The vote is on November 29.",
        "objective": "Mark the date",
        "motion": "none",
        "planned_duration_seconds": 5,
        "requirement": {
            "kind": "infographic",
            "graphics_spec": payload("key_date"),
            "media_type": "video",
            "category": "graphic",
            "description": "A simple graphic showing the election date",
            "subjects": [],
            "tags": [],
            "strategy": "generate_allowed",
        },
    }
    plan = {"version": 1, "segments": [segment]}
    production.current_visual_plan.return_value = plan
    production.package_context.return_value = {"claims": [claim()]}
    profile = ContentProfile()
    runs.get.return_value = {"attempt": 1, "profile_snapshot": profile.model_dump(mode="json"), "settings_snapshot": {}}
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=MagicMock(),
        storage=LocalStorageProvider(tmp_path),
        media=media,
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        video_providers=[],
        graphics_providers=[hyperframes],
    )
    state: WorkflowState = {
        "run_id": str(uuid4()),
        "story_package_id": str(uuid4()),
        "attempt": 1,
        "trigger": "run_now",
    }
    await service.select_assets(state)
    assets.list.return_value = [assets.save.call_args.args[0]]
    segment["planned_duration_seconds"] = 2.8
    segment.pop("selected_asset_id")
    await service.select_assets({**state, "attempt": 2})
    assert len(hyperframes.calls) == 1
    assert segment["selection_reason"] == "reused"


def _key_date_segment(index: int) -> dict[str, Any]:
    return {
        "index": index,
        "script_segment_index": index,
        "narration_text": f"Talks resume on Monday in round {index}.",
        "objective": "Mark the date",
        "motion": "none",
        "planned_duration_seconds": 5,
        "requirement": {
            "kind": "infographic",
            "graphics_spec": payload("key_date"),
            "fallback_graphics_spec": None,
            "media_type": "video",
            "category": "graphic",
            "description": "Monday key date",
            "subjects": [],
            "tags": [],
            "strategy": "generate_allowed",
            "search_queries": [],
        },
    }


def _deduplicating_assets() -> tuple[MagicMock, MagicMock]:
    """Identical deterministic renders import as the same content-addressed Asset."""
    assets, media = assets_and_media()
    saved: dict[str, Any] = {}

    def save(asset: Any) -> Any:
        saved[asset.sha256] = asset
        return asset

    assets.save.side_effect = save
    assets.by_hash.side_effect = saved.get
    return assets, media


@pytest.mark.req("CF-REQ-265")
async def test_duplicate_render_keeps_its_specific_code_instead_of_generic_render_failure(tmp_path: Path) -> None:
    provider = FakeGraphics("hyperframes")
    assets, media = _deduplicating_assets()
    progress = AsyncMock()
    arguments: dict[str, Any] = {
        "providers": [provider],
        "storage": LocalStorageProvider(tmp_path),
        "assets": assets,
        "media": media,
        "now": NOW,
        "progress": progress,
        "max_video_bytes": 10000,
        "min_video_height_px": 720,
    }
    first = await generate_video_asset(request("key_date"), **arguments)
    assert first is not None
    with pytest.raises(ProviderError) as duplicate:
        await generate_video_asset(request("key_date"), **arguments, excluded_asset_ids=frozenset({str(first.id)}))
    assert duplicate.value.code == "generation_duplicate"
    assert duplicate.value.detail == str(first.id)
    assert duplicate.value.transient is False
    payloads = [call.args[1] for call in progress.await_args_list]
    assert [item.get("error_code") for item in payloads if item.get("generation_phase") == "failed"] == [
        "generation_duplicate"
    ]
    assert payloads[-1]["asset_id"] == str(first.id)


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-410")
async def test_repeated_key_date_card_becomes_a_blocking_replan_issue_not_a_terminal_failure(
    tmp_path: Path,
) -> None:
    hyperframes = FakeGraphics("hyperframes")
    assets, media = _deduplicating_assets()
    production, runs, evaluations = MagicMock(), MagicMock(), MagicMock()
    plan = {"version": 1, "segments": [_key_date_segment(0), _key_date_segment(1)]}
    production.current_visual_plan.return_value = plan
    production.package_context.return_value = {"claims": [claim()]}
    runs.get.return_value = {
        "attempt": 1,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {},
    }
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=assets,
        evaluations=evaluations,
        storage=LocalStorageProvider(tmp_path),
        media=media,
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
        video_providers=[],
        graphics_providers=[hyperframes],
    )

    await service.select_assets(
        {"run_id": str(uuid4()), "story_package_id": str(uuid4()), "attempt": 1, "trigger": "run_now"}
    )

    first_asset = plan["segments"][0]["selected_asset_id"]
    assert "selected_asset_id" not in plan["segments"][1]
    assert plan["segments"][1]["selection_reason"] == "duplicate_graphic"
    production.save_visual_plan.assert_called_once()
    production.save_artifact.assert_not_called()
    evaluation = evaluations.save.call_args.args[0]
    assert evaluation.passed is False
    assert [issue.code for issue in evaluation.issues] == ["generation_duplicate"]
    assert evaluation.issues[0].refs == {"segment_index": 1, "duplicate_asset_id": first_asset}
    assert [(action.type.value, action.target_stage) for action in evaluation.actions] == [
        ("replan_visuals", Stage.PLAN_VISUALS)
    ]


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-410")
@pytest.mark.req("CF-REQ-412")
async def test_duplicate_replan_converts_only_that_visual_and_keeps_other_selections(tmp_path: Path) -> None:
    production, runs = MagicMock(), MagicMock()
    shown: dict[str, Any] = _key_date_segment(0) | {"selected_asset_id": "card-asset", "selection_reason": "rendered"}
    repeated: dict[str, Any] = _key_date_segment(1) | {"selection_reason": "duplicate_graphic"}
    portrait = _key_date_segment(2)
    portrait["requirement"] = {
        "kind": "media",
        "category": "person",
        "graphics_spec": None,
        "person": {"name": "Jane Smith", "fallback": dict(_key_date_segment(2)["requirement"])},
    }
    plan = {"version": 3, "segments": [shown, repeated, portrait]}
    production.current_visual_plan.return_value = plan
    production.current_script.return_value = {"version": 3, "segments": []}
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=MagicMock(),
        evaluations=MagicMock(),
        storage=LocalStorageProvider(tmp_path),
        media=MagicMock(),
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
    )
    package_id = uuid4()
    actions = [
        {
            "type": "replan_visuals",
            "target_stage": "plan_visuals",
            "instructions": "replan",
            "refs": {"segment_index": index, "duplicate_asset_id": "card-asset"},
        }
        for index in (1, 2)
    ]

    await service.plan_visuals(
        {
            "run_id": str(uuid4()),
            "story_package_id": str(package_id),
            "attempt": 2,
            "trigger": "run_now",
            "reentry_stage": "plan_visuals",
            "pending_actions": actions,
            "affected_segments": [1, 2],
        }
    )

    production.save_visual_plan.assert_called_once_with(package_id, 3, plan)
    assert shown["selected_asset_id"] == "card-asset"
    assert shown["requirement"]["graphics_spec"] == payload("key_date")
    replanned: dict[str, Any] = repeated["requirement"]
    assert replanned["kind"] == "media"
    assert replanned["category"] == "broll"
    assert replanned["graphics_spec"] is None
    assert replanned["fallback_graphics_spec"] is None
    assert replanned["description"] == repeated["narration_text"]
    assert "selection_reason" not in repeated
    assert portrait["requirement"]["person"]["name"] == "Jane Smith"
    assert portrait["requirement"]["person"]["fallback"]["kind"] == "media"
    assert portrait["requirement"]["person"]["fallback"]["graphics_spec"] is None
    events = [call.kwargs["payload"] for call in runs.append_event.call_args_list]
    assert [(item["segment_index"], item["replan_reason"]) for item in events] == [
        (1, "generation_duplicate"),
        (2, "generation_duplicate"),
    ]


def _two_card_script() -> dict[str, Any]:
    card = {
        "objective": "Mark the day",
        "media_type": "video",
        "category": "graphic",
        "description": "Monday key date",
        "kind": "infographic",
        "strategy": "generate_allowed",
        "graphics_spec": payload("key_date"),
    }
    texts = ["Talks open in 2025 with ministers present.", "Talks close in 2025 after two days."]
    return {
        "version": 2,
        "language": "en",
        "segments": [
            {"index": i, "text": t, "claim_ids": [str(CLAIM_ID)], "estimated_duration_seconds": 3}
            for i, t in enumerate(texts)
        ],
        "word_count": 15,
        "estimated_duration_seconds": 6,
        "social_metadata": {"title": "Title", "description": "Description", "hashtags": ["#a", "#b", "#c"]},
        "visual_draft": [card, card],
        "llm_model": "fake",
    }


@pytest.mark.req("CF-REQ-265")
@pytest.mark.req("CF-REQ-410")
@pytest.mark.req("CF-REQ-412")
@pytest.mark.parametrize("duplicate_in_this_retry", [True, False])
async def test_mixed_replan_rebuild_keeps_duplicate_override_and_unchanged_selections(
    tmp_path: Path, duplicate_in_this_retry: bool
) -> None:
    production, runs = MagicMock(), MagicMock()
    production.current_script.return_value = _two_card_script()
    production.package_context.return_value = {"claims": [claim()]}
    runs.get.return_value = {
        "attempt": 2,
        "profile_snapshot": ContentProfile().model_dump(mode="json"),
        "settings_snapshot": {},
    }
    service = ProductionStageService(
        production=production,
        runs=runs,
        assets=MagicMock(),
        evaluations=MagicMock(),
        storage=LocalStorageProvider(tmp_path),
        media=MagicMock(),
        clock=lambda: NOW,
        llm=MagicMock(),
        tts=MagicMock(),
        transcription=MagicMock(),
    )
    package_id = uuid4()
    state: WorkflowState = {
        "run_id": str(uuid4()),
        "story_package_id": str(package_id),
        "attempt": 1,
        "trigger": "run_now",
    }
    production.current_visual_plan.side_effect = LookupError
    await service.plan_visuals(state)
    initial = production.save_visual_plan.call_args.args[2]
    assert [s["requirement"]["graphics_spec"] for s in initial["segments"]] == [payload("key_date")] * 2
    initial["segments"][0] |= {"selected_asset_id": "card-asset", "selection_reason": "rendered", "motion": "none"}
    if not duplicate_in_this_retry:
        await service._replan_duplicates(UUID(state["run_id"]), initial, {1: "card-asset"})
        initial["segments"][1] |= {"selected_asset_id": "footage-asset", "selection_reason": "reviewed"}
    production.current_visual_plan.side_effect = None
    production.current_visual_plan.return_value = initial
    actions: list[dict[str, Any]] = [
        {"type": "replan_visuals", "target_stage": "plan_visuals", "instructions": "pacing", "refs": {}}
    ]
    if duplicate_in_this_retry:
        actions.append(
            {
                "type": "replan_visuals",
                "target_stage": "plan_visuals",
                "instructions": "duplicate",
                "refs": {"segment_index": 1, "duplicate_asset_id": "card-asset"},
            }
        )

    await service.plan_visuals({**state, "attempt": 2, "reentry_stage": "plan_visuals", "pending_actions": actions})

    saved = production.save_visual_plan.call_args.args[2]
    first, second = saved["segments"]
    assert first["selected_asset_id"] == "card-asset"
    assert first["requirement"]["graphics_spec"] == payload("key_date")
    assert second["requirement"]["kind"] == "media"
    assert second["requirement"]["graphics_spec"] is None
    assert second["duplicate_replan"] == "card-asset"
    if duplicate_in_this_retry:
        assert "selected_asset_id" not in second
    else:
        assert second["selected_asset_id"] == "footage-asset"
