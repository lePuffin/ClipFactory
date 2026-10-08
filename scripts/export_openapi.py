#!/usr/bin/env python3
"""Export the FastAPI OpenAPI document for generated frontend types."""

from __future__ import annotations

import json
from pathlib import Path

from clipfactory.api.app import create_app
from clipfactory.infrastructure.settings import EnvironmentSettings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    settings = EnvironmentSettings(
        APP_ENV="test",
        DATABASE_URL="postgresql+psycopg://unused:unused@localhost/unused",
        LLM_PROVIDER="fake",
        NEWS_SOURCES="fake",
        TTS_PROVIDER="fake",
        TRANSCRIPTION_PROVIDER="fake",
        PUBLIC_MEDIA_BASE_URL=None,
        MEDIA_URL_SIGNING_KEY=None,
    )
    output = ROOT / "backend" / "openapi.json"
    output.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI schema to {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()