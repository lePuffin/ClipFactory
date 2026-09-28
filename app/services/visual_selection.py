"""Resolve planned visuals against available media and build renderable scenes."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.reel import (
    EvidenceReference,
    ReelScript,
    ReelScriptSection,
    Scene,
    ScenePlanning,
    SceneVisual,
    SceneVisualType,
    SourceMaterial,
    VisualAsset,
    VisualAssetKind,
)
from app.models.source import ClipSourceType


class VisualSelector:
    """Prefers valid planned media and falls back deterministically without black frames."""

    def select(
        self,
        script: ReelScript,
        planning: ScenePlanning,
        materials: Sequence[SourceMaterial],
    ) -> tuple[Scene, ...]:
        proposals = {proposal.script_section_id: proposal.visual for proposal in planning.scenes}
        materials_by_id = {material.source.id: material for material in materials}
        scenes: list[Scene] = []
        for index, section in enumerate(script.sections, start=1):
            visual = self._usable_visual(
                proposals.get(section.id),
                section,
                materials_by_id,
            )
            if visual is None:
                visual = self._fallback_visual(section, materials_by_id)
            scenes.append(
                Scene(
                    id=f"scene_{index:02d}",
                    script_section_id=section.id,
                    duration=section.duration_seconds,
                    narration=section.text,
                    evidence=section.evidence,
                    visual=visual,
                    visual_intent=section.visual_intent or section.visual_hint,
                )
            )
        return tuple(scenes)

    def _usable_visual(
        self,
        visual: SceneVisual | None,
        section: ReelScriptSection,
        materials: dict[str, SourceMaterial],
    ) -> SceneVisual | None:
        if visual is None:
            return None
        if visual.type is SceneVisualType.TEXT_CARD:
            return self._preferred_evidence_visual(section, materials)
        material = materials.get(visual.source_id or "")
        if material is None:
            return None
        if visual.type is SceneVisualType.SOURCE_VIDEO:
            if visual.start is None or visual.end is None:
                return None
            fitted = self._fit_video_range(
                visual.start,
                visual.end,
                section.duration_seconds,
                material.metadata.duration,
            )
            if fitted is None or material.source.type is not ClipSourceType.VIDEO:
                return None
            return visual.model_copy(update={"start": fitted[0], "end": fitted[1]})
        asset = self._find_asset(material, visual.asset_id)
        if asset is None or not self._matches_visual_type(asset, visual.type):
            return None
        return visual

    def _fallback_visual(
        self,
        section: ReelScriptSection,
        materials: dict[str, SourceMaterial],
    ) -> SceneVisual:
        return self._preferred_evidence_visual(section, materials) or SceneVisual(
            type=SceneVisualType.TEXT_CARD,
            reason="No usable source visual was available for this narration.",
        )

    def _preferred_evidence_visual(
        self,
        section: ReelScriptSection,
        materials: dict[str, SourceMaterial],
    ) -> SceneVisual | None:
        for evidence in section.evidence:
            material = materials.get(evidence.source_id)
            if material is None or material.source.type is not ClipSourceType.VIDEO:
                continue
            fitted = self._fit_video_range(
                evidence.start,
                evidence.end,
                section.duration_seconds,
                material.metadata.duration,
            )
            if fitted is not None:
                return SceneVisual(
                    type=SceneVisualType.SOURCE_VIDEO,
                    source_id=material.source.id,
                    start=fitted[0],
                    end=fitted[1],
                    reason="Transcript evidence matches this narration.",
                )
        for kind, visual_type in (
            (VisualAssetKind.SOURCE_IMAGE, SceneVisualType.SOURCE_IMAGE),
            (VisualAssetKind.ARTICLE_IMAGE, SceneVisualType.ARTICLE_IMAGE),
        ):
            asset = self._evidence_asset(section.evidence, materials, kind)
            if asset is not None:
                return SceneVisual(
                    type=visual_type,
                    source_id=asset.source_id,
                    asset_id=asset.id,
                    reason="Source asset is attached to this narration evidence.",
                )
        return None

    def _fit_video_range(
        self,
        start: float | None,
        end: float | None,
        scene_duration: float,
        source_duration: float | None,
    ) -> tuple[float, float] | None:
        if (
            start is None
            or end is None
            or source_duration is None
            or end <= start
            or source_duration < scene_duration
        ):
            return None
        midpoint = (start + end) / 2
        fitted_start = min(max(0, midpoint - scene_duration / 2), source_duration - scene_duration)
        return fitted_start, fitted_start + scene_duration

    def _find_asset(self, material: SourceMaterial, asset_id: str | None) -> VisualAsset | None:
        return next((asset for asset in material.content.assets if asset.id == asset_id), None)

    def _matches_visual_type(self, asset: VisualAsset, visual_type: SceneVisualType) -> bool:
        return (
            asset.kind is VisualAssetKind.SOURCE_IMAGE
            and visual_type is SceneVisualType.SOURCE_IMAGE
        ) or (
            asset.kind is VisualAssetKind.ARTICLE_IMAGE
            and visual_type is SceneVisualType.ARTICLE_IMAGE
        )

    def _evidence_asset(
        self,
        evidence: Sequence[EvidenceReference],
        materials: dict[str, SourceMaterial],
        kind: VisualAssetKind,
    ) -> VisualAsset | None:
        for reference in evidence:
            material = materials.get(reference.source_id)
            if material is None:
                continue
            if reference.asset_id:
                asset = self._find_asset(material, reference.asset_id)
                if asset is not None and asset.kind is kind:
                    return asset
            asset = next((asset for asset in material.content.assets if asset.kind is kind), None)
            if asset is not None:
                return asset
        return None
