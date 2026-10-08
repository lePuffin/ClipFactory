"""Transactional persistence adapter for source-grounded research output."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from clipfactory.domain.models import Claim
from clipfactory.infrastructure.db.models import (
    ClaimEvidenceRow,
    ClaimRow,
    RunRow,
    SourceRow,
    StoryRow,
    StorySourceRow,
)
from clipfactory.ports.research import ResearchSnapshot, ResearchSourceRecord, SelectedStoryContext


class ResearchRunMissing(LookupError):
    pass


class ResearchRepository:
    def __init__(self, sessions: sessionmaker) -> None:
        self.sessions = sessions

    def persist(self, snapshot: ResearchSnapshot) -> None:
        with self.sessions.begin() as session:
            run = session.scalar(select(RunRow).where(RunRow.id == snapshot.run_id).with_for_update())
            if run is None:
                raise ResearchRunMissing(str(snapshot.run_id))
            source_ids: dict[object, object] = {}
            for source in sorted(snapshot.sources, key=lambda item: item.syndication_of is not None):
                existing = session.scalar(select(SourceRow).where(SourceRow.canonical_url == source.canonical_url))
                if existing is not None:
                    source_ids[source.id] = existing.id
                    continue
                source_id = source_ids.get(source.syndication_of, source.syndication_of)
                row = SourceRow(
                    id=source.id,
                    url=source.url,
                    canonical_url=source.canonical_url,
                    publisher=source.publisher,
                    origin_publisher=source.origin_publisher,
                    author=source.author,
                    title=source.title,
                    text=source.text,
                    text_hash=source.text_hash,
                    quality_tier=source.quality_tier,
                    syndication_of=source_id,
                    published_at=source.published_at,
                    retrieved_at=source.retrieved_at,
                    metadata_json={},
                )
                session.add(row)
                session.flush()
                source_ids[source.id] = row.id

            for story in snapshot.stories:
                session.add(
                    StoryRow(
                        id=story.id,
                        run_id=snapshot.run_id,
                        status=story.status,
                        title=story.title,
                        summary=story.summary,
                        category=story.category,
                        selection_score=story.selection_score,
                        score_breakdown=story.score_breakdown,
                        selection_rationale=story.selection_rationale,
                        rejection_reason=story.rejection_reason,
                        key_fact_claim_ids=[str(claim_id) for claim_id in snapshot.key_fact_claim_ids]
                        if story.id == snapshot.selected_story_id
                        else [],
                    )
                )
                session.flush()
                for source_id in story.source_ids:
                    session.add(
                        StorySourceRow(
                            story_id=story.id,
                            source_id=source_ids[source_id],
                            role="evidence" if story.id == snapshot.selected_story_id else "candidate",
                            is_independent=not any(
                                source.id == source_id and source.syndication_of is not None
                                for source in snapshot.sources
                            ),
                        )
                    )

            for claim in snapshot.claims:
                self._persist_claim(session, claim, snapshot.selected_story_id, source_ids)
            run.selected_story_id = snapshot.selected_story_id

    def summary(self, run_id) -> dict[str, object] | None:
        with self.sessions() as session:
            selected = session.scalar(select(StoryRow).where(StoryRow.run_id == run_id, StoryRow.status == "selected"))
            if selected is None:
                return None
            story_count = (
                session.scalar(select(func.count()).select_from(StoryRow).where(StoryRow.run_id == run_id)) or 0
            )
            source_rows = list(
                session.execute(
                    select(SourceRow.syndication_of)
                    .join(StorySourceRow, StorySourceRow.source_id == SourceRow.id)
                    .where(StorySourceRow.story_id == selected.id)
                )
            )
            claim_rows = list(session.scalars(select(ClaimRow).where(ClaimRow.story_id == selected.id)))
            return {
                "story_id": selected.id,
                "title": selected.title,
                "story_candidates": story_count,
                "article_count": len(source_rows),
                "independent_source_count": sum(row.syndication_of is None for row in source_rows),
                "accepted": sum(row.status == "accepted" for row in claim_rows),
                "rejected": sum(row.status == "rejected" for row in claim_rows),
                "corroborated": sum(row.support_level == "corroborated" for row in claim_rows),
                "single_source": sum(row.support_level == "single_source" for row in claim_rows),
            }

    def selected_story_context(self, run_id) -> SelectedStoryContext:
        with self.sessions() as session:
            story = session.scalar(select(StoryRow).where(StoryRow.run_id == run_id, StoryRow.status == "selected"))
            if story is None:
                raise LookupError(f"selected Story is missing for Run {run_id}")
            sources = list(
                session.scalars(
                    select(SourceRow)
                    .join(StorySourceRow, StorySourceRow.source_id == SourceRow.id)
                    .where(StorySourceRow.story_id == story.id)
                )
            )
            return SelectedStoryContext(
                story_id=story.id,
                sources=tuple(
                    ResearchSourceRecord(
                        id=source.id,
                        url=source.url,
                        canonical_url=source.canonical_url,
                        publisher=source.publisher,
                        origin_publisher=source.origin_publisher,
                        title=source.title,
                        text=source.text,
                        text_hash=source.text_hash,
                        quality_tier=source.quality_tier,
                        retrieved_at=source.retrieved_at,
                        published_at=source.published_at,
                        author=source.author,
                        syndication_of=source.syndication_of,
                    )
                    for source in sources
                ),
            )

    def persist_claims(self, story_id, claims, key_fact_claim_ids, title, summary) -> None:
        with self.sessions.begin() as session:
            story = session.scalar(select(StoryRow).where(StoryRow.id == story_id).with_for_update())
            if story is None:
                raise LookupError(f"Story {story_id} is missing")
            existing = session.scalar(select(func.count()).select_from(ClaimRow).where(ClaimRow.story_id == story_id))
            if existing:
                return
            source_ids = {
                source_id: source_id
                for source_id in session.scalars(
                    select(StorySourceRow.source_id).where(StorySourceRow.story_id == story_id)
                )
            }
            for claim in claims:
                self._persist_claim(session, claim, story_id, source_ids)
            story.title = title
            story.summary = summary
            story.key_fact_claim_ids = [str(claim_id) for claim_id in key_fact_claim_ids]

    @staticmethod
    def _persist_claim(session, claim: Claim, story_id, source_ids: dict[object, object]) -> None:
        session.add(
            ClaimRow(
                id=claim.id,
                story_id=story_id,
                text=claim.text,
                kind=claim.kind.value,
                support_level=claim.support_level.value,
                status=claim.status.value,
                rejection_reason=claim.rejection_reason,
            )
        )
        session.flush()
        for evidence in claim.evidence:
            actual_source_id = source_ids.get(evidence.source_id)
            if actual_source_id is None:
                continue
            session.add(
                ClaimEvidenceRow(
                    claim_id=claim.id,
                    source_id=actual_source_id,
                    excerpt=evidence.excerpt,
                    verified=evidence.verified,
                )
            )
