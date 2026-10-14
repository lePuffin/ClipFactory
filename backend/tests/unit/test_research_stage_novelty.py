from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from clipfactory.domain.models import ContentProfile
from clipfactory.domain.research_policy import ResearchControls
from clipfactory.ports.research import CoveredStory
from clipfactory.workflow.research_stages import ResearchStageUseCase


class FakeRuns:
    def __init__(self, research_settings: dict[str, Any]) -> None:
        self.research_settings = research_settings

    def get(self, run_id: object) -> dict[str, Any]:
        del run_id
        profile = ContentProfile().model_dump(mode="json")
        # This fixture represents an immutable Run written under the old split contract.
        for key in ResearchControls.model_fields:
            profile["research"].pop(key)
        return {
            "profile_snapshot": profile,
            "settings_snapshot": {
                "research": {"feeds": [["Fixture", "https://news.example/rss"]], **self.research_settings}
            },
        }

    def append_event(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


class FakeRepository:
    covered = (CoveredStory("Riyadh airport attack kills 12", frozenset({"https://news.example/riyadh"})),)

    def __init__(self) -> None:
        self.since: list[datetime] = []

    def summary(self, run_id: object) -> None:
        del run_id

    def recently_covered(self, since: datetime) -> tuple[CoveredStory, ...]:
        self.since.append(since)
        return self.covered


class FakeResearch:
    def __init__(self) -> None:
        self.recently_covered: tuple[CoveredStory, ...] | None = None

    async def execute(self, *args: Any, recently_covered: tuple[CoveredStory, ...], **kwargs: Any) -> Any:
        del args, kwargs
        self.recently_covered = recently_covered

        class Result:
            story_id = uuid4()
            fallback_index = 0

            class research:
                references_seen = 0
                articles = ()
                articles_skipped = 0

        return Result()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
@pytest.mark.asyncio
async def test_research_stage_passes_stories_covered_in_the_configured_window() -> None:
    repository, research = FakeRepository(), FakeResearch()
    before = datetime.now(UTC)
    stage = ResearchStageUseCase(research, repository, FakeRuns({"story_novelty_window_hours": 48}))  # type: ignore[arg-type]

    await stage.execute({"run_id": str(uuid4())})  # type: ignore[typeddict-item]

    assert research.recently_covered == FakeRepository.covered
    assert before - timedelta(hours=48) <= repository.since[0] <= datetime.now(UTC) - timedelta(hours=48)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-109")
@pytest.mark.asyncio
async def test_a_zero_novelty_window_disables_the_rule() -> None:
    repository, research = FakeRepository(), FakeResearch()
    stage = ResearchStageUseCase(research, repository, FakeRuns({"story_novelty_window_hours": 0}))  # type: ignore[arg-type]

    await stage.execute({"run_id": str(uuid4())})  # type: ignore[typeddict-item]

    assert research.recently_covered == ()
    assert repository.since == []
