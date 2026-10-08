"""Durable persistence for Story Packages, production artifacts, Clips and retries."""

from __future__ import annotations

from datetime import UTC, datetime
from fractions import Fraction
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from clipfactory.composition.render import RenderedClip
from clipfactory.domain.models import (
    Claim,
    ClaimKind,
    ClaimStatus,
    ClipStatus,
    Evidence,
    SupportLevel,
)
from clipfactory.infrastructure.db.models import (
    AssetUsageRow,
    ClaimEvidenceRow,
    ClaimRow,
    ClipRow,
    RunRow,
    ScriptVersionRow,
    SourceRow,
    StageArtifactRow,
    StoryPackageRow,
    StoryRow,
    VisualPlanVersionRow,
)
from clipfactory.planning.script import GeneratedScript


class ProductionRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def create_story_package(self, run_id: UUID, now: datetime) -> dict[str, Any]:
        with self.sessions.begin() as session:
            existing = session.scalar(select(StoryPackageRow).where(StoryPackageRow.run_id == run_id))
            if existing is not None:
                return _package_summary(existing)
            run = session.scalar(select(RunRow).where(RunRow.id == run_id).with_for_update())
            story = session.scalar(select(StoryRow).where(StoryRow.run_id == run_id, StoryRow.status == "selected"))
            if run is None or story is None:
                raise LookupError("selected Story is missing")
            accepted_ids = set(
                session.scalars(select(ClaimRow.id).where(ClaimRow.story_id == story.id, ClaimRow.status == "accepted"))
            )
            ranked = [UUID(value) for value in story.key_fact_claim_ids]
            if not 3 <= len(ranked) <= 8 or not set(ranked) <= accepted_ids:
                raise ValueError("persisted key facts must contain 3-8 accepted Claims")
            package = StoryPackageRow(
                id=uuid4(),
                run_id=run_id,
                story_id=story.id,
                key_fact_claim_ids=[str(value) for value in ranked],
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(package)
            run.story_package_id = package.id
            session.flush()
            return _package_summary(package)

    def package_context(self, package_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            package = session.get(StoryPackageRow, package_id)
            if package is None:
                raise LookupError("Story Package is missing")
            story = session.get(StoryRow, package.story_id)
            if story is None:
                raise LookupError("Story is missing")
            claims: list[Claim] = []
            for row in session.scalars(
                select(ClaimRow).where(ClaimRow.story_id == story.id, ClaimRow.status == "accepted")
            ):
                evidence = [
                    Evidence(source_id=item.source_id, excerpt=item.excerpt, verified=item.verified)
                    for item in session.scalars(select(ClaimEvidenceRow).where(ClaimEvidenceRow.claim_id == row.id))
                ]
                claims.append(
                    Claim(
                        id=row.id,
                        story_id=row.story_id,
                        text=row.text,
                        kind=ClaimKind(row.kind),
                        evidence=evidence,
                        support_level=SupportLevel(row.support_level),
                        status=ClaimStatus(row.status),
                        rejection_reason=row.rejection_reason,
                    )
                )
            attributions = list(
                session.execute(
                    select(SourceRow.publisher, SourceRow.url)
                    .join(ClaimEvidenceRow, ClaimEvidenceRow.source_id == SourceRow.id)
                    .join(ClaimRow, ClaimRow.id == ClaimEvidenceRow.claim_id)
                    .where(ClaimRow.story_id == story.id, ClaimRow.status == "accepted")
                    .distinct()
                )
            )
            publishers_by_source = dict(
                session.execute(
                    select(SourceRow.id, SourceRow.publisher).where(
                        SourceRow.id.in_({item.source_id for claim in claims for item in claim.evidence})
                    )
                ).all()
            )
            return {
                **_package_summary(package),
                "title": story.title,
                "summary": story.summary,
                "claims": claims,
                "source_attributions": [f"{publisher}: {url}" for publisher, url in attributions],
                "claim_publishers": {
                    claim.id: list(
                        dict.fromkeys(
                            publishers_by_source[item.source_id]
                            for item in claim.evidence
                            if item.verified and publishers_by_source.get(item.source_id)
                        )
                    )
                    for claim in claims
                },
            }

    def save_script(self, package_id: UUID, script: GeneratedScript, now: datetime) -> int:
        with self.sessions.begin() as session:
            package = session.scalar(select(StoryPackageRow).where(StoryPackageRow.id == package_id).with_for_update())
            if package is None:
                raise LookupError("Story Package is missing")
            latest = session.scalar(
                select(func.max(ScriptVersionRow.version)).where(ScriptVersionRow.story_package_id == package_id)
            )
            version = 1 if latest is None else latest + 1
            if latest is not None:
                package.version = version
            value = {
                "version": version,
                "language": script.language,
                "hook_segment_index": 0,
                "segments": [
                    {
                        "index": item.index,
                        "text": item.text,
                        "claim_ids": [str(value) for value in item.claim_ids],
                        "attribution": item.attribution,
                        "estimated_duration_seconds": item.estimated_duration_seconds,
                        "purpose": item.purpose,
                    }
                    for item in script.segments
                ],
                "word_count": script.word_count,
                "estimated_duration_seconds": script.estimated_duration_seconds,
                "llm_model": script.model,
                "prompt_version": "write_script.v1",
                "social_metadata": script.social_metadata.model_dump(mode="json"),
                "visual_draft": [item.model_dump(mode="json") for item in script.visuals],
                "editorial_overlays": [item.model_dump(mode="json") for item in script.editorial_overlays],
            }
            session.add(ScriptVersionRow(story_package_id=package_id, version=version, value=value))
            package.updated_at = now
            return version

    def current_script(self, package_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.scalar(
                select(ScriptVersionRow)
                .where(ScriptVersionRow.story_package_id == package_id)
                .order_by(ScriptVersionRow.version.desc())
                .limit(1)
            )
            if row is None:
                raise LookupError("Script is missing")
            return dict(row.value)

    def save_visual_plan(self, package_id: UUID, version: int, value: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            existing = session.get(VisualPlanVersionRow, (package_id, version))
            if existing is None:
                session.add(VisualPlanVersionRow(story_package_id=package_id, version=version, value=value))
            else:
                existing.value = value

    def current_visual_plan(self, package_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.scalar(
                select(VisualPlanVersionRow)
                .where(VisualPlanVersionRow.story_package_id == package_id)
                .order_by(VisualPlanVersionRow.version.desc())
                .limit(1)
            )
            if row is None:
                raise LookupError("Visual Plan is missing")
            return dict(row.value)

    def artifact(self, run_id: UUID, attempt: int, stage: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(StageArtifactRow, (run_id, attempt, stage))
            return dict(row.value) if row else None

    def latest_artifact(self, run_id: UUID, stage: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalar(
                select(StageArtifactRow)
                .where(StageArtifactRow.run_id == run_id, StageArtifactRow.stage == stage)
                .order_by(StageArtifactRow.attempt.desc())
                .limit(1)
            )
            return dict(row.value) if row else None

    def save_artifact(self, run_id: UUID, attempt: int, stage: str, value: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            row = session.get(StageArtifactRow, (run_id, attempt, stage))
            if row is None:
                session.add(
                    StageArtifactRow(
                        run_id=run_id,
                        attempt=attempt,
                        stage=stage,
                        value=value,
                        created_at=datetime.now(UTC),
                    )
                )
            else:
                row.value = value

    def save_clip(
        self,
        *,
        run_id: UUID,
        story_package_id: UUID,
        story_package_version: int,
        attempt: int,
        rendered: RenderedClip,
        composition_spec_hash: str,
        metadata: dict[str, Any],
        asset_usages: list[dict[str, Any]],
        now: datetime,
    ) -> UUID:
        with self.sessions.begin() as session:
            existing = session.scalar(select(ClipRow).where(ClipRow.run_id == run_id, ClipRow.attempt == attempt))
            if existing is not None:
                return existing.id
            videos = [item for item in rendered.probe.get("streams", []) if item.get("codec_type") == "video"]
            audios = [item for item in rendered.probe.get("streams", []) if item.get("codec_type") == "audio"]
            if len(videos) != 1 or len(audios) != 1:
                raise ValueError("rendered Clip must contain exactly one video and one audio stream")
            video, audio = videos[0], audios[0]
            clip = ClipRow(
                id=uuid4(),
                run_id=run_id,
                story_package_id=story_package_id,
                story_package_version=story_package_version,
                attempt=attempt,
                status=ClipStatus.RENDERED.value,
                storage_key=rendered.storage_key,
                sha256=rendered.sha256,
                duration_seconds=float(rendered.probe.get("format", {}).get("duration", 0)),
                width=int(video["width"]),
                height=int(video["height"]),
                fps=float(Fraction(str(video["avg_frame_rate"]))),
                video_codec=str(video["codec_name"]),
                audio_codec=str(audio["codec_name"]),
                size_bytes=rendered.size_bytes,
                composition_spec_hash=composition_spec_hash,
                metadata_json=metadata,
                created_at=now,
            )
            session.add(clip)
            session.flush()
            for usage in asset_usages:
                session.add(
                    AssetUsageRow(
                        clip_id=clip.id,
                        asset_id=UUID(str(usage["asset_id"])),
                        visual_segment_index=int(usage["visual_segment_index"]),
                        start_seconds=float(usage["start_seconds"]),
                        end_seconds=float(usage["end_seconds"]),
                    )
                )
            return clip.id

    def clip(self, clip_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            clip = session.get(ClipRow, clip_id)
            if clip is None:
                raise LookupError("Clip is missing")
            usages = list(
                session.scalars(
                    select(AssetUsageRow)
                    .where(AssetUsageRow.clip_id == clip_id)
                    .order_by(AssetUsageRow.visual_segment_index)
                )
            )
            return {
                "clip_id": str(clip.id),
                "status": clip.status,
                "storage_key": clip.storage_key,
                "duration_seconds": clip.duration_seconds,
                "width": clip.width,
                "height": clip.height,
                "fps": clip.fps,
                "video_codec": clip.video_codec,
                "audio_codec": clip.audio_codec,
                "metadata": clip.metadata_json,
                "asset_usages": [
                    {
                        "asset_id": str(item.asset_id),
                        "visual_segment_index": item.visual_segment_index,
                        "start_seconds": item.start_seconds,
                        "end_seconds": item.end_seconds,
                    }
                    for item in usages
                ],
            }

    def set_clip_status(self, clip_id: UUID, status: ClipStatus) -> None:
        with self.sessions.begin() as session:
            clip = session.scalar(select(ClipRow).where(ClipRow.id == clip_id).with_for_update())
            if clip is None:
                raise LookupError("Clip is missing")
            clip.status = status.value


def _package_summary(package: StoryPackageRow) -> dict[str, Any]:
    return {
        "story_package_id": str(package.id),
        "story_package_version": package.version,
        "story_id": str(package.story_id),
        "key_fact_claim_ids": list(package.key_fact_claim_ids),
    }
