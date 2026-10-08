from pathlib import Path
from typing import Any

import pytest

from clipfactory.bootstrap import create_application
from clipfactory.domain.models import Stage
from clipfactory.infrastructure.settings import EnvironmentSettings


def _settings(tmp_path: Path) -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'assembly.db'}",
        "DATA_DIR": tmp_path / "data",
        "SCHEDULER_ENABLED": False,
        "MEDIA_SOURCES": "pexels,pixabay,unsplash,wikimedia_commons",
    }
    return EnvironmentSettings(**values)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-654")
@pytest.mark.req("CF-REQ-207")
def test_production_assembly_exposes_only_genuinely_backed_stages(tmp_path: Path) -> None:
    application = create_application(_settings(tmp_path))

    assert application.state.stage_executor.supported_stages == {
        Stage.INGEST_URL,
        Stage.RESEARCH,
        Stage.CLUSTER_STORIES,
        Stage.SELECT_STORY,
        Stage.GATHER_SOURCES,
        Stage.EXTRACT_CLAIMS,
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
        Stage.PUBLISH,
    }
    assert set(application.state.providers) == {
        "llm",
        "media_sources",
        "news",
        "publishers",
        "tts",
        "transcription",
        "video",
    }
    assert [provider.name for provider in application.state.providers["video"]] == ["wan_local"]
    assert {source.name for source in application.state.providers["media_sources"]} == {
        "pexels",
        "pixabay",
        "unsplash",
        "wikimedia_commons",
    }
    application.state.engine.dispose()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-759")
def test_production_wan_uses_prepared_run_settings_not_startup_baseline(tmp_path: Path) -> None:
    configured = _settings(tmp_path)
    configured.wan_inference_steps = 50
    application = create_application(configured)
    try:
        wan = application.state.providers["video"][0]
        application.state.prepare_run({"environment": {"wan_inference_steps": 25, "wan_fps": 8}})
        assert wan.settings.wan_inference_steps == 25
        assert wan.settings.wan_fps == 8
        assert configured.wan_inference_steps == 50
        application.state.prepare_run({})
        assert wan.settings.wan_inference_steps == 50
    finally:
        application.state.engine.dispose()
