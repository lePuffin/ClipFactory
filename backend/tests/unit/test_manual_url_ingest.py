from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clipfactory.domain.models import Claim, ClaimKind, ContentProfile, ResearchPolicy
from clipfactory.ports.llm import LLMMessage, LLMResult
from clipfactory.ports.research import ResearchSourceRecord, SelectedStoryContext
from clipfactory.research.grounding import ClaimEvidenceDraft
from clipfactory.research.llm_tasks import ExtractClaimsResult, ExtractedClaimDraft
from clipfactory.research.manual_url import ManualURLClaimExtractor, ManualURLFailure, ManualURLIngest


class FakeFetcher:
    def __init__(self, payload: bytes | Exception) -> None:
        self.payload = payload

    async def get_bytes(self, url: str, *, max_bytes: int) -> tuple[bytes, str, object]:
        del max_bytes
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload, url, object()


class RecordingRepository:
    def __init__(self) -> None:
        self.snapshots: list[Any] = []

    def persist(self, snapshot: Any) -> None:
        self.snapshots.append(snapshot)


class ClaimRepository:
    def __init__(self, context: SelectedStoryContext) -> None:
        self.context = context
        self.persisted: tuple[Any, ...] | None = None

    def selected_story_context(self, run_id: Any) -> SelectedStoryContext:
        del run_id
        return self.context

    def persist_claims(
        self,
        story_id: UUID,
        claims: tuple[Claim, ...],
        key_fact_claim_ids: tuple[UUID, ...],
        title: str,
        summary: str,
    ) -> None:
        self.persisted = (story_id, claims, key_fact_claim_ids, title, summary)


class ClaimLLM:
    name = "fake"

    def __init__(self, result: ExtractClaimsResult) -> None:
        self.result = result
        self.tasks: list[str] = []

    async def generate_structured(
        self,
        task: str,
        messages: list[LLMMessage],
        schema: type[Any],
        *,
        model_role: str = "default",
        images: list[Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[Any]:
        del messages, schema, model_role, images, temperature
        self.tasks.append(task)
        return cast(LLMResult[Any], LLMResult(self.result, "fake", "test-model"))


def claim_context() -> SelectedStoryContext:
    story_id = uuid4()
    source = ResearchSourceRecord(
        id=uuid4(),
        url="https://news.example/report",
        canonical_url="https://news.example/report",
        publisher="news.example",
        origin_publisher="news.example",
        title="Public-interest report",
        text="The city opened a bridge. It cost 12 million dollars. The mayor attended the opening.",
        text_hash="hash",
        quality_tier="high",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        published_at=None,
        author=None,
        syndication_of=None,
    )
    return SelectedStoryContext(story_id=story_id, sources=(source,))


@pytest.mark.unit
@pytest.mark.req("CF-REQ-701")
@pytest.mark.asyncio
async def test_manual_url_ingest_persists_selected_story_and_evidence_source() -> None:
    repository = RecordingRepository()
    ingest = ManualURLIngest(
        FakeFetcher(
            b"<html><head><title>Public-interest report</title></head><body><article>"
            b"<p>The first paragraph gives the important lead for readers.</p>"
            b"<p>The article continues with enough extractable reporting.</p>"
            b"</article></body></html>"
        ),
        repository,
    )

    result = await ingest.execute(
        uuid4(),
        "https://news.example/report",
        ContentProfile(),
        now=datetime(2026, 10, 1, tzinfo=UTC),
        max_article_bytes=100_000,
        publisher_quality={"news.example": "high"},
    )

    snapshot = repository.snapshots[0]
    assert result.story_id == snapshot.selected_story_id
    assert snapshot.stories[0].status == "selected"
    assert snapshot.stories[0].source_ids == (snapshot.sources[0].id,)
    assert snapshot.sources[0].quality_tier == "high"
    assert snapshot.claims == ()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-701")
@pytest.mark.parametrize(
    ("payload", "blocked", "code"),
    [
        (OSError("offline"), [], "url_unreachable"),
        (b"<html><title>Navigation only</title></html>", [], "url_not_article"),
        (b"<article><title>Blocked</title><p>Article body.</p></article>", ["news.example"], "url_blocked_source"),
    ],
)
@pytest.mark.asyncio
async def test_manual_url_ingest_maps_specified_failures(
    payload: bytes | Exception, blocked: list[str], code: str
) -> None:
    ingest = ManualURLIngest(FakeFetcher(payload), RecordingRepository())

    with pytest.raises(ManualURLFailure, match=code) as caught:
        await ingest.execute(
            uuid4(),
            "https://news.example/report",
            ContentProfile(research=ResearchPolicy(blocked_publishers=blocked)),
            now=datetime(2026, 10, 1, tzinfo=UTC),
            max_article_bytes=100_000,
            publisher_quality={},
        )

    assert caught.value.code == code


@pytest.mark.unit
@pytest.mark.req("CF-REQ-701")
@pytest.mark.req("CF-REQ-702")
@pytest.mark.asyncio
async def test_manual_url_extracts_and_persists_grounded_claims() -> None:
    context = claim_context()
    source_id = context.sources[0].id
    llm = ClaimLLM(
        ExtractClaimsResult(
            claims=[
                ExtractedClaimDraft(
                    ref="c1",
                    text="The city opened a bridge.",
                    kind=ClaimKind.FACT,
                    evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt="opened a bridge")],
                ),
                ExtractedClaimDraft(
                    ref="c2",
                    text="The bridge cost 12 million dollars.",
                    kind=ClaimKind.FIGURE,
                    evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt="cost 12 million dollars")],
                ),
                ExtractedClaimDraft(
                    ref="c3",
                    text="The mayor attended the opening.",
                    kind=ClaimKind.FACT,
                    evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt="mayor attended the opening")],
                ),
            ],
            key_fact_refs=["c1", "c2", "c3"],
            refined_title="City bridge opens",
            refined_summary="The city opened a new bridge.",
        )
    )
    repository = ClaimRepository(context)

    result = await ManualURLClaimExtractor(llm, repository).execute(uuid4(), max_input_chars=10_000)

    assert llm.tasks == ["extract_claims"]
    assert len(result.claims) == 3
    assert repository.persisted is not None
    assert repository.persisted[3:] == ("City bridge opens", "The city opened a new bridge.")


@pytest.mark.unit
@pytest.mark.req("CF-REQ-703")
@pytest.mark.asyncio
async def test_manual_url_fails_when_fewer_than_three_claims_are_accepted() -> None:
    context = claim_context()
    source_id = context.sources[0].id
    repository = ClaimRepository(context)
    llm = ClaimLLM(
        ExtractClaimsResult(
            claims=[
                ExtractedClaimDraft(
                    ref="c1",
                    text="The city opened a bridge.",
                    kind=ClaimKind.FACT,
                    evidence=[ClaimEvidenceDraft(source_id=source_id, excerpt="opened a bridge")],
                )
            ],
            key_fact_refs=["c1"],
            refined_title="City bridge opens",
            refined_summary="The city opened a new bridge.",
        )
    )

    with pytest.raises(ManualURLFailure, match="insufficient_claims"):
        await ManualURLClaimExtractor(llm, repository).execute(uuid4(), max_input_chars=10_000)

    assert repository.persisted is None
