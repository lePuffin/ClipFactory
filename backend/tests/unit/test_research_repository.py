from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Text, create_engine, select

from clipfactory.domain.models import Claim, ClaimKind, ClaimStatus, Evidence, RunTrigger, SupportLevel
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.models import ClaimEvidenceRow, ClaimRow, RunRow, SourceRow, StoryRow, StorySourceRow
from clipfactory.infrastructure.db.repositories import RunRepository
from clipfactory.infrastructure.db.research_repository import ResearchRepository
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.ports.research import ResearchSnapshot, ResearchSourceRecord, ResearchStoryRecord


@pytest.mark.unit
@pytest.mark.req("CF-REQ-118")
@pytest.mark.req("CF-REQ-113")
@pytest.mark.req("CF-REQ-101")
def test_research_repository_persists_provenance_claims_and_evidence_atomically(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    run = RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})
    run_id = UUID(run["run_id"])
    source_id = uuid4()
    syndicated_id = uuid4()
    selected_story_id = uuid4()
    rejected_story_id = uuid4()
    now = datetime(2026, 9, 30, tzinfo=UTC)
    author = ",".join(f"https://news.example/profile/reporter-{index}" for index in range(10))
    assert len(author) > 255
    assert isinstance(SourceRow.__table__.c.author.type, Text)
    source = ResearchSourceRecord(
        source_id,
        "https://wire.example/news",
        "https://wire.example/news",
        "Wire News",
        "Wire News",
        "Report title",
        "The event began today and officials confirmed the result.",
        "a" * 64,
        "high",
        now,
        now,
        author,
        None,
    )
    syndicated = ResearchSourceRecord(
        syndicated_id,
        "https://copy.example/news",
        "https://copy.example/news",
        "Copy Site",
        "Wire News",
        "Copied report",
        source.text,
        "b" * 64,
        "standard",
        now,
        now,
        None,
        source_id,
    )
    stories = (
        ResearchStoryRecord(
            selected_story_id,
            "selected",
            "Report title",
            "The event began today.",
            "general",
            0.8,
            {"recency": 0.9},
            "Strong reporting",
            None,
            (source_id, syndicated_id),
        ),
        ResearchStoryRecord(
            rejected_story_id,
            "rejected",
            "Other story",
            "Another event.",
            "general",
            0.4,
            {"recency": 0.5},
            "Lower score",
            "lower_selection_score",
            (),
        ),
    )
    claim = Claim(
        story_id=selected_story_id,
        text="Officials confirmed the result.",
        kind=ClaimKind.FACT,
        evidence=[
            Evidence(source_id=source_id, excerpt="officials confirmed the result", verified=True),
            Evidence(source_id=source_id, excerpt="The event began today", verified=True),
        ],
        support_level=SupportLevel.SINGLE_SOURCE,
        status=ClaimStatus.ACCEPTED,
    )

    ResearchRepository(sessions).persist(
        ResearchSnapshot(run_id, (source, syndicated), stories, selected_story_id, (claim,), (claim.id,))
    )
    with sessions() as session:
        persisted_run = session.get(RunRow, run_id)
        persisted_copy = session.get(SourceRow, syndicated_id)
        persisted_source = session.get(SourceRow, source_id)
        assert persisted_run is not None
        assert persisted_copy is not None
        assert persisted_source is not None
        assert persisted_source.author == author
        persisted_story = session.get(StoryRow, selected_story_id)
        assert persisted_story is not None
        assert persisted_story.key_fact_claim_ids == [str(claim.id)]
        assert persisted_run.selected_story_id == selected_story_id
        assert len(list(session.scalars(select(SourceRow)))) == 2
        assert len(list(session.scalars(select(StoryRow)))) == 2
        assert len(list(session.scalars(select(StorySourceRow)))) == 2
        assert len(list(session.scalars(select(ClaimRow)))) == 1
        assert len(list(session.scalars(select(ClaimEvidenceRow)))) == 2
        assert persisted_copy.syndication_of == source_id
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-116")
def test_package_context_maps_each_claim_to_its_evidence_publishers(tmp_path) -> None:
    from clipfactory.infrastructure.db.models import StoryPackageRow
    from clipfactory.infrastructure.db.production_repository import ProductionRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'package.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    run_id = UUID(RunRepository(sessions).create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
    source_id, story_id = uuid4(), uuid4()
    now = datetime(2026, 10, 6, tzinfo=UTC)
    source = ResearchSourceRecord(
        source_id,
        "https://wire.example/a",
        "https://wire.example/a",
        "Wire News",
        "Wire News",
        "Title",
        "Officials confirmed the result.",
        "c" * 64,
        "high",
        now,
        now,
        None,
        None,
    )
    story = ResearchStoryRecord(
        story_id, "selected", "Title", "Summary", "general", 0.8, {}, "Reason", None, (source_id,)
    )
    claim = Claim(
        story_id=story_id,
        text="Officials confirmed the result.",
        kind=ClaimKind.FACT,
        evidence=[Evidence(source_id=source_id, excerpt="Officials confirmed the result", verified=True)],
        support_level=SupportLevel.SINGLE_SOURCE,
        status=ClaimStatus.ACCEPTED,
    )
    ResearchRepository(sessions).persist(ResearchSnapshot(run_id, (source,), (story,), story_id, (claim,), (claim.id,)))
    package_id = uuid4()
    with sessions.begin() as session:
        session.add(
            StoryPackageRow(
                id=package_id,
                run_id=run_id,
                story_id=story_id,
                key_fact_claim_ids=[str(claim.id)],
                version=1,
                created_at=now,
                updated_at=now,
            )
        )

    context = ProductionRepository(sessions).package_context(package_id)

    assert context["claim_publishers"] == {claim.id: ["Wire News"]}
    engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
