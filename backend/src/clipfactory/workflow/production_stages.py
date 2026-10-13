"""Thin workflow adapters for executable planning, production, evaluation and retry stages."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from clipfactory.assets.acquisition import acquire_asset, search_media_candidates
from clipfactory.assets.candidate_review import SegmentCandidates
from clipfactory.assets.generation import generate_video_asset
from clipfactory.assets.graphics import graphics_provider
from clipfactory.assets.music import select_music
from clipfactory.assets.retention import retire_run_external_assets
from clipfactory.assets.selection import (
    AssetRequirement,
    choose_reusable_asset,
    rank_media_candidates,
    refined_media_queries,
)
from clipfactory.assets.vision_review import review_media_candidates
from clipfactory.composition.render import freeze_end_card, render_clip
from clipfactory.composition.spec import AudioInput, CompositionSpec, OverlayInput, VisualInput
from clipfactory.domain.graphics import (
    GraphicsError,
    GraphicsSpec,
    graphics_kind,
    reusable_render_duration,
    validate_graphics_claims,
    validate_graphics_kind,
)
from clipfactory.domain.models import (
    ActionType,
    Asset,
    AssetOrigin,
    AssetStatus,
    ClipStatus,
    ContentProfile,
    Evaluation,
    EvaluationLayer,
    Issue,
    IssueSeverity,
    Provenance,
    Stage,
)
from clipfactory.evaluation.retry import plan_retry
from clipfactory.evaluation.semantic import evaluate_semantics, representative_frames
from clipfactory.evaluation.validation import (
    EvaluationContext,
    MediaValidationSpec,
    build_evaluation,
    validate_duration,
    validate_media,
)
from clipfactory.planning.motion import ShotMedia, choose_shot_motions
from clipfactory.planning.people import expand_bare_names, name_candidates
from clipfactory.planning.script import (
    BuzzLineDraft,
    EditorialDraft,
    GeneratedScript,
    PersonDraft,
    ScriptGateError,
    ScriptSegment,
    SocialMetadataDraft,
    VisualDraft,
    WriteScriptResult,
    generate_script,
    normalize_people,
)
from clipfactory.planning.visuals import (
    build_visual_plan,
    contains_named_person,
    distinct_media_searches,
    serialize_visual_plan,
    with_date_cards,
)
from clipfactory.ports.errors import ProviderError
from clipfactory.ports.generation import VideoGenerationRequest, VideoProvider
from clipfactory.ports.llm import EVALUATION_FALLBACK_ERRORS, ImageInput, LLMModelRole
from clipfactory.ports.media import MediaProcessError
from clipfactory.ports.media_sources import MediaCandidate, MediaSourceProvider, PersonPortraits, PersonPortraitSource
from clipfactory.production.alignment import AlignedWord, AlignmentResult
from clipfactory.production.audio_captions import (
    NarrationDurationGateError,
    build_captions,
    generate_narration,
    transcribe_narration,
)
from clipfactory.production.editorial import (
    EditorialCue,
    render_ai_disclosure_tag,
    render_brand_mark,
    render_editorial_graphic,
    render_news_date,
)
from clipfactory.production.timing import prefer_covering_footage, reconcile_visual_timing, short_footage
from clipfactory.workflow.executor import EvaluationStatusReader, StageFailure, StageUseCase
from clipfactory.workflow.graph import WorkflowState, renew_generation_watchdog

logger = logging.getLogger(__name__)


class ProductionStageUseCase:
    def __init__(self, stage: Stage, service: ProductionStageService) -> None:
        self.stage = stage
        self.service = service

    async def execute(self, state: WorkflowState) -> dict[str, Any]:
        method = getattr(self.service, self.stage.value)
        result: dict[str, Any] = await method(state)
        return result


class PersistedEvaluationStatus(EvaluationStatusReader):
    def __init__(self, evaluations: Any) -> None:
        self.evaluations = evaluations

    async def passed(self, state: WorkflowState) -> bool:
        ids = state.get("last_evaluation_ids", [])
        if not ids:
            raise StageFailure("internal_error", "No persisted Evaluation is available for routing")
        evaluation = await asyncio.to_thread(self.evaluations.get, UUID(ids[-1]))
        if evaluation is None:
            raise StageFailure("internal_error", "The latest persisted Evaluation is missing")
        return evaluation.passed


_CONTEXT_KINDS = frozenset({"headline", "place", "number", "quote"})


class ProductionStageService:
    def __init__(
        self,
        *,
        production: Any,
        runs: Any,
        assets: Any,
        evaluations: Any,
        storage: Any,
        llm: Any,
        tts: Any,
        transcription: Any,
        media: Any,
        clock: Callable[[], datetime],
        media_sources: Sequence[MediaSourceProvider] = (),
        video_providers: Sequence[VideoProvider] = (),
        graphics_providers: Sequence[VideoProvider] = (),
        candidate_preview: Callable[[MediaCandidate], Awaitable[ImageInput | None]] | None = None,
        person_portraits: PersonPortraitSource | None = None,
    ) -> None:
        self.production = production
        self.runs = runs
        self.assets = assets
        self.evaluations = evaluations
        self.storage = storage
        self.llm = llm
        self.tts = tts
        self.transcription = transcription
        self.media = media
        self.clock = clock
        self.media_sources = tuple(media_sources)
        self.video_providers = tuple(video_providers)
        self.graphics_providers = tuple(graphics_providers)
        self.candidate_preview = candidate_preview
        self.person_portraits = person_portraits

    async def build_story_package(self, state: WorkflowState) -> dict[str, Any]:
        return await asyncio.to_thread(self.production.create_story_package, UUID(state["run_id"]), self.clock())

    async def write_script(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, profile = await self._run_context(state)
        package_id = _required_uuid(state, "story_package_id")
        context = await asyncio.to_thread(self.production.package_context, package_id)
        configured = detail["settings_snapshot"].get("script", {})
        composition = detail["settings_snapshot"].get("composition", {})
        previous_script = None
        rejected_draft = None
        rejected_codes: list[str] = []
        if state.get("pending_actions"):
            retained = await asyncio.to_thread(self.production.latest_artifact, run_id, Stage.WRITE_SCRIPT.value)
            if retained and retained.get("story_package_id") == str(package_id) and not retained.get("passed", False):
                rejected_draft = WriteScriptResult.model_validate(retained["draft"])
                rejected_codes = retained["codes"]
            try:
                previous_script = await asyncio.to_thread(self.production.current_script, package_id)
            except LookupError:
                previous_script = None
        try:
            script = await generate_script(
                self.llm,
                story_title=context["title"],
                story_summary=context["summary"],
                claims=context["claims"],
                key_fact_claim_ids=[UUID(value) for value in context["key_fact_claim_ids"]],
                profile=profile,
                lead_in_seconds=float(composition.get("lead_in_seconds", 0.3)),
                tail_seconds=float(composition.get("tail_seconds", 1.0)),
                min_segments=int(configured.get("min_segments", 4)),
                max_segments=int(configured.get("max_segments", 8)),
                hook_max_seconds=float(configured.get("hook_max_seconds", 5.0)),
                revision_instructions=[str(action["instructions"]) for action in state.get("pending_actions", [])],
                target_word_count=next(
                    (
                        int(action["refs"]["target_word_count"])
                        for action in state.get("pending_actions", [])
                        if "target_word_count" in action.get("refs", {})
                    ),
                    None,
                ),
                source_attributions=context.get("source_attributions", []),
                claim_publishers=context.get("claim_publishers", {}),
                previous_script=previous_script,
                rejected_draft=rejected_draft,
                rejected_codes=rejected_codes,
            )
        except ScriptGateError as exc:
            if exc.draft is not None:
                await asyncio.to_thread(
                    self.production.save_artifact,
                    run_id,
                    attempt,
                    Stage.WRITE_SCRIPT.value,
                    {
                        "story_package_id": str(package_id),
                        "passed": False,
                        "codes": list(exc.codes),
                        "draft": exc.draft.model_dump(mode="json"),
                    },
                )
            evaluation = self._gate_evaluation(
                run_id, attempt, Stage.WRITE_SCRIPT, list(exc.codes), instructions=exc.detail or None
            )
            return await self._persist_evaluation(evaluation)
        except ProviderError as exc:
            if exc.code in {"unsupported_graphics_template", "unsupported_statement"}:
                raise StageFailure(exc.code, str(exc)) from exc
            raise StageFailure("llm_unavailable", str(exc)) from exc
        except GraphicsError as exc:
            raise StageFailure(exc.code, str(exc)) from exc
        version = await asyncio.to_thread(self.production.save_script, package_id, script, self.clock())
        await asyncio.to_thread(
            self.production.save_artifact,
            run_id,
            attempt,
            Stage.WRITE_SCRIPT.value,
            {"story_package_id": str(package_id), "passed": True},
        )
        evaluation = self._gate_evaluation(run_id, attempt, Stage.WRITE_SCRIPT, [])
        result = await self._persist_evaluation(evaluation)
        result["story_package_version"] = version
        return result

    async def plan_visuals(self, state: WorkflowState) -> dict[str, Any]:
        package_id = _required_uuid(state, "story_package_id")
        script_value = await asyncio.to_thread(self.production.current_script, package_id)
        script = _script_from_value(script_value)
        detail = await asyncio.to_thread(self.runs.get, UUID(state["run_id"]))
        profile = ContentProfile.model_validate(detail["profile_snapshot"])
        maximum = float(detail["settings_snapshot"].get("visual", {}).get("max_segment_seconds", 8.0))
        portrait_minimum = int(detail["settings_snapshot"].get("assets", {}).get("min_portrait_short_side_px", 480))
        script = await self._with_undeclared_people(script, package_id, portrait_minimum)
        context = await asyncio.to_thread(self.production.package_context, package_id)
        script = with_date_cards(
            script, context["claims"], allow_generated_media=profile.visual_style.allow_generated_media
        )
        plan = build_visual_plan(
            script, allow_generated_media=profile.visual_style.allow_generated_media, max_segment_seconds=maximum
        )
        value = {"version": script_value["version"], "segments": serialize_visual_plan(plan)}
        await asyncio.to_thread(self.production.save_visual_plan, package_id, script_value["version"], value)
        return {"story_package_version": script_value["version"]}

    async def _with_undeclared_people(
        self, script: GeneratedScript, package_id: UUID, portrait_minimum: int = 480
    ) -> GeneratedScript:
        """Add verified humans named in narration but omitted from the writing response (CF-REQ-268)."""
        source = self.person_portraits
        if source is None:
            return script
        context = await asyncio.to_thread(self.production.package_context, package_id)
        evidence = [claim.text for claim in context["claims"]] + [
            item.excerpt for claim in context["claims"] for item in claim.evidence
        ]
        expanded = expand_bare_names(script.people, evidence)
        if expanded != tuple(script.people):
            script = replace(script, people=normalize_people(expanded, script.segments))
        if len(script.people) >= 8:
            return script
        candidates = name_candidates(
            [segment.text for segment in script.segments],
            [claim.text for claim in context["claims"]],
            script.people,
        )
        found: list[PersonDraft] = []
        for name in candidates:
            try:
                resolved = await source.find_person(name, min_short_side_px=portrait_minimum)
            except ProviderError as exc:
                logger.warning("Person lookup for %r skipped: %s", name, exc.code)
                continue
            if resolved is not None and resolved.candidates:
                found.append(PersonDraft(name=name))
        if not found:
            return script
        people = normalize_people([*script.people, *found], script.segments)
        return replace(script, people=people)

    async def select_assets(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, profile = await self._run_context(state)
        package_id = _required_uuid(state, "story_package_id")
        plan = await asyncio.to_thread(self.production.current_visual_plan, package_id)
        distinct_media_searches(
            [(segment["requirement"], str(segment.get("narration_text", ""))) for segment in plan["segments"]]
        )
        available = await asyncio.to_thread(self.assets.list, status=AssetStatus.ACTIVE, limit=500)
        available = [asset for asset in available if asset.category != "title_card"]
        configured = detail["settings_snapshot"].get("assets", {})
        affected = set(state.get("affected_segments", []))
        used: set[str] = {
            str(action["refs"]["rejected_asset_id"])
            for action in state.get("pending_actions", [])
            if action.get("type") == ActionType.RESELECT_ASSET.value and action.get("refs", {}).get("rejected_asset_id")
        }
        tail_seconds = float(detail["settings_snapshot"].get("composition", {}).get("tail_seconds", 1.0))
        last_index = max((int(item["index"]) for item in plan["segments"]), default=0)

        async def progress(message: str, payload: dict[str, object]) -> None:
            await asyncio.to_thread(
                self.runs.append_event,
                run_id,
                "provider_call_failed" if "error_code" in payload else "progress",
                message,
                stage=Stage.SELECT_ASSETS.value,
                level="warning" if "error_code" in payload else "info",
                payload=payload,
            )

        policy = detail["settings_snapshot"].get("providers", {})
        retry_policy = {
            "max_call_retries": int(policy.get("max_call_retries", 3)),
            "retry_base_delay_seconds": float(policy.get("call_retry_base_delay_seconds", 2)),
            "retry_max_delay_seconds": float(policy.get("call_retry_max_delay_seconds", 60)),
        }
        pending: list[tuple[dict[str, Any], AssetRequirement, list[tuple[MediaCandidate, Any]]]] = []
        searched: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], list[tuple[MediaCandidate, Any]]] = {}
        review_limit = int(configured.get("candidates_per_review_segment", 10))
        people: dict[str, PersonPortraits | None] = {}
        person_occurrences: dict[str, int] = {}
        for segment in plan["segments"]:
            if segment.get("selected_asset_id") and (affected and int(segment["index"]) not in affected):
                used.add(str(segment["selected_asset_id"]))
                continue
            requirement = segment["requirement"]
            if isinstance(requirement.get("person"), dict):
                if await self._select_person(
                    segment, configured, available, used, progress, people, person_occurrences, retry_policy, run_id
                ):
                    continue
                # CF-REQ-268: without a verified licensed portrait, keep the writer's original visual intent.
                segment["requirement"] = requirement = dict(requirement["person"]["fallback"])
                segment.pop("identity", None)
            if requirement.get("kind", "media") != "media":
                try:
                    await self._select_graphic(
                        segment,
                        profile,
                        package_id,
                        {
                            **configured,
                            "graphics_fps": detail["settings_snapshot"].get("environment", {}).get("graphics_fps", 30),
                        },
                        available,
                        used,
                        progress,
                        len(plan["segments"]),
                        declared_fallback=(
                            requirement.get("fallback_graphics_spec") is not None
                            and requirement.get("fallback_graphics_spec") == requirement.get("graphics_spec")
                        ),
                    )
                except (GraphicsError, ProviderError) as exc:
                    raise StageFailure(exc.code, str(exc)) from exc
                continue
            asset_requirement = AssetRequirement(
                media_type=requirement["media_type"],
                category=requirement["category"],
                description=requirement["description"],
                subjects=tuple(requirement["subjects"]),
                tags=tuple(requirement["tags"]),
                min_width=int(configured.get("min_image_short_side_px", 720)),
                min_height=int(configured.get("min_video_height_px", 720)),
            )
            options: list[tuple[MediaCandidate, Any]] = [
                (_library_candidate(match.asset), match.asset)
                for match in [
                    choose_reusable_asset(
                        asset_requirement,
                        available,
                        now=self.clock(),
                        cooldown_days=int(configured.get("reuse_cooldown_days", 3)),
                        minimum_match=float(configured.get("reuse_min_match_score", 0.6)),
                        already_used=frozenset(used),
                    )
                ]
                if match is not None
            ]
            key = (
                asset_requirement.media_type,
                asset_requirement.description,
                asset_requirement.subjects,
                asset_requirement.tags,
            )
            if key not in searched:
                searched[key] = await search_media_candidates(
                    asset_requirement,
                    providers=self.media_sources,
                    candidates_per_search=int(configured.get("candidates_per_search", 10)),
                    progress=progress,
                    **retry_policy,
                )
            options.extend(searched[key][: max(0, review_limit - len(options))])
            pending.append((segment, asset_requirement, options))

        reviewed: dict[int, list[MediaCandidate]] | None = None
        if any(options for _, _, options in pending):
            context = await asyncio.to_thread(self.production.package_context, package_id)
            try:
                reviewed = await review_media_candidates(
                    self.llm,
                    [
                        SegmentCandidates(
                            int(segment["index"]),
                            str(segment["narration_text"]),
                            f"{segment['objective']}: {requirement.description}",
                            tuple(candidate for candidate, _ in options),
                        )
                        for segment, requirement, options in pending
                        if options
                    ],
                    story_title=str(context["title"]),
                    preview=self.candidate_preview,
                    max_images_per_request=int(configured.get("max_review_images_per_request", 10)),
                    fallback=_has_evaluation_fallback(detail),
                )
                await self._event(
                    run_id,
                    "progress",
                    "Candidate review kept "
                    f"{sum(len(items) for items in reviewed.values())} of "
                    f"{sum(len(options) for _, _, options in pending)} candidates",
                )
            except ProviderError as exc:
                if self.candidate_preview is not None:
                    raise StageFailure(exc.code, str(exc)) from exc
                await progress(
                    f"Candidate review unavailable ({exc.code}); falling back to metadata ranking",
                    {"error_code": exc.code},
                )

        fallback_pending: list[tuple[dict[str, Any], AssetRequirement, list[tuple[MediaCandidate, Any]]]] = []
        for segment, asset_requirement, options in pending:
            await progress(
                f"Selecting Asset for Visual {int(segment['index']) + 1} of {len(plan['segments'])}",
                {"segment_index": int(segment["index"]), "segment_count": len(plan["segments"])},
            )
            if reviewed is None:
                ordered = options
            else:
                by_candidate = {id(candidate): (candidate, source) for candidate, source in options}
                ordered = [by_candidate[id(item)] for item in reviewed.get(int(segment["index"]), [])]
            if asset_requirement.media_type == "video":
                ordered = prefer_covering_footage(
                    ordered,
                    float(segment["planned_duration_seconds"])
                    + 2.0
                    + (tail_seconds if int(segment["index"]) == last_index else 0.0),
                )
            selected, reason = None, ""
            for candidate, source in ordered:
                if isinstance(source, Asset):
                    if str(source.id) in used:
                        continue
                    selected, reason = (source, "reused")
                    break
                acquired = await acquire_asset(
                    asset_requirement,
                    providers=self.media_sources,
                    storage=self.storage,
                    assets=self.assets,
                    run_id=run_id,
                    media=self.media,
                    now=self.clock(),
                    progress=progress,
                    excluded_urls=frozenset(
                        asset.provenance.source_url
                        for asset in available
                        if str(asset.id) in used and asset.provenance.source_url
                    ),
                    max_image_bytes=int(configured.get("max_image_bytes", 20000000)),
                    max_video_bytes=int(configured.get("max_video_bytes", 300000000)),
                    excluded_asset_ids=frozenset(used),
                    candidates=[(candidate, source)],
                    **retry_policy,
                )
                if acquired is not None:
                    selected, reason = (acquired, "acquired" if reviewed is None else "reviewed")
                    if all(asset.id != acquired.id for asset in available):
                        available.append(acquired)
                    break
            if (
                selected is None
                and profile.visual_style.allow_generated_media
                and segment["requirement"].get("strategy") in {"generate_allowed", "reuse_first"}
                and not contains_named_person(list(asset_requirement.subjects))
                and asset_requirement.category not in {"map", "chart", "graphic", "text_card", "diagram"}
                and not re.search(
                    r"\b(?:maps?|charts?|diagrams?|infographics?)\b",
                    " ".join((asset_requirement.description, *asset_requirement.tags)),
                    re.IGNORECASE,
                )
            ):
                by_name = {provider.name: provider for provider in self.video_providers}

                async def generation_progress(
                    message: str, payload: dict[str, object], segment_index: int = int(segment["index"])
                ) -> None:
                    renew_generation_watchdog()
                    if payload.get("generation_phase") == "heartbeat":
                        return
                    await progress(
                        message, {**payload, "segment_index": segment_index, "segment_count": len(plan["segments"])}
                    )

                async def start_permit(provider: str, segment_index: int = int(segment["index"])) -> bool:
                    if provider != "wan_local":
                        await generation_progress(
                            f"Starting {provider} generation", {"provider": provider, "generation_phase": "started"}
                        )
                        return True
                    return await asyncio.to_thread(
                        self.runs.reserve_generation_start,
                        run_id,
                        provider=provider,
                        limit=int(
                            detail["settings_snapshot"].get("environment", {}).get("wan_max_generations_per_run", 2)
                        ),
                        segment_index=segment_index,
                        now=self.clock(),
                    )

                selected = await generate_video_asset(
                    VideoGenerationRequest(
                        prompt=(
                            segment["requirement"].get("generation_prompt")
                            or (
                                asset_requirement.description
                                + ". Naturalistic cinematic footage with continuous believable subject motion, "
                                "realistic textures, natural lighting and a steady camera."
                            )
                        ),
                        negative_prompt="people, faces, text, logos, watermarks, low quality, blurry",
                        width=profile.output.width,
                        height=max(profile.output.height, asset_requirement.min_height),
                        duration_seconds=float(segment["planned_duration_seconds"]),
                        seed=int.from_bytes(
                            hashlib.sha256(f"{run_id}:{attempt}:{segment['index']}".encode()).digest()[:4], "big"
                        ),
                    ),
                    providers=[
                        by_name[name]
                        for name in profile.generation.video_providers
                        if name in by_name
                        and (segment["requirement"].get("strategy") == "generate_allowed" or name == "wan_local")
                    ],
                    storage=self.storage,
                    assets=self.assets,
                    media=self.media,
                    now=self.clock(),
                    progress=generation_progress,
                    max_video_bytes=int(configured.get("max_video_bytes", 300000000)),
                    min_video_height_px=asset_requirement.min_height,
                    subjects=asset_requirement.subjects,
                    tags=asset_requirement.tags,
                    excluded_asset_ids=frozenset(used),
                    start_permit=start_permit,
                )
                if selected is not None:
                    reason = "generated"
                    segment["requirement"]["media_type"] = "video"
                    segment["requirement"]["category"] = "broll"
                    if all(asset.id != selected.id for asset in available):
                        available.append(selected)
            if selected is None and (
                segment["requirement"].get("fallback_graphics_spec") is not None
                and profile.visual_style.allow_generated_media
                and segment["requirement"].get("strategy") in {"generate_allowed", "reuse_first"}
                and not contains_named_person(list(asset_requirement.subjects))
            ):
                alternative = {**segment, "requirement": dict(segment["requirement"])}
                try:
                    spec = TypeAdapter(GraphicsSpec).validate_python(
                        alternative["requirement"]["fallback_graphics_spec"]
                    )
                    kind = graphics_kind(spec)
                    alternative["requirement"].update(
                        kind=kind,
                        graphics_spec=spec.model_dump(mode="json"),
                        fallback_graphics_spec=spec.model_dump(mode="json"),
                        media_type="video",
                        category="chart" if spec.template in {"comparison", "function_plot"} else "graphic",
                    )
                    await progress(
                        f"Visual {segment['index']}: choosing declared {kind} fallback",
                        {"segment_index": segment["index"], "fallback_choice": kind, "template": spec.template},
                    )
                    await self._select_graphic(
                        alternative,
                        profile,
                        package_id,
                        {
                            **configured,
                            "graphics_fps": detail["settings_snapshot"].get("environment", {}).get("graphics_fps", 30),
                        },
                        available,
                        used,
                        progress,
                        len(plan["segments"]),
                        declared_fallback=True,
                    )
                except ValidationError as exc:
                    raise StageFailure("unsupported_statement", "Invalid declared graphics alternative") from exc
                except (GraphicsError, ProviderError) as exc:
                    raise StageFailure(exc.code, str(exc)) from exc
                segment.update(alternative)
                segment["selection_reason"] = "graphics_fallback"
                segment["generated"] = False
                continue
            if selected is None:
                alternatives: list[tuple[MediaCandidate, Any]] = []
                seen_urls = {candidate.url for candidate, _ in options}
                for query in refined_media_queries(
                    asset_requirement,
                    segment["requirement"].get("search_queries", []),
                    narration=str(segment.get("narration_text", "")),
                    rotation=attempt - 1,
                ):
                    await progress(
                        f"Visual {segment['index']}: refined search for {query}",
                        {"segment_index": segment["index"], "fallback_choice": "refined_search", "search_query": query},
                    )
                    # On a revision Attempt a video Visual also searches stills: free video catalogues are
                    # sparse and the composer always moves stills (CF-REQ-266).
                    media_types = (
                        ("video", "image") if attempt > 1 and asset_requirement.media_type == "video" else (None,)
                    )
                    per_type: list[list[tuple[MediaCandidate, Any]]] = []
                    for media_type in media_types:
                        searched_requirement = replace(
                            asset_requirement, description=query, media_type=media_type or asset_requirement.media_type
                        )
                        found = await search_media_candidates(
                            searched_requirement,
                            providers=self.media_sources,
                            candidates_per_search=int(configured.get("candidates_per_search", 10)),
                            progress=progress,
                            **retry_policy,
                        )
                        eligible = rank_media_candidates(
                            replace(asset_requirement, media_type=searched_requirement.media_type),
                            [candidate for candidate, _ in found],
                        )
                        per_type.append([(candidate, source) for candidate, source in found if candidate in eligible])
                    for group in zip_longest(*per_type):
                        for item in group:
                            if item is not None and item[0].url not in seen_urls:
                                alternatives.append(item)
                                seen_urls.add(item[0].url)
                fallback_pending.append((segment, asset_requirement, alternatives[:review_limit]))
                continue
            segment["selected_asset_id"] = str(selected.id)
            segment["selection_reason"] = reason
            segment["generated"] = selected.provenance.origin == AssetOrigin.GENERATED
            used.add(str(selected.id))
            await progress(
                f"Visual {segment['index']}: {reason} {selected.media_type}",
                {"segment_index": segment["index"], "asset_id": str(selected.id), "selection_reason": reason},
            )
        fallback_reviewed: dict[int, list[MediaCandidate]] = {}
        if any(options for _, _, options in fallback_pending):
            context = await asyncio.to_thread(self.production.package_context, package_id)
            try:
                fallback_reviewed = await review_media_candidates(
                    self.llm,
                    [
                        SegmentCandidates(
                            int(segment["index"]),
                            str(segment["narration_text"]),
                            f"{segment['objective']}: {requirement.description}",
                            tuple(candidate for candidate, _ in options),
                        )
                        for segment, requirement, options in fallback_pending
                        if options
                    ],
                    story_title=str(context["title"]),
                    preview=self.candidate_preview,
                    max_images_per_request=int(configured.get("max_review_images_per_request", 10)),
                    fallback=_has_evaluation_fallback(detail),
                )
            except ProviderError as exc:
                raise StageFailure(exc.code, str(exc)) from exc
        missing_issues: list[Issue] = []
        reselected_segments = {
            int(action["refs"]["segment_index"])
            for action in state.get("pending_actions", [])
            if action.get("type") == ActionType.RESELECT_ASSET.value
            and isinstance(action.get("refs", {}).get("segment_index"), int)
        }
        for segment, asset_requirement, options in fallback_pending:
            accepted = fallback_reviewed.get(int(segment["index"]), [])
            selected = await acquire_asset(
                asset_requirement,
                providers=self.media_sources,
                storage=self.storage,
                assets=self.assets,
                run_id=run_id,
                media=self.media,
                now=self.clock(),
                progress=progress,
                excluded_urls=frozenset(
                    asset.provenance.source_url
                    for asset in available
                    if str(asset.id) in used and asset.provenance.source_url
                ),
                max_image_bytes=int(configured.get("max_image_bytes", 20000000)),
                max_video_bytes=int(configured.get("max_video_bytes", 300000000)),
                excluded_asset_ids=frozenset(used),
                candidates=[
                    (candidate, source) for item in accepted for candidate, source in options if candidate is item
                ],
                **retry_policy,
            )
            if selected is not None:
                segment["selected_asset_id"] = str(selected.id)
                segment["selection_reason"] = "refined_search"
                segment["generated"] = False
                used.add(str(selected.id))
                if all(asset.id != selected.id for asset in available):
                    available.append(selected)
                await progress(
                    f"Visual {segment['index']}: selected reviewed refined-search media",
                    {
                        "segment_index": segment["index"],
                        "asset_id": str(selected.id),
                        "selection_reason": "refined_search",
                    },
                )
                continue
            segment.pop("selected_asset_id", None)
            segment["selection_reason"] = "missing_reviewed_media"
            if int(segment["index"]) in reselected_segments:
                script_index = int(segment.get("script_segment_index", segment["index"]))
                message = (
                    f"Visual for script segment {script_index} ({segment.get('description', '')!r}) could not be "
                    "found in free stock media after a reselection; rewrite only that segment's media visual as an "
                    "ordinary photographable scene (place, crowd, building, object or activity) with new "
                    "search_queries, no on-screen text, tables or numbers. Keep all narration text unchanged."
                )
                code = "unsourceable_visual"
                refs = {"segment_index": int(segment["index"]), "script_segment_index": script_index}
            else:
                message = (
                    f"Visual {segment['index']} has no suitable reviewed licensed media; "
                    "reselect relevant media or supply an owner-reviewed photo. Plain-colour cards are not permitted."
                )
                code = "missing_asset"
                refs = {"segment_index": int(segment["index"])}
            missing_issues.append(
                Issue(
                    code=code,
                    severity=IssueSeverity.BLOCKING,
                    stage=Stage.SELECT_ASSETS,
                    message=message,
                    refs=refs,
                )
            )
            await progress(message, {"segment_index": segment["index"], "selection_reason": "missing_reviewed_media"})
        await asyncio.to_thread(self.production.save_visual_plan, package_id, plan["version"], plan)
        if missing_issues:
            return await self._persist_evaluation(
                build_evaluation(
                    EvaluationContext(run_id, None, attempt),
                    issues=missing_issues,
                    evaluator="deterministic_gate",
                    layer=EvaluationLayer.STAGE_GATE,
                )
            )
        clip_duration = float(sum(float(item["planned_duration_seconds"]) for item in plan["segments"]))
        music = select_music(available, profile.music, platforms=profile.platforms, clip_duration_seconds=clip_duration)
        artifact = {"music_asset_id": str(music.id) if music else None}
        await asyncio.to_thread(self.production.save_artifact, run_id, attempt, Stage.SELECT_ASSETS.value, artifact)
        if profile.music.enabled and music is None:
            await self._event(run_id, "no_music_available", "No eligible local music Asset; composing without music")
        return await self._persist_evaluation(self._gate_evaluation(run_id, attempt, Stage.SELECT_ASSETS, []))

    async def _select_person(
        self,
        segment: dict[str, Any],
        configured: dict[str, Any],
        available: list[Asset],
        used: set[str],
        progress: Callable[[str, dict[str, object]], Awaitable[None]],
        people: dict[str, PersonPortraits | None],
        occurrences: dict[str, int],
        retry_policy: dict[str, Any],
        run_id: UUID,
    ) -> bool:
        """Show a mentioned public figure through a Wikidata-bound licensed portrait (CF-REQ-268)."""
        source = self.person_portraits
        name = str(segment["requirement"]["person"]["name"])
        if source is None:
            return False
        key = name.casefold()
        if key not in people:
            try:
                people[key] = await source.find_person(
                    name, min_short_side_px=int(configured.get("min_portrait_short_side_px", 480))
                )
            except ProviderError as exc:
                await progress(
                    f"Visual {segment['index']}: could not verify {name} ({exc.code}); keeping the original shot",
                    {"segment_index": segment["index"], "error_code": exc.code},
                )
                people[key] = None
        resolved = people[key]
        if resolved is None or not resolved.candidates:
            await progress(
                f"Visual {segment['index']}: no verified licensed portrait of {name}; keeping the original shot",
                {"segment_index": segment["index"], "person": name},
            )
            return False
        occurrence = occurrences.get(key, 0)
        occurrences[key] = occurrence + 1
        count = len(resolved.candidates)
        ordered = [resolved.candidates[(occurrence + offset) % count] for offset in range(count)]
        requirement = AssetRequirement(
            media_type="image",
            category="person",
            description=f"Portrait photograph of {resolved.name}",
            subjects=(resolved.name,),
            tags=(resolved.name, "person", resolved.identity_ref),
            min_width=int(configured.get("min_portrait_short_side_px", 480)),
            min_height=int(configured.get("min_portrait_short_side_px", 480)),
        )
        selected: Asset | None = None
        for candidate in ordered:
            # Portraits may repeat within a Run and ignore reuse cooldown: identity, not variety, is the point.
            selected = next(
                (
                    asset
                    for asset in available
                    if asset.provenance.source_url == candidate.url
                    and asset.status.value == "active"
                    and (
                        asset.provenance.origin != AssetOrigin.EXTERNAL
                        or asset.storage_key.startswith(f"assets/external-runs/{run_id}/")
                    )
                ),
                None,
            )
            if selected is not None and not await self.storage.exists(selected.storage_key):
                selected = None
            if selected is None:
                selected = await acquire_asset(
                    requirement,
                    providers=(source,),
                    storage=self.storage,
                    assets=self.assets,
                    run_id=run_id,
                    media=self.media,
                    now=self.clock(),
                    progress=progress,
                    max_image_bytes=int(configured.get("max_image_bytes", 20000000)),
                    candidates=[(candidate, source)],
                    **retry_policy,
                )
                if selected is not None and all(asset.id != selected.id for asset in available):
                    available.append(selected)
            if selected is not None:
                break
        if selected is None:
            await progress(
                f"Visual {segment['index']}: portrait of {name} could not be imported; keeping the original shot",
                {"segment_index": segment["index"], "person": name},
            )
            return False
        segment["selected_asset_id"] = str(selected.id)
        segment["selection_reason"] = "person_portrait"
        segment["generated"] = False
        segment["identity"] = {
            "name": resolved.name,
            "ref": resolved.identity_ref,
            "url": resolved.identity_url,
            "source_url": selected.provenance.source_url,
        }
        used.add(str(selected.id))
        await progress(
            f"Visual {segment['index']}: showing {resolved.name} ({resolved.identity_ref})",
            {
                "segment_index": segment["index"],
                "asset_id": str(selected.id),
                "selection_reason": "person_portrait",
                "identity_ref": resolved.identity_ref,
            },
        )
        return True

    async def _select_graphic(
        self,
        segment: dict[str, Any],
        profile: ContentProfile,
        package_id: UUID,
        configured: dict[str, Any],
        available: list[Asset],
        used: set[str],
        progress: Callable[[str, dict[str, object]], Awaitable[None]],
        segment_count: int,
        *,
        declared_fallback: bool = False,
    ) -> None:
        requirement = segment["requirement"]
        kind = requirement["kind"]
        try:
            spec = TypeAdapter(GraphicsSpec).validate_python(requirement.get("graphics_spec"))
        except ValidationError as exc:
            code = (
                "unsupported_graphics_template"
                if any(error["type"] in {"union_tag_invalid", "union_tag_not_found"} for error in exc.errors())
                else "unsupported_statement"
            )
            raise GraphicsError(code, "Invalid bounded graphics input") from exc
        validate_graphics_kind(kind, spec)
        context = await asyncio.to_thread(self.production.package_context, package_id)
        validate_graphics_claims(spec, context["claims"])
        normalized = spec.model_dump(mode="json")
        eligible = [
            asset
            for asset in available
            if asset.provenance.origin == AssetOrigin.RENDERED
            and asset.provenance.generation
            and asset.provenance.generation.get("parameters", {}).get("graphics_spec") == normalized
            and asset.provenance.generation.get("parameters", {}).get("template_version") == "1"
            and asset.provenance.generation.get("parameters", {}).get("fps") == configured.get("graphics_fps", 30)
            and asset.width == profile.output.width
            and asset.height == profile.output.height
            and asset.duration_seconds is not None
            and reusable_render_duration(
                spec,
                asset.duration_seconds,
                float(segment["planned_duration_seconds"]),
                1 / int(configured.get("graphics_fps", 30)),
            )
        ]
        eligible.sort(key=lambda asset: asset.duration_seconds or 0.0)
        match = choose_reusable_asset(
            AssetRequirement(
                media_type="video",
                category=requirement["category"],
                description=requirement["description"],
                subjects=tuple(requirement["subjects"]),
                tags=tuple(requirement["tags"]),
                min_width=profile.output.width,
                min_height=profile.output.height,
            ),
            eligible,
            now=self.clock(),
            cooldown_days=int(configured.get("reuse_cooldown_days", 3)),
            minimum_match=0,
            already_used=frozenset(used),
        )
        if match is not None and await self.storage.exists(match.asset.storage_key):
            selected, reason = match.asset, "reused"
        else:
            if (
                not profile.visual_style.allow_generated_media
                or (
                    requirement.get("strategy") != "generate_allowed"
                    and not (declared_fallback and requirement.get("strategy") == "reuse_first")
                )
                or contains_named_person(list(requirement["subjects"]))
            ):
                raise GraphicsError(
                    "unsupported_statement", "New graphics require generated-media permission and no person depiction"
                )
            provider = graphics_provider(kind, self.graphics_providers)

            async def rendering_progress(message: str, payload: dict[str, object]) -> None:
                renew_generation_watchdog()
                if payload.get("generation_phase") != "heartbeat":
                    await progress(
                        message,
                        {
                            **payload,
                            "segment_index": int(segment["index"]),
                            "segment_count": segment_count,
                            "renderer": provider.name,
                            "template": spec.template,
                        },
                    )

            selected = await generate_video_asset(
                VideoGenerationRequest(
                    prompt=requirement["description"],
                    negative_prompt="",
                    width=profile.output.width,
                    height=profile.output.height,
                    duration_seconds=float(segment["planned_duration_seconds"]),
                    seed=0,
                    graphics_spec=spec,
                ),
                providers=[provider],
                storage=self.storage,
                assets=self.assets,
                media=self.media,
                now=self.clock(),
                progress=rendering_progress,
                max_video_bytes=int(configured.get("max_video_bytes", 300000000)),
                min_video_height_px=int(configured.get("min_video_height_px", 720)),
                subjects=requirement["subjects"],
                tags=requirement["tags"],
                excluded_asset_ids=frozenset(used),
            )
            if selected is None:
                raise GraphicsError("graphics_render_failed", "Graphics output was not imported")
            reason = "rendered"
            available.append(selected)
        used.add(str(selected.id))
        segment["selected_asset_id"] = str(selected.id)
        segment["selection_reason"] = reason
        segment["motion"] = "none"

    async def generate_narration(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, profile = await self._run_context(state)
        existing = await asyncio.to_thread(self.production.artifact, run_id, attempt, Stage.GENERATE_NARRATION.value)
        if existing is not None:
            return {}
        script = await asyncio.to_thread(self.production.current_script, _required_uuid(state, "story_package_id"))
        segments = tuple(item["text"] for item in script["segments"])
        composition = detail["settings_snapshot"].get("composition", {})
        try:
            result = await generate_narration(
                script_segments=segments,
                language=profile.language,
                voice_id=profile.voice.provider_voice_id,
                speaking_rate=profile.voice.speaking_rate,
                min_seconds=profile.duration.min_seconds,
                max_seconds=profile.duration.max_seconds,
                lead_in_seconds=float(composition.get("lead_in_seconds", 0.3)),
                tail_seconds=float(composition.get("tail_seconds", 1.0)),
                speaking_words_per_minute=profile.voice.words_per_minute,
                tts=self.tts,
                storage=self.storage,
                force_refresh=any(
                    action.get("type") == "regenerate_narration" for action in state.get("pending_actions", [])
                ),
            )
            measured = await self.media.validate_narration(self.storage.local_path(result.narration_key))
        except NarrationDurationGateError as exc:
            previous_words = sum(len(segment.split()) for segment in segments)
            target_words = max(1, previous_words + exc.word_delta * exc.action_word_count)
            evaluation = self._gate_evaluation(
                run_id,
                attempt,
                Stage.GENERATE_NARRATION,
                [exc.code],
                instructions="".join(
                    [
                        f"{exc}",
                        ". Previous script had ",
                        f"{previous_words}",
                        " words; target about ",
                        f"{target_words}",
                        " words. Change the length only by adding or removing accepted facts or necessary "
                        "context, never with filler adverbs (notably, remarkably, impressively, truly).",
                    ]
                ),
                refs={"target_word_count": target_words, "previous_word_count": previous_words},
            )
            return await self._persist_evaluation(evaluation)

        except (MediaProcessError, ValueError):
            evaluation = self._gate_evaluation(run_id, attempt, Stage.GENERATE_NARRATION, ["narration_invalid"])
            return await self._persist_evaluation(evaluation)
        audio_path = self.storage.local_path(result.narration_key)
        text_hash = hashlib.sha256("\n".join(segments).encode()).hexdigest()
        asset = Asset(
            media_type="audio",
            category="narration",
            storage_key=result.narration_key,
            sha256=result.narration_sha256,
            mime_type="audio/wav",
            size_bytes=audio_path.stat().st_size,
            duration_seconds=float(measured["duration_seconds"]),
            description="Synthetic narration for one Clip attempt",
            provenance=Provenance(
                origin=AssetOrigin.GENERATED,
                provider=self.tts.name,
                license="private-production",
                generation={
                    "provider": self.tts.name,
                    "voice_id": profile.voice.provider_voice_id,
                    "text_hash": text_hash,
                },
                acquired_at=self.clock(),
            ),
            reusable=False,
            created_at=self.clock(),
        )
        stored = await asyncio.to_thread(self.assets.save, asset)
        artifact = {
            "asset_id": str(stored.id),
            "narration_key": result.narration_key,
            "sha256": result.narration_sha256,
            "duration_seconds": result.narration_duration_seconds,
            "text_hash": text_hash,
        }
        await asyncio.to_thread(
            self.production.save_artifact, run_id, attempt, Stage.GENERATE_NARRATION.value, artifact
        )
        evaluation = self._gate_evaluation(run_id, attempt, Stage.GENERATE_NARRATION, [])
        return await self._persist_evaluation(evaluation)

    async def transcribe_narration(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, _, profile = await self._run_context(state)
        narration = await self._artifact(run_id, attempt, Stage.GENERATE_NARRATION)
        previous = await asyncio.to_thread(self.production.latest_artifact, run_id, Stage.TRANSCRIBE_NARRATION.value)
        if previous is not None and previous.get("narration_sha256") == narration["sha256"]:
            await asyncio.to_thread(
                self.production.save_artifact, run_id, attempt, Stage.TRANSCRIBE_NARRATION.value, previous
            )
            return {}
        script = await asyncio.to_thread(self.production.current_script, _required_uuid(state, "story_package_id"))
        alignment = await transcribe_narration(
            narration_key=narration["narration_key"],
            script_segments=tuple(item["text"] for item in script["segments"]),
            language=profile.language,
            transcription=self.transcription,
            storage=self.storage,
        )
        artifact = {
            "narration_sha256": narration["sha256"],
            "wer": alignment.wer,
            "words": [asdict(word) for word in alignment.words],
        }
        await asyncio.to_thread(
            self.production.save_artifact, run_id, attempt, Stage.TRANSCRIBE_NARRATION.value, artifact
        )
        return {}

    async def build_captions(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, _ = await self._run_context(state)
        transcription = await self._artifact(run_id, attempt, Stage.TRANSCRIBE_NARRATION)
        font_file = Path(detail["settings_snapshot"].get("captions", {}).get("font_file", "NotoSans-Bold.ttf"))
        if not await asyncio.to_thread(font_file.is_file):
            raise StageFailure("caption_font_unavailable", f"Configured caption font is missing: {font_file}")
        alignment = AlignmentResult(
            tuple(AlignedWord(**word) for word in transcription["words"]), float(transcription["wer"])
        )
        caption_key, track = await build_captions(
            run_id=run_id,
            attempt=attempt,
            alignment=alignment,
            storage=self.storage,
            font_file=font_file,
            lead_in_seconds=float(detail["settings_snapshot"].get("composition", {}).get("lead_in_seconds", 0.3)),
        )
        artifact = {"caption_key": caption_key, "cues": [asdict(cue) for cue in track.cues]}
        await asyncio.to_thread(self.production.save_artifact, run_id, attempt, Stage.BUILD_CAPTIONS.value, artifact)
        return {}

    async def compose_clip(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, profile = await self._run_context(state)
        package_id = _required_uuid(state, "story_package_id")
        plan = await asyncio.to_thread(self.production.current_visual_plan, package_id)
        narration = await self._artifact(run_id, attempt, Stage.GENERATE_NARRATION)
        transcription = await self._artifact(run_id, attempt, Stage.TRANSCRIBE_NARRATION)
        captions = await self._artifact(run_id, attempt, Stage.BUILD_CAPTIONS)
        composition = detail["settings_snapshot"].get("composition", {})
        words = tuple(AlignedWord(**word) for word in transcription["words"])
        plan["segments"] = reconcile_visual_timing(
            plan["segments"],
            words,
            narration_duration_seconds=float(narration["duration_seconds"]),
            lead_in_seconds=float(composition.get("lead_in_seconds", 0.3)),
            tail_seconds=float(composition.get("tail_seconds", 1.0)),
            max_segment_seconds=float(detail["settings_snapshot"].get("visual", {}).get("max_segment_seconds", 8.0)),
            min_segment_seconds=float(detail["settings_snapshot"].get("visual", {}).get("min_segment_seconds", 1.5)),
        )
        selected: list[tuple[dict[str, Any], Asset]] = []
        issues: list[str] = []
        short_assets: dict[int, str] = {}
        for segment in plan["segments"]:
            asset_id = segment.get("selected_asset_id")
            asset = await asyncio.to_thread(self.assets.get, UUID(asset_id)) if asset_id else None
            if (
                asset is None
                or asset.category == "title_card"
                or asset.status.value != "active"
                or (not await self.storage.exists(asset.storage_key))
            ):
                issues.append("missing_asset")
                continue
            duration = float(segment["end_seconds"]) - float(segment["start_seconds"])
            visual = detail["settings_snapshot"].get("visual", {})
            if duration < float(visual.get("min_segment_seconds", 1.5)):
                issues.append("segment_too_short")
            if duration > float(visual.get("max_segment_seconds", 8.0)):
                issues.append("segment_too_long")
            if asset.media_type == "video" and short_footage(
                asset.duration_seconds,
                offset_seconds=float(segment.get("source_offset_seconds", 0.0)),
                shown_seconds=duration,
            ):
                short_assets.setdefault(int(segment.get("plan_segment_index", segment["index"])), str(asset.id))
            selected.append((segment, asset))
        gate = self._gate_evaluation(run_id, attempt, Stage.COMPOSE_CLIP, list(dict.fromkeys(issues)))
        if gate.passed and short_assets:
            gate = build_evaluation(
                EvaluationContext(run_id, None, attempt),
                issues=[
                    Issue(
                        code="asset_too_short",
                        severity=IssueSeverity.BLOCKING,
                        stage=Stage.COMPOSE_CLIP,
                        message=(
                            f"Visual {index + 1} footage is too short to fill its segment without replaying it; "
                            "select a different, longer clip for this segment."
                        ),
                        refs={"segment_index": index, "rejected_asset_id": asset_id},
                    )
                    for index, asset_id in sorted(short_assets.items())
                ],
                evaluator="deterministic_gate",
                layer=EvaluationLayer.STAGE_GATE,
            )
        if not gate.passed:
            return await self._persist_evaluation(gate)
        motions = choose_shot_motions(
            [
                ShotMedia(
                    media_type=asset.media_type,
                    category=asset.category,
                    width=asset.width or profile.output.width,
                    height=asset.height or profile.output.height,
                    requested_motion=str(segment.get("motion", "none")),
                    asset_id=str(asset.id),
                    script_segment_index=segment.get("script_segment_index"),
                    requested_reason=str(segment.get("motion_reason", "")),
                )
                for segment, asset in selected
            ]
        )
        for (segment, _), motion in zip(selected, motions, strict=True):
            segment["motion"] = motion.motion
            segment["motion_reason"] = motion.reason
        selection = await self._artifact(run_id, attempt, Stage.SELECT_ASSETS)
        music = (
            await asyncio.to_thread(self.assets.get, UUID(selection["music_asset_id"]))
            if selection.get("music_asset_id")
            else None
        )
        output_path = self.storage.work_dir(run_id) / f"attempt-{attempt}" / "clip.tmp.mp4"
        script_value = await asyncio.to_thread(self.production.current_script, package_id)
        font_file = Path(detail["settings_snapshot"].get("captions", {}).get("font_file", "NotoSans-Bold.ttf"))
        clip_duration = (
            float(composition.get("lead_in_seconds", 0.3))
            + float(narration["duration_seconds"])
            + float(composition.get("tail_seconds", 1.0))
        )
        overlays, overlay_metadata = await self._editorial_overlays(
            run_id,
            attempt,
            package_id,
            script_value,
            plan["segments"],
            font_file,
            profile,
            clip_duration - 3 if composition.get("end_card_file") else clip_duration,
        )
        sound_effects = await self._sound_cues(overlays, clip_duration)
        identity_overlays, identity_metadata = await self._identity_overlays(
            run_id, attempt, package_id, script_value, font_file, profile, clip_duration, composition
        )
        overlays.extend(identity_overlays)
        end_card_path = None
        end_card_sha256 = None
        if composition.get("end_card_file"):
            try:
                if composition.get("branding_directory"):
                    await self.media.prepare_profile_outro(Path(composition["branding_directory"]), font_file)
                end_card_path, end_card_sha256 = await freeze_end_card(
                    Path(str(composition["end_card_file"])),
                    storage=self.storage,
                    runner=self.media,
                    key=f"work/{run_id}/attempt-{attempt}/end-card.mp4",
                )
            except (OSError, ValueError, MediaProcessError) as exc:
                raise StageFailure(
                    "composition_failed", f"Configured end card is unavailable or invalid: {exc}"
                ) from exc
        spec = CompositionSpec(
            segments=tuple(
                (
                    VisualInput(
                        self.storage.local_path(asset.storage_key),
                        "video" if asset.media_type == "video" else "image",
                        asset.width or profile.output.width,
                        asset.height or profile.output.height,
                        float(segment["end_seconds"]) - float(segment["start_seconds"]),
                        segment["motion"],
                        segment["transition_in"],
                        source_label=segment.get("source_label"),
                        source_offset_seconds=(
                            float(segment.get("source_offset_seconds", 0.0)) if asset.media_type == "video" else 0.0
                        ),
                    )
                    for segment, asset in selected
                )
            ),
            narration_path=self.storage.local_path(narration["narration_key"]),
            caption_file=self.storage.local_path(captions["caption_key"]),
            output_path=output_path,
            narration_duration_seconds=float(narration["duration_seconds"]),
            music_path=self.storage.local_path(music.storage_key) if music else None,
            narration_word_spans=tuple((word.start_seconds, word.end_seconds) for word in words),
            width=profile.output.width,
            height=profile.output.height,
            fps=profile.output.fps,
            lead_in_seconds=float(composition.get("lead_in_seconds", 0.3)),
            tail_seconds=float(composition.get("tail_seconds", 1.0)),
            transition_seconds=float(composition.get("transition_seconds", 0.4)),
            narration_loudness_lufs=float(composition.get("narration_loudness_lufs", -14)),
            video_codec=str(composition.get("video_codec", "libx264")),
            crf=int(composition.get("crf", 23)),
            preset=str(composition.get("preset", "medium")),
            pixel_format=str(composition.get("pixel_format", "yuv420p")),
            audio_codec=str(composition.get("audio_codec", "aac")),
            audio_bitrate=str(composition.get("audio_bitrate", "128k")),
            audio_sample_rate=int(composition.get("audio_sample_rate", 48000)),
            music_ducked_level_db=profile.music.ducked_level_db,
            music_unducked_level_db=profile.music.unducked_level_db,
            motion_intensity=profile.visual_style.motion_intensity,
            fonts_dir=font_file.parent,
            overlays=tuple(overlays),
            sound_effects=sound_effects,
            end_card_path=end_card_path,
            end_card_sha256=end_card_sha256,
        )
        try:
            rendered = await render_clip(
                spec, storage=self.storage, runner=self.media, final_key=f"clips/{run_id}/attempt-{attempt}.mp4"
            )
        except MediaProcessError as exc:
            raise StageFailure("composition_failed", exc.stderr_tail or str(exc)) from exc
        caption_package = await asyncio.to_thread(
            self.production.package_context, _required_uuid(state, "story_package_id")
        )
        package_summary = caption_package.get("summary")
        package_attributions = caption_package.get("source_attributions", [])
        metadata = {
            "narration": narration,
            "word_timings": transcription["words"],
            "wer": transcription["wer"],
            "captions": captions,
            "music_asset_id": str(music.id) if music else None,
            "visual_segments": plan["segments"],
            "editorial_overlays": overlay_metadata,
            "identity_overlays": identity_metadata,
            "end_card": (
                {"path": str(end_card_path), "sha256": end_card_sha256, "duration_seconds": 3}
                if end_card_path is not None
                else None
            ),
            "sound_effects": [asdict(cue) | {"path": str(cue.path)} for cue in sound_effects],
            "social_metadata": {
                **script_value["social_metadata"],
                "description": _descriptive_caption(
                    str(script_value["social_metadata"].get("description", "")), str(package_summary or "")
                ),
                "source_attributions": list(package_attributions),
                "asset_attributions": list(
                    dict.fromkeys(
                        asset.provenance.attribution_text
                        for _, asset in selected
                        if asset.provenance.attribution_required and asset.provenance.attribution_text
                    )
                ),
                "contains_synthetic_media": any(
                    asset.provenance.origin == AssetOrigin.GENERATED for _, asset in selected
                ),
                "synthetic_voice": True,
            },
        }
        usages = [
            {
                "asset_id": str(asset.id),
                "visual_segment_index": segment["index"],
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
            }
            for segment, asset in selected
        ]
        clip_id = await asyncio.to_thread(
            self.production.save_clip,
            run_id=run_id,
            story_package_id=package_id,
            story_package_version=int(plan["version"]),
            attempt=attempt,
            rendered=rendered,
            composition_spec_hash=spec.sha256(),
            metadata=metadata,
            asset_usages=usages,
            now=self.clock(),
        )
        await asyncio.to_thread(self.production.save_visual_plan, package_id, plan["version"], plan)
        result = await self._persist_evaluation(gate)
        result["clip_id"] = str(clip_id)
        return result

    async def validate_clip(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, profile = await self._run_context(state)
        clip_id = _required_uuid(state, "clip_id")
        clip = await asyncio.to_thread(self.production.clip, clip_id)
        context = EvaluationContext(run_id, clip_id, attempt)
        technical = await validate_media(
            context,
            self.storage.local_path(clip["storage_key"]),
            runner=self.media,
            spec=MediaValidationSpec(profile.output.width, profile.output.height, profile.output.fps),
        )
        duration = validate_duration(
            context,
            duration_seconds=float(clip["duration_seconds"]),
            min_seconds=profile.duration.min_seconds,
            max_seconds=profile.duration.max_seconds,
        )
        issues = [*technical.issues, *duration.issues]
        maximum_wer = float(detail["settings_snapshot"].get("evaluation", {}).get("max_narration_wer", 0.15))
        wer = float(clip["metadata"].get("wer", 1.0))
        if wer > maximum_wer:
            issues.append(
                Issue(
                    code="narration_mismatch",
                    severity=IssueSeverity.BLOCKING,
                    stage=Stage.VALIDATE_CLIP,
                    message=f"Narration WER {wer:.3f} exceeds {maximum_wer:.3f}",
                    evidence={"wer": wer, "maximum": maximum_wer},
                )
            )
        evaluation = build_evaluation(
            context, issues=issues, metrics={**technical.metrics, **duration.metrics, "wer": wer}
        )
        await asyncio.to_thread(
            self.production.set_clip_status, clip_id, ClipStatus.RENDERED if evaluation.passed else ClipStatus.REJECTED
        )
        return await self._persist_evaluation(evaluation)

    async def evaluate_clip(self, state: WorkflowState) -> dict[str, Any]:
        run_id, attempt, detail, _ = await self._run_context(state)
        clip_id = _required_uuid(state, "clip_id")
        clip = await asyncio.to_thread(self.production.clip, clip_id)
        configured = detail["settings_snapshot"].get("evaluation", {})
        context = EvaluationContext(run_id, clip_id, attempt)
        if not bool(configured.get("semantic_enabled", True)):
            await self._event(run_id, "semantic_evaluation_skipped", "Semantic evaluation is disabled")
            evaluation = build_evaluation(
                context, issues=[], evaluator="semantic_disabled", layer=EvaluationLayer.SEMANTIC
            )
        else:
            frames: list[ImageInput] = []
            if bool(configured.get("visual_enabled", True)):
                frame_specs = representative_frames(
                    clip["metadata"]["visual_segments"], int(configured.get("visual_frame_count", 5))
                )
                for frame in frame_specs:
                    image = await self.media.extract_frame(
                        self.storage.local_path(clip["storage_key"]),
                        frame["timestamp_seconds"],
                        int(configured.get("visual_frame_width_px", 360)),
                    )
                    frames.append(ImageInput(image, "image/jpeg", frame))
            package = await asyncio.to_thread(
                self.production.package_context, _required_uuid(state, "story_package_id")
            )
            production_data = {
                "story": {"title": package["title"], "summary": package["summary"]},
                "verified_claims": [claim.model_dump(mode="json") for claim in package["claims"]],
                "source_attributions": package.get("source_attributions", []),
                "script": await asyncio.to_thread(
                    self.production.current_script, _required_uuid(state, "story_package_id")
                ),
                "visual_plan": clip["metadata"]["visual_segments"],
                "captions": clip["metadata"]["captions"],
                "social_metadata": clip["metadata"]["social_metadata"],
                "wer": clip["metadata"]["wer"],
                "frames": [item.metadata for item in frames],
            }
            environment = detail["settings_snapshot"].get("environment", {})
            primary_model = environment.get("llm_model_evaluation") or environment.get("llm_model")
            fallback_model = environment.get("llm_model_evaluation_fallback")
            model_role: LLMModelRole = "evaluation"
            while True:
                try:
                    evaluation = await evaluate_semantics(
                        self.llm,
                        context,
                        production_data=production_data,
                        frames=frames or None,
                        model_role=model_role,
                    )
                    break
                except ProviderError as exc:
                    if (
                        exc.code in EVALUATION_FALLBACK_ERRORS
                        and model_role == "evaluation"
                        and fallback_model
                        and fallback_model != primary_model
                    ):
                        # Free providers moderate news imagery with an opaque, input-deterministic 400 (CF-REQ-405).
                        model_role = "evaluation_fallback"
                        await self._event(
                            run_id,
                            "evaluation_model_fallback",
                            f"Evaluation model {primary_model} failed the request ({exc.code}); "
                            f"retrying once with {fallback_model}",
                        )
                        continue
                    if exc.code != "image_limit" or len(frames) <= 1:
                        raise StageFailure("llm_unavailable", str(exc)) from exc
                # The routed free vision model accepts fewer images per prompt; keep evenly spaced frames.
                frames = _fewer_frames(frames)
                production_data["frames"] = [item.metadata for item in frames]
                await self._event(
                    run_id,
                    "evaluation_image_limit",
                    f"Evaluation model accepts fewer images; retrying with {len(frames)}",
                )
        await asyncio.to_thread(
            self.production.set_clip_status, clip_id, ClipStatus.APPROVED if evaluation.passed else ClipStatus.REJECTED
        )
        result = await self._persist_evaluation(evaluation)
        if evaluation.passed:
            await self.cleanup_run(run_id)
        return result

    async def cleanup_run(self, run_id: UUID) -> None:
        try:
            await retire_run_external_assets(run_id, assets=self.assets, storage=self.storage)
        except OSError:
            logger.exception("External input cleanup failed for Run %s", run_id)
            await self._event(
                run_id,
                "asset_cleanup_failed",
                "External inputs were retired but file deletion failed; check server logs",
            )

    async def plan_retry(self, state: WorkflowState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        detail = await asyncio.to_thread(self.runs.get, run_id)
        ids = state.get("last_evaluation_ids", [])
        evaluation = await asyncio.to_thread(self.evaluations.get, UUID(ids[-1])) if ids else None
        if evaluation is None:
            raise StageFailure("internal_error", "Retry planning requires a persisted Evaluation")
        maximum = int(detail["settings_snapshot"].get("workflow", {}).get("max_revision_retries", 3))
        retry = plan_retry(
            evaluation, revision_retries_used=int(detail["revision_retries_used"]), max_revision_retries=maximum
        )
        if retry.failure_code:
            raise StageFailure(retry.failure_code, "Clip evaluation did not produce an approved result")
        await asyncio.to_thread(
            self.runs.apply_retry,
            run_id,
            attempt=retry.attempt,
            revision_retries_used=retry.revision_retries_used,
            reentry_stage=retry.reentry_stage.value if retry.reentry_stage else None,
            action_types=tuple(str(action["type"]) for action in retry.pending_actions),
            retries_remaining=maximum - retry.revision_retries_used,
        )
        return {
            "attempt": retry.attempt,
            "revision_retries_used": retry.revision_retries_used,
            "pending_actions": list(retry.pending_actions),
            "affected_segments": list(retry.affected_segments),
            "reentry_stage": retry.reentry_stage.value if retry.reentry_stage else None,
        }

    async def _run_context(self, state: WorkflowState) -> tuple[UUID, int, dict[str, Any], ContentProfile]:
        run_id = UUID(state["run_id"])
        detail = await asyncio.to_thread(self.runs.get, run_id)
        return (
            run_id,
            int(state.get("attempt", detail["attempt"])),
            detail,
            ContentProfile.model_validate(detail["profile_snapshot"]),
        )

    async def _artifact(self, run_id: UUID, attempt: int, stage: Stage) -> dict[str, Any]:
        value = await asyncio.to_thread(self.production.artifact, run_id, attempt, stage.value)
        if value is None:
            value = await asyncio.to_thread(self.production.latest_artifact, run_id, stage.value)
        if value is None:
            raise StageFailure("internal_error", f"Persisted output for {stage.value} is missing")
        return value

    def _gate_evaluation(
        self,
        run_id: UUID,
        attempt: int,
        stage: Stage,
        codes: list[str],
        *,
        instructions: str | None = None,
        refs: dict[str, Any] | None = None,
    ) -> Evaluation:
        issues = [
            Issue(
                code=code,
                severity=IssueSeverity.BLOCKING,
                stage=stage,
                message=instructions or f"{stage.value} gate failed: {code}",
                refs=refs or {},
            )
            for code in codes
        ]
        return build_evaluation(
            EvaluationContext(run_id, None, attempt),
            issues=issues,
            evaluator="deterministic_gate",
            layer=EvaluationLayer.STAGE_GATE,
        )

    async def _persist_evaluation(self, evaluation: Evaluation) -> dict[str, Any]:
        await asyncio.to_thread(self.evaluations.save, evaluation)
        return {"last_evaluation_ids": [str(evaluation.id)]}

    async def _identity_overlays(
        self,
        run_id: UUID,
        attempt: int,
        package_id: UUID,
        script: dict[str, Any],
        font_file: Path,
        profile: ContentProfile,
        duration: float,
        settings: dict[str, Any],
    ) -> tuple[list[OverlayInput], list[dict[str, Any]]]:
        scale = profile.output.width / 720
        margin = round(24 * scale)
        logo = Path(str(settings.get("logo_file", "branding/inpulso_world/logo_letters.png")))
        opacity = float(settings.get("logo_opacity", 0.7))
        try:
            content, width, height = await asyncio.to_thread(render_brand_mark, logo, round(112 * scale), opacity)
        except (OSError, ValueError) as exc:
            raise StageFailure(
                "composition_failed", f"Configured logo is unavailable or invalid: {logo}: {exc}"
            ) from exc
        if width + 2 * margin > profile.output.width or height + 2 * margin > profile.output.height:
            raise StageFailure("composition_failed", "Configured logo cannot fit within the output frame")
        key = f"work/{run_id}/attempt-{attempt}/identity-logo.png"
        await self.storage.put_bytes(key, content)
        overlays = [
            OverlayInput(
                self.storage.local_path(key),
                0,
                duration,
                profile.output.width - margin - width,
                margin,
                width,
                height,
                0,
                hashlib.sha256(content).hexdigest(),
            )
        ]
        recorded: list[dict[str, Any]] = [
            asdict(overlays[0])
            | {"path": str(overlays[0].path), "kind": "logo", "sha256": hashlib.sha256(content).hexdigest()}
        ]
        context = await asyncio.to_thread(self.production.package_context, package_id)
        cited_claims = {UUID(str(value)) for segment in script["segments"] for value in segment["claim_ids"]}
        sources = {
            evidence.source_id
            for claim in context["claims"]
            if claim.id in cited_claims
            for evidence in claim.evidence
            if evidence.verified
        }
        dated = {
            source: timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp
            for source, timestamp in context.get("source_publications", {}).items()
            if source in sources and timestamp is not None
        }
        if dated:
            latest = max(dated.values())
            try:
                text, graphic = await asyncio.to_thread(
                    render_news_date, latest, profile.schedule.timezone, font_file, profile.output.width
                )
            except (OSError, ValueError) as exc:
                raise StageFailure("composition_failed", f"News-date label could not be rendered: {exc}") from exc
            if graphic.x + graphic.width >= overlays[0].x or graphic.y + graphic.height > round(
                112 * profile.output.height / 1280
            ):
                raise StageFailure(
                    "composition_failed", "News-date label cannot fit outside the logo and editorial region"
                )
            key = f"work/{run_id}/attempt-{attempt}/identity-date.png"
            await self.storage.put_bytes(key, graphic.png_bytes)
            overlay = OverlayInput(
                self.storage.local_path(key),
                0,
                duration,
                graphic.x,
                graphic.y,
                graphic.width,
                graphic.height,
                0,
                graphic.sha256,
            )
            overlays.append(overlay)
            recorded.append(
                asdict(overlay)
                | {
                    "path": str(overlay.path),
                    "kind": "news_date",
                    "text": text,
                    "published_at": latest.isoformat(),
                    "source_ids": sorted(str(source) for source, timestamp in dated.items() if timestamp == latest),
                    "sha256": graphic.sha256,
                }
            )
        else:
            await self._event(
                run_id, "warning", "News date omitted: cited verified Sources have no known publication timestamp"
            )

        if settings.get("ai_disclosure_tag", True):
            ai_tag_text = str(settings.get("ai_disclosure_text", "AI Generated"))
            try:
                tag_label, ai_graphic = await asyncio.to_thread(
                    render_ai_disclosure_tag,
                    font_file,
                    profile.output.width,
                    profile.output.height,
                    ai_tag_text,
                )
                ai_key = f"work/{run_id}/attempt-{attempt}/identity-ai-tag.png"
                await self.storage.put_bytes(ai_key, ai_graphic.png_bytes)
                ai_overlay = OverlayInput(
                    self.storage.local_path(ai_key),
                    0,
                    duration,
                    ai_graphic.x,
                    ai_graphic.y,
                    ai_graphic.width,
                    ai_graphic.height,
                    0,
                    ai_graphic.sha256,
                )
                overlays.append(ai_overlay)
                recorded.append(
                    asdict(ai_overlay)
                    | {
                        "path": str(ai_overlay.path),
                        "kind": "ai_disclosure",
                        "text": tag_label,
                        "sha256": ai_graphic.sha256,
                    }
                )
            except (OSError, ValueError) as exc:
                await self._event(run_id, "warning", f"AI disclosure tag omitted: {exc}")

        return overlays, recorded

    async def _editorial_overlays(
        self,
        run_id: UUID,
        attempt: int,
        package_id: UUID,
        script_value: dict[str, Any],
        segments: list[dict[str, Any]],
        font_file: Path,
        profile: ContentProfile,
        story_end: float,
    ) -> tuple[list[OverlayInput], list[dict[str, Any]]]:
        """Keep one grounded context summary in the top panel from Clip start to story end (CF-REQ-259/269)."""
        chosen: dict[int, dict[str, Any]] = {}
        for draft in script_value.get("editorial_overlays", []):
            if draft.get("kind") in _CONTEXT_KINDS:
                chosen.setdefault(int(draft["segment_index"]), draft)
        for item in script_value.get("buzz_lines", []):
            line = BuzzLineDraft.model_validate(item)
            chosen.setdefault(
                line.segment_index,
                {"kind": "headline", "text": line.text, "claim_ids": [str(value) for value in line.claim_ids]},
            )
        starts: dict[int, float] = {}
        for segment in segments:
            if segment.get("script_segment_index") is None or segment.get("start_seconds") is None:
                continue
            index = int(segment["script_segment_index"])
            starts[index] = min(starts.get(index, float("inf")), float(segment["start_seconds"]))
        timeline = sorted((starts[index], index, draft) for index, draft in chosen.items() if index in starts)
        if not timeline:
            return [], []
        context = await asyncio.to_thread(self.production.package_context, package_id)
        sources_by_claim = {
            claim.id: tuple(dict.fromkeys(item.source_id for item in claim.evidence if item.verified))
            for claim in context["claims"]
        }
        known_sources = frozenset(source for sources in sources_by_claim.values() for source in sources)
        overlays: list[OverlayInput] = []
        recorded: list[dict[str, Any]] = []
        carried_start: float | None = 0.0
        for number, (segment_start, _index, draft) in enumerate(timeline):
            start = round(carried_start if carried_start is not None else segment_start, 3)
            end = round(min(timeline[number + 1][0] if number + 1 < len(timeline) else story_end, story_end), 3)
            if end <= start:
                continue
            claim_ids = tuple(UUID(str(value)) for value in draft["claim_ids"])
            cue = EditorialCue(
                draft["kind"],
                draft["text"],
                start,
                end,
                claim_ids,
                tuple(dict.fromkeys(source for claim in claim_ids for source in sources_by_claim.get(claim, ()))),
                secondary=draft.get("secondary", ""),
            )
            try:
                graphic = await asyncio.to_thread(
                    render_editorial_graphic,
                    cue,
                    font_file=font_file,
                    accepted_claim_ids=frozenset(sources_by_claim),
                    known_source_ids=known_sources,
                    width=profile.output.width,
                    height=profile.output.height,
                )
            except (ValueError, OSError) as exc:
                await self._event(run_id, "progress", f"Editorial label {number} skipped: {exc}")
                if overlays:
                    overlays[-1] = replace(overlays[-1], end_seconds=end)
                    recorded[-1]["end_seconds"] = end
                continue
            carried_start = None
            key = f"work/{run_id}/attempt-{attempt}/overlay-{number}.png"
            await self.storage.put_bytes(key, graphic.png_bytes)
            overlays.append(
                OverlayInput(
                    self.storage.local_path(key),
                    cue.start_seconds,
                    cue.end_seconds,
                    graphic.x,
                    graphic.y,
                    graphic.width,
                    graphic.height,
                )
            )
            recorded.append(
                {
                    "kind": cue.kind,
                    "text": cue.text,
                    "secondary": cue.secondary,
                    "start_seconds": cue.start_seconds,
                    "end_seconds": cue.end_seconds,
                    "claim_ids": [str(value) for value in cue.claim_ids],
                    "source_ids": [str(value) for value in cue.source_ids],
                    "sha256": graphic.sha256,
                }
            )
        return overlays, recorded

    async def _sound_cues(self, overlays: list[OverlayInput], clip_duration: float) -> tuple[AudioInput, ...]:
        """A quiet licensed information cue under each label; no cue when the library has none."""
        if not overlays:
            return ()
        library = await asyncio.to_thread(self.assets.list, status=AssetStatus.ACTIVE, limit=500)
        cue_asset = next(
            (
                asset
                for asset in library
                if asset.category == "sfx" and asset.status.value == "active" and (asset.duration_seconds or 0) > 0
            ),
            None,
        )
        if cue_asset is None or not await self.storage.exists(cue_asset.storage_key):
            return ()
        length = min(float(cue_asset.duration_seconds or 0), 1.2)
        return tuple(
            AudioInput(self.storage.local_path(cue_asset.storage_key), overlay.start_seconds, length, gain_db=-26)
            for overlay in overlays
            if overlay.start_seconds + length <= clip_duration
        )

    async def _event(self, run_id: UUID, event_type: str, message: str) -> None:
        await asyncio.to_thread(
            self.runs.append_event, run_id, event_type, message, level="warning", payload={"warning": event_type}
        )


def production_stage_handlers(service: ProductionStageService) -> dict[Stage, StageUseCase]:
    return {
        stage: ProductionStageUseCase(stage, service)
        for stage in (
            Stage.BUILD_STORY_PACKAGE,
            Stage.WRITE_SCRIPT,
            Stage.PLAN_VISUALS,
            Stage.SELECT_ASSETS,
            Stage.GENERATE_NARRATION,
            Stage.TRANSCRIBE_NARRATION,
            Stage.BUILD_CAPTIONS,
            Stage.COMPOSE_CLIP,
            Stage.VALIDATE_CLIP,
            Stage.EVALUATE_CLIP,
            Stage.PLAN_RETRY,
        )
    }


def _required_uuid(state: WorkflowState, key: str) -> UUID:
    value = state.get(key)
    if not value:
        raise StageFailure("internal_error", f"Workflow state is missing {key}")
    return UUID(str(value))


def _library_candidate(asset: Asset) -> MediaCandidate:
    """Present a reusable library Asset to the candidate review alongside external results."""
    return MediaCandidate(
        url=f"asset:{asset.id}",
        download_url="",
        source="library",
        license=asset.provenance.license,
        media_type="video" if asset.media_type == "video" else "image",
        width=asset.width or 0,
        height=asset.height or 0,
        description=asset.description or "",
        duration_seconds=asset.duration_seconds,
    )


def _script_from_value(value: dict[str, Any]) -> GeneratedScript:
    return GeneratedScript(
        language=value["language"],
        segments=tuple(
            ScriptSegment(
                int(item["index"]),
                item["text"],
                tuple(UUID(claim_id) for claim_id in item["claim_ids"]),
                item.get("attribution"),
                float(item["estimated_duration_seconds"]),
            )
            for item in value["segments"]
        ),
        word_count=int(value["word_count"]),
        estimated_duration_seconds=float(value["estimated_duration_seconds"]),
        social_metadata=SocialMetadataDraft.model_validate(value["social_metadata"]),
        visuals=tuple(VisualDraft.model_validate(item) for item in value["visual_draft"]),
        model=value["llm_model"],
        editorial_overlays=tuple(EditorialDraft.model_validate(item) for item in value.get("editorial_overlays", ())),
        people=tuple(PersonDraft.model_validate(item) for item in value.get("people", ())),
        buzz_lines=tuple(BuzzLineDraft.model_validate(item) for item in value.get("buzz_lines", ())),
    )


def _fewer_frames(frames: list[ImageInput]) -> list[ImageInput]:
    """Halve the evaluation frames while keeping the first and last views of the Clip."""
    keep = max(1, len(frames) // 2)
    if keep == 1:
        return frames[len(frames) // 2 : len(frames) // 2 + 1]
    step = (len(frames) - 1) / (keep - 1)
    return [frames[round(index * step)] for index in range(keep)]


def _descriptive_caption(description: str, summary: str, minimum: int = 120) -> str:
    description = " ".join(description.split())
    summary = " ".join(summary.split())
    if len(description) >= minimum or not summary or summary in description:
        return description
    if description and description[-1] not in ".!?":
        description += "."
    return f"{description} {summary}".strip()[:2000]


def _has_evaluation_fallback(detail: dict[str, Any]) -> bool:
    environment = detail["settings_snapshot"].get("environment", {})
    fallback = environment.get("llm_model_evaluation_fallback")
    return bool(fallback) and fallback != (environment.get("llm_model_evaluation") or environment.get("llm_model"))
