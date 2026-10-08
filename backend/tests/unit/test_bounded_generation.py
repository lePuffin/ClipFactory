"""CF-REQ-266: offline Run-backed quota and grounded alternative acceptance tests."""

import asyncio
import copy
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine
from test_generation_fallback import FakeVideoProvider, fake_assets, fake_inspector
from test_local_graphics import FakeGraphics, assets_and_media, claim, payload, spec
from test_script_planning import FakeLLM, _result
from test_settings_and_api import Configuration, RunCreatorFake, settings

from clipfactory.api.app import create_app
from clipfactory.assets.candidate_review import ReviewMediaResult
from clipfactory.assets.generation import generate_video_asset
from clipfactory.assets.selection import AssetRequirement, refined_media_queries
from clipfactory.domain.graphics import GraphicsError
from clipfactory.domain.models import AssetOrigin, ContentProfile, RunTrigger
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import RunRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.providers.wan_local import WanLocalVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.settings_validation import apply_runtime_environment
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.planning.script import VisualDraft, WriteScriptResult, generate_script
from clipfactory.planning.visuals import _normalize_segment
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import GENERATION_ABORT, VideoGenerationRequest
from clipfactory.ports.media_sources import DownloadedMedia, MediaCandidate
from clipfactory.workflow.executor import StageFailure
from clipfactory.workflow.production_stages import ProductionStageService

pytestmark = [pytest.mark.unit, pytest.mark.req("CF-REQ-266")]
NOW = datetime(2026, 10, 8, tzinfo=UTC)