def test_recently_covered_lists_only_completed_runs_finished_inside_the_window(tmp_path) -> None:
    from datetime import timedelta

    engine = create_engine(f"sqlite:///{tmp_path / 'novelty.db'}")
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    runs = RunRepository(sessions)
    repository = ResearchRepository(sessions)
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)

    def record(source_id: UUID, name: str, digest: str) -> ResearchSourceRecord:
        url = f"https://news.example/{name}"
        return ResearchSourceRecord(
            source_id,
            url,
            url,
            "News",
            "News",
            name,
            "Officials confirmed the event.",
            digest,
            "high",
            now,
            now,
            None,
            None,
        )

    def covered_run(name: str, status: str, finished_hours_ago: float) -> None:
        run_id = UUID(runs.create(RunTrigger.RUN_NOW, manual_url=None, settings_snapshot={})["run_id"])
        source_id, leftover_id, story_id = uuid4(), uuid4(), uuid4()
        sources = (
            record(source_id, name, name.ljust(64, "x")[:64]),
            record(leftover_id, f"{name}-leftover", name.ljust(64, "y")[:64]),
        )
        story = ResearchStoryRecord(
            story_id, "selected", name, "Summary.", "general", 0.8, {}, "", None, (source_id, leftover_id)
        )
        claim = Claim(
            story_id=story_id,
            text="Officials confirmed the event.",
            kind=ClaimKind.FACT,
            evidence=[Evidence(source_id=source_id, excerpt="Officials confirmed the event", verified=True)],
            support_level=SupportLevel.SINGLE_SOURCE,
            status=ClaimStatus.ACCEPTED,
        )
        repository.persist(ResearchSnapshot(run_id, sources, (story,), story_id, (claim,), (claim.id,)))
        with sessions.begin() as session:
            row = session.get(RunRow, run_id)
            assert row is not None
            row.status = status
            row.finished_at = now - timedelta(hours=finished_hours_ago)

    covered_run("completed-yesterday", "completed", 20)
    covered_run("failed-today", "failed", 2)
    covered_run("completed-too-early", "completed", 49)

    covered = repository.recently_covered(now - timedelta(hours=48))

    assert [story.title for story in covered] == ["completed-yesterday"]
    # Articles grouped with the Story but not cited by its accepted Claims are not covered.
    assert covered[0].canonical_urls == frozenset({"https://news.example/completed-yesterday"})
    engine.dispose()
