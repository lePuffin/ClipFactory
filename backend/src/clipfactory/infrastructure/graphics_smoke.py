"""Explicit synthetic native renderer/import smoke, never an application or Run."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from clipfactory.assets.generation import generate_video_asset
from clipfactory.domain.graphics import GraphicsSpec, validate_graphics_claims
from clipfactory.domain.models import AssetOrigin, Claim, ClaimStatus, SupportLevel
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.infrastructure.providers.local_graphics import HyperFramesVideoProvider, ManimVideoProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.generation import VideoGenerationRequest


async def smoke(renderer: str, directory: Path, template: str | None) -> None:
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    root = (await asyncio.to_thread(Path(__file__).resolve)).parents[3]
    values: dict[str, Any] = {
        "_env_file": None,
        "DATABASE_URL": "postgresql://unused/synthetic",
        "DATA_DIR": directory,
        "HYPERFRAMES_PACKAGE_DIR": root / "renderers/hyperframes",
        "HYPERFRAMES_PATH": root / "renderers/hyperframes/clipfactory-hyperframes.mjs",
        "MANIM_PATH": str(root / ".venv/bin/manim"),
        "GRAPHICS_TIMEOUT_SECONDS": 180,
    }
    settings = EnvironmentSettings(**values)
    accepted = Claim(
        story_id=uuid4(),
        text="Synthetic study: Group A 42 supports Group B 21 in 2025 and 2026.",
        status=ClaimStatus.ACCEPTED,
        support_level=SupportLevel.CORROBORATED,
    )

    def label(text: str) -> dict[str, object]:
        return {"text": text, "claim_ids": [str(accepted.id)]}

    selected_template = template or ("statistic" if renderer == "hyperframes" else "function_plot")
    data: dict[str, object] = {"template": selected_template, "title": label("Synthetic study")}
    items = [{"label": label("Group A"), "value": 42}, {"label": label("Group B"), "value": 21}]
    if selected_template == "statistic":
        data["item"] = items[0]
    elif selected_template == "comparison":
        data["items"] = items
    elif selected_template == "timeline":
        data["events"] = [
            {"date": label("2025"), "label": label("Group A")},
            {"date": label("2026"), "label": label("Group B")},
        ]
    elif selected_template == "relationship_diagram":
        data["nodes"] = [{"id": "a", "label": label("Group A")}, {"id": "b", "label": label("Group B")}]
        data["edges"] = [{"source": "a", "target": "b", "label": label("supports")}]
    else:
        data.update({"function": "quadratic", "a": 1, "b": 0, "c": 0, "x_min": -3, "x_max": 3})
    spec = TypeAdapter(GraphicsSpec).validate_python(data)
    validate_graphics_claims(spec, [accepted])
    engine = create_engine(f"sqlite:///{directory / 'synthetic-assets.db'}")
    Base.metadata.create_all(engine)
    assets = AssetRepository(sessionmaker(engine))
    media = MediaRunner("ffmpeg", "ffprobe")
    storage = LocalStorageProvider(directory)
    provider = HyperFramesVideoProvider(settings) if renderer == "hyperframes" else ManimVideoProvider(settings)

    async def progress(message: str, payload: dict[str, object]) -> None:
        if payload.get("generation_phase") != "heartbeat":
            print(message, payload)

    try:
        asset = await generate_video_asset(
            VideoGenerationRequest("Synthetic study", "", 720, 1280, 5, 0, spec),
            providers=[provider],
            storage=storage,
            assets=assets,
            media=media,
            now=datetime(2026, 10, 8, tzinfo=UTC),
            progress=progress,
            max_video_bytes=300000000,
            min_video_height_px=720,
        )
        assert asset is not None
        assert asset.provenance.origin == AssetOrigin.RENDERED
        persisted = await asyncio.to_thread(assets.get, asset.id)
        assert persisted is not None
        assert persisted.sha256 == asset.sha256
        assert persisted.provenance == asset.provenance
        assert persisted.reusable
        path = storage.local_path(asset.storage_key)
        probe = await media.probe(path)
        await media.decode(path)
        stream = probe["streams"][0]
        print(
            "NATIVE PROBED/DECODED/IMPORTED",
            path,
            asset.id,
            {
                "width": stream["width"],
                "height": stream["height"],
                "fps": stream["r_frame_rate"],
                "duration": probe["format"]["duration"],
                "frames": stream.get("nb_frames"),
            },
        )
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("renderer", choices=["hyperframes", "manim"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--template", choices=["statistic", "comparison", "timeline", "function_plot", "relationship_diagram"]
    )
    arguments = parser.parse_args()
    asyncio.run(smoke(arguments.renderer, arguments.directory.resolve(), arguments.template))


if __name__ == "__main__":
    main()