@pytest.fixture
def repository(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bounded.db'}")
    Base.metadata.create_all(engine)
    yield RunRepository(create_session_factory(engine))
    engine.dispose()


def plan(count: int = 5) -> dict[str, Any]:
    return {
        "version": 1,
        "segments": [
            {
                "index": index,
                "narration_text": "Energy infrastructure needs repair",
                "objective": "Show the power grid",
                "planned_duration_seconds": 5,
                "motion": "none",
                "requirement": {
                    "kind": "media",
                    "graphics_spec": None,
                    "media_type": "video",
                    "category": "broll",
                    "description": "Electricity substation",
                    "subjects": ["electricity"],
                    "tags": ["power", "grid"],
                    "strategy": "reuse_first",
                },
            }
            for index in range(count)
        ],
    }


def create_run(repository: RunRepository, limit: int = 2) -> UUID:
    return UUID(
        repository.create(
            RunTrigger.RUN_NOW,
            manual_url=None,
            settings_snapshot={"environment": {"wan_max_generations_per_run": limit}},
        )["run_id"]
    )


def service(
    repository: RunRepository, tmp_path: Path, visual_plan: dict[str, Any], provider: Any, **overrides: Any
) -> ProductionStageService:
    production = MagicMock()
    production.current_visual_plan.return_value = visual_plan
    production.package_context.return_value = {"title": "Power grid", "claims": [claim()]}
    arguments = {
        "production": production,
        "runs": repository,
        "assets": fake_assets(),
        "evaluations": MagicMock(),
        "storage": LocalStorageProvider(tmp_path),
        "media": fake_inspector(),
        "clock": lambda: NOW,
        "llm": MagicMock(),
        "tts": MagicMock(),
        "transcription": MagicMock(),
        "video_providers": [provider],
    }
    return ProductionStageService(**{**arguments, **overrides})


async def select(service: ProductionStageService, run_id: UUID, attempt: int = 1) -> None:
    await service.select_assets(
        {"run_id": str(run_id), "story_package_id": str(uuid4()), "attempt": attempt, "trigger": "run_now"}
    )


def starts(repository: RunRepository, run_id: UUID) -> list[dict[str, Any]]:
    return [
        event
        for event in repository.events(run_id)
        if event["payload"].get("provider") == "wan_local" and event["payload"].get("generation_phase") == "started"
    ]


@pytest.mark.parametrize("limit", [0, 1, 2, 4, 100])
@pytest.mark.parametrize("failure", [False, True])
async def test_five_unmet_visuals_have_exact_bounded_actual_starts(
    repository: RunRepository, tmp_path: Path, limit: int, failure: bool
) -> None:
    run_id = create_run(repository, limit)
    provider = FakeVideoProvider(failure=failure)
    visual_plan = plan()
    instance = service(repository, tmp_path, visual_plan, provider)
    await select(instance, run_id)
    assert len(provider.calls) == min(limit, 5)
    assert len(starts(repository, run_id)) == len(provider.calls)
    assert [event["payload"]["generation_count"] for event in starts(repository, run_id)] == list(
        range(1, min(limit, 5) + 1)
    )
    evaluation = instance.evaluations.save.call_args.args[0]
    assert len(evaluation.issues) == (5 if failure else 5 - min(limit, 5))
    assert all(issue.code == "missing_asset" for issue in evaluation.issues)
    cap_skips = [
        event for event in repository.events(run_id) if event["payload"].get("generation_phase") == "cap_skipped"
    ]
    assert len(cap_skips) == max(0, 5 - limit)
    assert all(event["payload"]["generation_limit"] == limit for event in cap_skips)


async def test_legacy_usage_retry_restart_and_continue_never_reset(repository: RunRepository, tmp_path: Path) -> None:
    run_id = create_run(repository)
    repository.claim_next_queued(NOW)
    repository.append_event(
        run_id, "progress", "Legacy generation", payload={"provider": "wan_local", "generation_phase": "started"}
    )
    provider = FakeVideoProvider(failure=True)
    await select(service(repository, tmp_path, plan(), provider), run_id)
    assert len(provider.calls) == 1
    repository.apply_retry(run_id, attempt=2, revision_retries_used=1)
    fresh = RunRepository(repository.sessions)
    await select(service(fresh, tmp_path, plan(), provider), run_id, 2)
    assert len(provider.calls) == 1
    fresh.fail(run_id, "select_assets", "interrupted", "Synthetic failure", NOW)
    fresh.continue_failed(
        run_id,
        settings_snapshot={"environment": {"wan_max_generations_per_run": 1}},
        expected_stage="select_assets",
        now=NOW,
    )
    fresh.claim_next_queued(NOW)
    await select(service(fresh, tmp_path, plan(), provider), run_id, 2)
    assert len(provider.calls) == 1
    fresh.fail(run_id, "select_assets", "interrupted", "Synthetic failure", NOW)
    fresh.continue_failed(
        run_id,
        settings_snapshot={"environment": {"wan_max_generations_per_run": 4}},
        expected_stage="select_assets",
        now=NOW,
    )
    await select(service(RunRepository(repository.sessions), tmp_path, plan(), provider), run_id, 2)
    assert len(provider.calls) == 3
    assert len(starts(fresh, run_id)) == 4


async def test_unconfigured_provider_consumes_nothing(repository: RunRepository, tmp_path: Path) -> None:
    run_id = create_run(repository)
    provider = FakeVideoProvider()
    provider.is_configured = lambda: False
    await select(service(repository, tmp_path, plan(), provider), run_id)
    assert provider.calls == []
    assert starts(repository, run_id) == []


async def test_cap_prevents_native_pipeline_load(repository: RunRepository, tmp_path: Path) -> None:
    run_id = create_run(repository, 0)
    factory = MagicMock(side_effect=AssertionError("Native model loading must never occur at the cap"))
    provider = WanLocalVideoProvider(settings(_env_file=None), fake_inspector(), pipeline_factory=factory)
    await select(service(repository, tmp_path, plan(), provider), run_id)
    factory.assert_not_called()
    assert starts(repository, run_id) == []


async def test_reusing_wan_asset_after_continue_at_zero_consumes_no_allowance(
    repository: RunRepository, tmp_path: Path
) -> None:
    run_id = create_run(repository)
    repository.claim_next_queued(NOW)
    provider = FakeVideoProvider()
    instance = service(repository, tmp_path, plan(1), provider)
    await select(instance, run_id)
    saved = instance.assets.save.call_args.args[0]
    assert saved.provenance.provider == "wan_local"
    repository.fail(run_id, "select_assets", "interrupted", "Synthetic failure", NOW)
    repository.continue_failed(
        run_id,
        settings_snapshot={"environment": {"wan_max_generations_per_run": 0}, "assets": {"reuse_min_match_score": 0}},
        expected_stage="select_assets",
        now=NOW,
    )
    instance.assets.list.return_value = [saved]
    instance.llm.generate_structured = AsyncMock(
        return_value=MagicMock(
            value=ReviewMediaResult.model_validate({"choices": [{"segment": 0, "ranked": ["s0c0"]}]})
        )
    )
    await select(instance, run_id)
    assert len(provider.calls) == 1
    assert len(starts(repository, run_id)) == 1
    assert instance.production.current_visual_plan.return_value["segments"][0]["selection_reason"] == "reused"


def test_concurrent_reservations_across_repository_instances_are_atomic(repository: RunRepository) -> None:
    run_id = create_run(repository)

    def reserve(index: int) -> bool:
        return RunRepository(repository.sessions).reserve_generation_start(
            run_id, provider="wan_local", limit=2, segment_index=index, now=NOW
        )

    with ThreadPoolExecutor(max_workers=8) as workers:
        permitted = list(workers.map(reserve, range(20)))
    assert sum(permitted) == 2
    assert len(starts(repository, run_id)) == 2
    assert [event["sequence"] for event in repository.events(run_id)] == list(range(1, 22))


async def test_cancelled_actual_start_consumes_reservation(repository: RunRepository, tmp_path: Path) -> None:
    run_id = create_run(repository, 1)
    provider = FakeVideoProvider()
    entered = asyncio.Event()

    async def cancelled(*args: Any, **kwargs: Any) -> None:
        entered.set()
        await asyncio.Event().wait()

    provider.generate = cancelled  # type: ignore[method-assign]
    abort = Event()
    token = GENERATION_ABORT.set(abort)

    async def permit(name: str) -> bool:
        return await asyncio.to_thread(
            repository.reserve_generation_start, run_id, provider=name, limit=1, segment_index=0, now=NOW
        )

    try:
        task = asyncio.create_task(
            generate_video_asset(
                VideoGenerationRequest("Power grid", "", 720, 1280, 5, 1),
                providers=[provider],
                storage=LocalStorageProvider(tmp_path),
                assets=fake_assets(),
                media=fake_inspector(),
                now=NOW,
                progress=AsyncMock(),
                max_video_bytes=1000000,
                min_video_height_px=720,
                start_permit=permit,
            )
        )
        await entered.wait()
        abort.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(starts(repository, run_id)) == 1
        assert not await permit("wan_local")
    finally:
        GENERATION_ABORT.reset(token)


@pytest.mark.parametrize(("template", "renderer"), [("comparison", "hyperframes"), ("function_plot", "manim")])
@pytest.mark.parametrize("wan_state", ["exhausted", "unconfigured", "failed"])
async def test_declared_grounded_graphics_fallback_routes_without_wan(
    repository: RunRepository, tmp_path: Path, template: str, renderer: str, wan_state: str
) -> None:
    run_id = create_run(repository, 0 if wan_state == "exhausted" else 1)
    visual_plan = plan(1)
    visual_plan["segments"][0]["requirement"]["fallback_graphics_spec"] = payload(template)
    wan = FakeVideoProvider(failure=wan_state == "failed")
    if wan_state == "unconfigured":
        wan.is_configured = lambda: False
    graphic = FakeGraphics(renderer)
    assets, media = assets_and_media()
    instance = service(repository, tmp_path, visual_plan, wan, graphics_providers=[graphic], assets=assets, media=media)
    await select(instance, run_id)
    requirement = visual_plan["segments"][0]["requirement"]
    assert len(wan.calls) == int(wan_state == "failed")
    assert len(starts(repository, run_id)) == int(wan_state == "failed")
    assert len(graphic.calls) == 1
    assert requirement["kind"] == ("infographic" if renderer == "hyperframes" else "scientific")
    assert requirement["graphics_spec"] == spec(template).model_dump(mode="json")
    assert requirement["media_type"] == "video"
    assert requirement["category"] == "chart"
    assert requirement["fallback_graphics_spec"] == spec(template).model_dump(mode="json")
    assert visual_plan["segments"][0]["selection_reason"] == "graphics_fallback"
    saved = assets.save.call_args.args[0]
    assert saved.provenance.origin == AssetOrigin.RENDERED
    assert saved.provenance.provider == renderer
    assert saved.provenance.generation["parameters"]["graphics_spec"] == spec(template).model_dump(mode="json")
    assert instance.evaluations.save.call_args.args[0].passed
    instance.assets.list.return_value = [saved]
    await select(instance, run_id, 2)
    assert len(graphic.calls) == 1
    assert visual_plan["segments"][0]["selection_reason"] == "reused"
    assert visual_plan["segments"][0]["requirement"]["fallback_graphics_spec"] == spec(template).model_dump(mode="json")
    # Retry still recognizes the declared alternative if its prior Asset is no longer reusable.
    instance.assets.list.return_value = []
    await select(instance, run_id, 3)
    assert len(graphic.calls) == 2
    assert len(wan.calls) == int(wan_state == "failed")
    assert requirement["strategy"] == "reuse_first"


@pytest.mark.parametrize("restriction", ["disabled", "person", "acquire_only", "evidence", "renderer"])
async def test_graphics_permissions_evidence_and_failure_are_not_bypassed(
    repository: RunRepository, tmp_path: Path, restriction: str
) -> None:
    run_id = create_run(repository, 0)
    visual_plan = plan(1)
    requirement = visual_plan["segments"][0]["requirement"]
    requirement["fallback_graphics_spec"] = payload()
    if restriction == "person":
        requirement["subjects"] = ["Jane Smith"]
    if restriction == "acquire_only":
        requirement["strategy"] = "acquire_only"
    if restriction == "evidence":
        requirement["fallback_graphics_spec"]["item"]["value"] = 99
    if restriction == "disabled":
        with repository.sessions.begin() as session:
            row = session.get(RunRow, run_id)
            assert row is not None
            snapshot = copy.deepcopy(row.profile_snapshot)
            snapshot["visual_style"]["allow_generated_media"] = False
            row.profile_snapshot = snapshot
    graphic = FakeGraphics("hyperframes", fail=restriction == "renderer")
    assets, media = assets_and_media()
    wan = FakeVideoProvider()
    instance = service(repository, tmp_path, visual_plan, wan, graphics_providers=[graphic], assets=assets, media=media)
    if restriction in {"evidence", "renderer"}:
        with pytest.raises(StageFailure) as failure:
            await select(instance, run_id)
        assert failure.value.code == (
            "unsupported_statement" if restriction == "evidence" else "graphics_render_failed"
        )
    else:
        await select(instance, run_id)
        assert not instance.evaluations.save.call_args.args[0].passed
    assert len(graphic.calls) == int(restriction == "renderer")
    assert wan.calls == []
    assets.save.assert_not_called()


def test_queries_and_normalized_draft_are_bounded_distinct_and_backward_compatible() -> None:
    base = dict(plan(1)["segments"][0]["requirement"])
    base["objective"] = "Power grid"
    draft = VisualDraft.model_validate(base)
    assert draft.search_queries == []
    assert draft.fallback_graphics_spec is None
    draft = VisualDraft.model_validate(
        {**base, "search_queries": ["power station", "grid transformer"], "fallback_graphics_spec": payload()}
    )
    normalized = _normalize_segment(0, 0, "Power grid", 5, draft, True)
    assert normalized.requirement["graphics_spec"] is None
    assert normalized.requirement["fallback_graphics_spec"] == payload()
    assert normalized.requirement["search_queries"] == ["power station", "grid transformer"]
    for values in (["a", "b", "c"], ["Grid", "grid"], [""], ["x" * 121], ["a " * 13], ["Electricity substation"]):
        with pytest.raises(ValidationError):
            VisualDraft.model_validate({**base, "search_queries": values})
    requirement = AssetRequirement("video", "broll", "Electricity substation", ("electricity",), ("power", "grid"))
    queries = refined_media_queries(requirement)
    assert queries == ("electricity", "electricity power grid")
    assert len(set(queries)) == 2


@pytest.mark.parametrize("supported", [True, False])
async def test_writer_declares_and_grounds_alternatives_in_its_existing_single_call(supported: bool) -> None:
    accepted = claim()
    value = _result([accepted]).model_dump(mode="json")
    value["visuals"][0]["fallback_graphics_spec"] = payload()
    value["visuals"][0]["search_queries"] = ["laboratory equipment", "research instruments"]
    if not supported:
        value["visuals"][0]["fallback_graphics_spec"]["item"]["value"] = 99
    llm = FakeLLM(WriteScriptResult.model_validate(value))
    arguments = {
        "story_title": "Synthetic study",
        "story_summary": "Source-grounded research",
        "claims": [accepted],
        "key_fact_claim_ids": [accepted.id],
        "profile": ContentProfile(),
    }
    if supported:
        generated = await generate_script(llm, **arguments)
        assert generated.visuals[0].graphics_spec is None
        assert generated.visuals[0].fallback_graphics_spec is not None
    else:
        with pytest.raises(GraphicsError, match="value"):
            await generate_script(llm, **arguments)
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == "write_script"
    assert "fallback_graphics_spec" in llm.calls[0][1][0].content
    assert "search_queries" in llm.calls[0][1][0].content


class RefinedSource:
    name = "fake"

    def __init__(self, storage: LocalStorageProvider, bad: str = "") -> None:
        self.storage = storage
        self.bad = bad
        self.queries: list[str] = []
        self.downloads: list[MediaCandidate] = []

    async def search(self, request: Any) -> list[MediaCandidate]:
        self.queries.append(request.description)
        if request.description == "Electricity substation":
            return []
        return [
            MediaCandidate(
                f"https://media.example/{request.description}/{index}",
                f"https://media.example/{request.description}/{index}.png",
                self.name,
                "" if self.bad == "licence" else "CC0",
                "image",
                100 if self.bad == "resolution" else 800,
                1200,
                description="Electricity grid transformer",
            )
            for index in range(2)
        ]

    async def download(self, candidate: MediaCandidate, dest: str, max_bytes: int) -> DownloadedMedia:
        self.downloads.append(candidate)
        output = io.BytesIO()
        Image.new("RGB", (800, 1200), "red").save(output, format="PNG")
        body = b"invalid" if self.bad == "invalid" else output.getvalue()
        if len(body) > max_bytes:
            raise ProviderError("media_too_large", "Too large", transient=False)
        await self.storage.put_bytes(dest, body)
        return DownloadedMedia(dest, len(body), hashlib.sha256(body).hexdigest())


async def test_acquire_only_uses_deterministic_refinement_never_declared_graphics_or_wan(
    repository: RunRepository, tmp_path: Path
) -> None:
    run_id = create_run(repository)
    visual_plan = plan(1)
    requirement = visual_plan["segments"][0]["requirement"]
    requirement.update(strategy="acquire_only", media_type="image", category="photo", fallback_graphics_spec=payload())
    storage = LocalStorageProvider(tmp_path)
    source = RefinedSource(storage)
    wan, graphic = FakeVideoProvider(), FakeGraphics("hyperframes")
    llm = MagicMock()
    llm.generate_structured = AsyncMock(
        return_value=MagicMock(
            value=ReviewMediaResult.model_validate({"choices": [{"segment": 0, "ranked": ["s0c0"]}]})
        )
    )
    instance = service(
        repository,
        tmp_path,
        visual_plan,
        wan,
        media_sources=[source],
        graphics_providers=[graphic],
        llm=llm,
        storage=storage,
    )
    await select(instance, run_id)
    assert source.queries == ["Electricity substation", "electricity", "electricity power grid"]
    assert wan.calls == []
    assert graphic.calls == []
    assert starts(repository, run_id) == []
    assert llm.generate_structured.await_count == 1
    assert requirement["kind"] == "media"
    assert requirement["graphics_spec"] is None
    assert visual_plan["segments"][0]["selection_reason"] == "refined_search"
    assert instance.evaluations.save.call_args.args[0].passed


@pytest.mark.parametrize("judgement", ["accepted", "rejected", "foreign", "unavailable"])
@pytest.mark.parametrize("bad", ["", "licence", "resolution", "invalid", "duplicate", "size"])
async def test_refined_candidates_are_batched_reviewed_and_import_safeguards_remain(
    repository: RunRepository, tmp_path: Path, judgement: str, bad: str
) -> None:
    run_id = create_run(repository, 0)
    visual_plan = plan(2)
    for segment in visual_plan["segments"]:
        segment["requirement"].update(
            media_type="image", category="photo", search_queries=["power station", "grid transformer"]
        )
    storage = LocalStorageProvider(tmp_path)
    source = RefinedSource(storage, bad)
    llm = MagicMock()

    async def review(task: str, messages: Any, schema: Any, **kwargs: Any) -> Any:
        assert task == "review_media_candidates"
        if judgement == "unavailable":
            raise ProviderError("llm_budget_exhausted", "No review budget", transient=False)
        data = json.loads(messages[1].content.split("<untrusted-candidate-metadata>\n")[1].split("\n</")[0])
        assert len(data) == 2
        assert all(item["intent"] == "Show the power grid: Electricity substation" for item in data)
        return MagicMock(
            value=schema(
                choices=[
                    {
                        "segment": item["segment"],
                        "ranked": (
                            [item["candidates"][0]["id"]]
                            if judgement == "accepted"
                            else ["s99c99"]
                            if judgement == "foreign"
                            else []
                        ),
                    }
                    for item in data
                ]
            )
        )

    llm.generate_structured = AsyncMock(side_effect=review)
    assets = fake_assets()
    assets.by_hash.side_effect = lambda digest: next(
        (call.args[0] for call in assets.save.call_args_list if call.args[0].sha256 == digest), None
    )
    if bad == "size":
        with repository.sessions.begin() as session:
            row = session.get(RunRow, run_id)
            assert row is not None
            row.settings_snapshot = {
                "environment": {"wan_max_generations_per_run": 0},
                "assets": {"max_image_bytes": 1},
            }
    instance = service(
        repository,
        tmp_path,
        visual_plan,
        FakeVideoProvider(),
        media_sources=[source],
        llm=llm,
        assets=assets,
        storage=storage,
    )
    if judgement == "unavailable" and bad not in {"licence", "resolution"}:
        with pytest.raises(StageFailure, match="No review budget"):
            await select(instance, run_id)
    else:
        await select(instance, run_id)
    assert set(source.queries) == {"Electricity substation", "power station", "grid transformer"}
    assert llm.generate_structured.await_count == (0 if bad in {"licence", "resolution"} else 1)
    if judgement != "accepted" or bad in {"licence", "resolution", "invalid", "size"}:
        assets.save.assert_not_called()
        if judgement != "accepted" or bad in {"licence", "resolution"}:
            assert source.downloads == []
    else:
        selected = assets.save.call_args.args[0]
        # Identical downloaded content is resolved to the original Asset, not used twice.
        assets.by_hash.return_value = selected
        if bad == "duplicate":
            for segment in visual_plan["segments"]:
                segment["requirement"]["strategy"] = "acquire_only"
            await select(instance, run_id)
            assert len(instance.evaluations.save.call_args.args[0].issues) == 1
        assert selected.provenance.origin == AssetOrigin.EXTERNAL
        assert selected.provenance.license == "CC0"
        assert visual_plan["segments"][0]["selection_reason"] == "refined_search"
        assert visual_plan["segments"][0]["requirement"]["graphics_spec"] is None
    assert starts(repository, run_id) == []


def test_settings_default_env_api_validation_and_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAN_MAX_GENERATIONS_PER_RUN", raising=False)
    configured = settings(_env_file=None)
    assert configured.wan_max_generations_per_run == 2
    configuration, runs = Configuration(), RunCreatorFake()
    client = TestClient(create_app(configured, configuration=configuration, run_creator=runs))
    assert client.get("/api/settings").json()["settings"]["environment"]["wan_max_generations_per_run"] == 2
    for value in (-1, 101, 1.5, True, "3", None):
        assert client.put("/api/settings/environment", json={"wan_max_generations_per_run": value}).status_code == 422
    for value in (0, 1, 7, 100):
        assert client.put("/api/settings/environment", json={"wan_max_generations_per_run": value}).status_code == 200
        assert client.get("/api/settings").json()["settings"]["environment"]["wan_max_generations_per_run"] == value
        assert client.post("/api/runs").status_code == 202
        assert runs.snapshots[-1]["environment"]["wan_max_generations_per_run"] == value
    monkeypatch.setenv("WAN_MAX_GENERATIONS_PER_RUN", "9")
    baseline = settings(_env_file=None)
    assert baseline.wan_max_generations_per_run == 9
    target = baseline.model_copy()
    apply_runtime_environment(target, baseline, {"wan_max_generations_per_run": 0})
    assert target.wan_max_generations_per_run == 0
    apply_runtime_environment(target, baseline, {})
    assert target.wan_max_generations_per_run == 9
    for value in (-1, 101):
        values: dict[str, Any] = {
            "_env_file": None,
            "DATABASE_URL": "postgresql://unused/test",
            "WAN_MAX_GENERATIONS_PER_RUN": value,
        }
        with pytest.raises(ValidationError):
            EnvironmentSettings(**values)
