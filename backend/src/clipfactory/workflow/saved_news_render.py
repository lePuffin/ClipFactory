"""Reproducible saved-content news rendering with no research or LLM calls."""

from __future__ import annotations

import asyncio
import io
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from PIL import Image, ImageFont
from pydantic import BaseModel, ConfigDict, Field

from clipfactory.assets.title_card import render_title_card
from clipfactory.composition.render import MediaExecutor, render_clip
from clipfactory.composition.spec import AudioInput, CompositionSpec, OverlayInput, VisualInput
from clipfactory.domain.models import Asset, AssetStatus, ContentProfile, Platform
from clipfactory.planning.motion import ShotMedia, choose_shot_motions
from clipfactory.ports.assets import AssetReader
from clipfactory.ports.render_revisions import RenderRevisionRepository
from clipfactory.ports.storage import MediaStorage
from clipfactory.production.alignment import AlignedWord
from clipfactory.production.captions import FontLoader, build_caption_track, render_ass
from clipfactory.production.editorial import EditorialCue, render_editorial_graphic


class OverlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["headline", "person", "place", "source", "quote", "number"]
    text: str = Field(min_length=1, max_length=200)
    secondary: str = Field(default="", max_length=100)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    claim_ids: tuple[UUID, ...] = ()
    source_ids: tuple[UUID, ...] = ()
    asset_id: UUID | None = None
    placement: Literal["top", "context"] = "top"


class SoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0, le=10)
    gain_db: float = Field(default=-24, ge=-60, le=0)
    fade_seconds: float = Field(default=0.15, ge=0, le=1)


class CardBackgroundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment_index: int = Field(ge=0)
    photo_asset_id: UUID


class SavedNewsRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_clip_id: UUID
    template_version: str = "modern-news-v1"
    overlays: tuple[OverlayRequest, ...] = ()
    sound_effects: tuple[SoundRequest, ...] = ()
    music_asset_id: UUID | None = None
    brand_mark_asset_id: UUID | None = None
    card_backgrounds: tuple[CardBackgroundRequest, ...] = ()
    transition_policy: Literal["planned", "cuts"] = "cuts"
    target_platforms: tuple[Platform, ...] = tuple(Platform)
    subtitle_bottom_margin_pct: float = Field(default=22, ge=10, le=30)


class RenderRevisionResponse(BaseModel):
    revision_id: UUID
    base_clip_id: UUID
    status: Literal["pending_review"]
    storage_key: str
    sha256: str
    composition_spec_hash: str
    request: SavedNewsRenderRequest
    probe: dict[str, Any]
    credits: list[str]
    sources: list[str]
    template_version: str
    openrouter_calls: int
    tts_calls: int
    research_calls: int
    transcription_calls: int


