"""Explicit native-only suite: python -m pytest native_tests (not default testpaths)."""

import asyncio
from pathlib import Path

import pytest

from clipfactory.infrastructure.graphics_smoke import smoke


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-263")
@pytest.mark.req("CF-REQ-265")
@pytest.mark.parametrize(
    ("renderer", "template"),
    [
        ("hyperframes", "statistic"),
        ("hyperframes", "comparison"),
        ("hyperframes", "timeline"),
        ("manim", "function_plot"),
        ("manim", "relationship_diagram"),
    ],
)
async def test_native_video_probe_decode_import_and_persistence(tmp_path: Path, renderer: str, template: str) -> None:
    await smoke(renderer, tmp_path, template)
    videos = await asyncio.to_thread(lambda: list(tmp_path.glob("assets/*/*.mp4")))
    assert len(videos) == 1
    assert (await asyncio.to_thread(videos[0].stat)).st_size > 0
    assert await asyncio.to_thread((tmp_path / "synthetic-assets.db").is_file)