class SavedNewsRenderer:
    def __init__(
        self,
        *,
        repository: RenderRevisionRepository,
        assets: AssetReader,
        storage: MediaStorage,
        media: MediaExecutor,
        font_file: Path,
        clock: Callable[[], datetime],
        font_loader: FontLoader = ImageFont.truetype,
    ) -> None:
        self.repository = repository
        self.assets = assets
        self.storage = storage
        self.media = media
        self.font_file = font_file
        self.clock = clock
        self.font_loader = font_loader

    async def execute(self, request: SavedNewsRenderRequest) -> dict[str, Any]:
        context = await asyncio.to_thread(self.repository.context, request.base_clip_id)
        clip = context["clip"]
        metadata = clip["metadata"]
        profile = ContentProfile.model_validate(context["profile"])
        settings = context["settings"]
        composition = settings.get("composition", {})
        revision_id = uuid4()
        work_key = f"work/render-revisions/{revision_id}"
        narration = metadata["narration"]
        duration = (
            float(narration["duration_seconds"])
            + float(composition.get("lead_in_seconds", 0.3))
            + float(composition.get("tail_seconds", 1))
        )
        known_claims = frozenset(claim.id for claim in context["package"]["claims"])
        known_sources = frozenset(source.id for source in context["sources"])
        lead_in = float(composition.get("lead_in_seconds", 0.3))
        words = tuple(
            AlignedWord(
                word["text"],
                word["start_seconds"] + lead_in,
                word["end_seconds"] + lead_in,
                word["script_segment_index"],
            )
            for word in metadata["word_timings"]
        )
        captions = await asyncio.to_thread(
            build_caption_track,
            words,
            font_file=self.font_file,
            width=profile.output.width,
            height=profile.output.height,
            bottom_margin_pct=request.subtitle_bottom_margin_pct,
            font_loader=self.font_loader,
        )
        caption_key = f"{work_key}/captions.ass"
        await self.storage.put_bytes(caption_key, render_ass(captions).encode())
        overlays = []
        segments = []
        credits = []
        for index, draft in enumerate(request.overlays):
            if draft.end_seconds > duration:
                raise ValueError("Editorial label extends beyond the retained narration timeline")
            cue = EditorialCue(
                draft.kind,
                draft.text,
                draft.start_seconds,
                draft.end_seconds,
                draft.claim_ids,
                draft.source_ids,
                draft.asset_id,
                draft.secondary,
                draft.placement,
            )
            graphic = await asyncio.to_thread(
                render_editorial_graphic,
                cue,
                font_file=self.font_file,
                accepted_claim_ids=known_claims,
                known_source_ids=known_sources,
                width=profile.output.width,
                height=profile.output.height,
            )
            for caption in captions.cues:
                overlap_time = cue.start_seconds < caption.end_seconds and caption.start_seconds < cue.end_seconds
                overlap_space = (
                    graphic.x < caption.x + caption.width
                    and caption.x < graphic.x + graphic.width
                    and (graphic.y < caption.y + caption.height)
                    and (caption.y < graphic.y + graphic.height)
                )
                if overlap_time and overlap_space:
                    raise ValueError("Editorial label collides with subtitles")
            key = f"{work_key}/overlay-{index}.png"
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
        if request.brand_mark_asset_id is not None:
            brand_mark = await asyncio.to_thread(self.assets.get, request.brand_mark_asset_id)
            if (
                brand_mark is None
                or brand_mark.status != AssetStatus.ACTIVE
                or brand_mark.media_type != "image"
                or not brand_mark.provenance.license.strip()
            ):
                raise ValueError("Brand mark requires an active licensed image Asset")
            brand_mark_path = self.storage.local_path(brand_mark.storage_key)
            if not await self.storage.exists(brand_mark.storage_key):
                raise ValueError("Brand mark image file is unavailable")
            scale = profile.output.width / 720
            maximum_dimension = round(112 * scale)
            margin = round(24 * scale)
            if maximum_dimension + 2 * margin > min(profile.output.width, profile.output.height):
                raise ValueError("Brand mark cannot fit within the output frame")
            image_bytes, brand_width, brand_height = await asyncio.to_thread(
                _resize_brand_mark, brand_mark_path, maximum_dimension
            )
            brand_mark_key = f"{work_key}/brand-mark.png"
            await self.storage.put_bytes(brand_mark_key, image_bytes)
            overlays.append(
                OverlayInput(
                    self.storage.local_path(brand_mark_key),
                    0,
                    duration,
                    profile.output.width - margin - brand_width,
                    margin,
                    brand_width,
                    brand_height,
                )
            )
            if brand_mark.provenance.attribution_required:
                credits.append(brand_mark.provenance.attribution_text)
        used_assets = set()
        previous: tuple[UUID, object] | None = None
        backgrounds = {item.segment_index: item.photo_asset_id for item in request.card_backgrounds}
        if len(backgrounds) != len(request.card_backgrounds):
            raise ValueError("A card can have only one background photo")
        if any(index >= len(metadata["visual_segments"]) for index in backgrounds):
            raise ValueError("Card background references an unknown visual segment")
        shots: list[ShotMedia] = []
        visual_paths: list[tuple[Path, Asset]] = []
        for position, segment in enumerate(metadata["visual_segments"]):
            asset = await asyncio.to_thread(self.assets.get, UUID(segment["selected_asset_id"]))
            if asset is None or asset.status != AssetStatus.ACTIVE or (not asset.provenance.license.strip()):
                raise ValueError("Saved visual is missing, inactive or unlicensed")
            continuation = previous == (asset.id, segment.get("script_segment_index"))
            if asset.id in used_assets and not continuation:
                raise ValueError("Saved visual plan repeats an Asset")
            used_assets.add(asset.id)
            previous = (asset.id, segment.get("script_segment_index"))
            if not await self.storage.exists(asset.storage_key):
                raise ValueError("Saved visual file is unavailable")
            path = self.storage.local_path(asset.storage_key)
            if position in backgrounds:
                path = await self._card_with_photo(
                    asset, backgrounds[position], f"{work_key}/card-{position}.png", profile, credits
                )
            visual_paths.append((path, asset))
            shots.append(
                ShotMedia(
                    media_type=asset.media_type,
                    category=asset.category,
                    width=asset.width or profile.output.width,
                    height=asset.height or profile.output.height,
                    requested_motion=str(segment.get("motion", "none")),
                    asset_id=str(asset.id),
                    script_segment_index=segment.get("script_segment_index"),
                )
            )
            if asset.provenance.attribution_required and not continuation:
                credits.append(asset.provenance.attribution_text)
        for segment, (path, asset), motion in zip(
            metadata["visual_segments"], visual_paths, choose_shot_motions(shots), strict=True
        ):
            segments.append(
                VisualInput(
                    path,
                    "video" if asset.media_type == "video" else "image",
                    asset.width or profile.output.width,
                    asset.height or profile.output.height,
                    float(segment["end_seconds"]) - float(segment["start_seconds"]),
                    motion.motion,
                    segment["transition_in"] if request.transition_policy == "planned" else "cut",
                    segment.get("source_label"),
                )
            )
        sounds = []
        for cue in request.sound_effects:
            asset = await asyncio.to_thread(self.assets.get, cue.asset_id)
            if (
                asset is None
                or asset.status != AssetStatus.ACTIVE
                or asset.category != "sfx"
                or (not asset.provenance.license.strip())
            ):
                raise ValueError("Sound cue requires an active licensed SFX Asset")
            if asset.provenance.allowed_platforms is not None and (
                not set(request.target_platforms) <= set(asset.provenance.allowed_platforms)
            ):
                raise ValueError("Sound cue licence does not cover the target platforms")
            if not asset.duration_seconds or cue.duration_seconds > asset.duration_seconds:
                raise ValueError("Sound cue exceeds its licensed file duration")
            sounds.append(
                AudioInput(
                    self.storage.local_path(asset.storage_key),
                    cue.start_seconds,
                    cue.duration_seconds,
                    cue.gain_db,
                    cue.fade_seconds,
                )
            )
            if asset.provenance.attribution_required:
                credits.append(asset.provenance.attribution_text)
        music_path = None
        if request.music_asset_id:
            music = await asyncio.to_thread(self.assets.get, request.music_asset_id)
            if (
                music is None
                or music.status != AssetStatus.ACTIVE
                or music.music is None
                or (not music.provenance.license.strip())
            ):
                raise ValueError("Music requires an active manifest-described licensed Asset")
            if music.music.allowed_platforms is not None and (
                not set(request.target_platforms) <= set(music.music.allowed_platforms)
            ):
                raise ValueError("Music licence does not cover the target platforms")
            music_path = self.storage.local_path(music.storage_key)
            if music.provenance.attribution_required:
                credits.append(music.provenance.attribution_text)
        spec = CompositionSpec(
            segments=tuple(segments),
            narration_path=self.storage.local_path(narration["narration_key"]),
            caption_file=self.storage.local_path(caption_key),
            output_path=self.storage.local_path(f"{work_key}/clip.tmp.mp4"),
            narration_duration_seconds=float(narration["duration_seconds"]),
            music_path=music_path,
            narration_word_spans=tuple(
                (word["start_seconds"], word["end_seconds"]) for word in metadata["word_timings"]
            ),
            width=profile.output.width,
            height=profile.output.height,
            fps=profile.output.fps,
            lead_in_seconds=float(composition.get("lead_in_seconds", 0.3)),
            tail_seconds=float(composition.get("tail_seconds", 1)),
            fonts_dir=self.font_file.parent,
            motion_intensity=profile.visual_style.motion_intensity,
            overlays=tuple(overlays),
            sound_effects=tuple(sounds),
        )
        rendered = await render_clip(
            spec, storage=self.storage, runner=self.media, final_key=f"clips/revisions/{revision_id}.mp4"
        )
        value = {
            "revision_id": str(revision_id),
            "base_clip_id": str(request.base_clip_id),
            "status": "pending_review",
            "storage_key": rendered.storage_key,
            "sha256": rendered.sha256,
            "composition_spec_hash": spec.sha256(),
            "request": request.model_dump(mode="json"),
            "probe": rendered.probe,
            "credits": list(dict.fromkeys(credit for credit in credits if credit)),
            "sources": context["package"]["source_attributions"],
            "template_version": request.template_version,
            "openrouter_calls": 0,
            "tts_calls": 0,
            "research_calls": 0,
            "transcription_calls": 0,
        }
        await self.storage.put_bytes(f"clips/revisions/{revision_id}.json", json.dumps(value, indent=2).encode())
        await asyncio.to_thread(self.repository.save_revision, revision_id, request.base_clip_id, value, self.clock())
        return value

    async def _card_with_photo(
        self, card: Asset, photo_id: UUID, key: str, profile: ContentProfile, credits: list[str | None]
    ) -> Path:
        if card.category != "title_card" or not card.description.strip():
            raise ValueError("Only a text card can receive a background photo")
        photo = await asyncio.to_thread(self.assets.get, photo_id)
        if (
            photo is None
            or photo.status != AssetStatus.ACTIVE
            or photo.media_type != "image"
            or not photo.provenance.license.strip()
            or not await self.storage.exists(photo.storage_key)
        ):
            raise ValueError("Card background requires an active licensed image Asset")
        rendered = await asyncio.to_thread(
            render_title_card,
            card.description,
            width=profile.output.width,
            height=profile.output.height,
            font_file=self.font_file,
            background_image=self.storage.local_path(photo.storage_key),
        )
        await self.storage.put_bytes(key, rendered.png_bytes)
        credits.append(photo.provenance.attribution_text)
        return self.storage.local_path(key)


def _resize_brand_mark(source: Path, maximum_dimension: int) -> tuple[bytes, int, int]:
    with Image.open(source) as original:
        image = original.convert("RGBA")
        image.thumbnail((maximum_dimension, maximum_dimension), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue(), image.width, image.height
