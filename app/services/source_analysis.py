"""Grounded source-level analysis for text, video transcripts, and local images."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.reel import SourceAnalysis, SourceMaterial
from app.prompts.source_analysis import SYSTEM_PROMPT
from app.services.reel_llm import OpenRouterJSONClient, parse_json_model
from app.services.reel_validation import hydrate_source_analysis


class SourceAnalyzer(Protocol):
    """Produces one structured analysis for an extracted normalized source."""

    def analyze(
        self, material: SourceMaterial, image_path: Path | None = None
    ) -> SourceAnalysis: ...


class OpenRouterSourceAnalyzer:
    """Uses a configured OpenAI-compatible model for source understanding."""

    def __init__(self, settings: Settings) -> None:
        self.client = OpenRouterJSONClient(settings)

    def analyze(self, material: SourceMaterial, image_path: Path | None = None) -> SourceAnalysis:
        analysis = self.client.generate(
            SYSTEM_PROMPT,
            build_source_analysis_payload(material),
            lambda content: parse_json_model(content, SourceAnalysis),
            maximum_tokens=3_000,
            image_path=image_path,
        )
        if not analysis.important_evidence and not analysis.claims:
            raise LLMError("Source analysis did not provide evidence for its interpretation")
        return hydrate_source_analysis(analysis, material)


def build_source_analysis_payload(material: SourceMaterial) -> dict[str, object]:
    """Bound one source's extracted data for the source-analysis prompt."""
    return {
        "source": {
            "id": material.source.id,
            "type": material.source.type,
            "name": material.source.name,
            "origin": material.source.origin,
        },
        "metadata": material.metadata.model_dump(mode="json"),
        "segments": [
            {
                "id": segment.id,
                "text": segment.text[:6_000],
                "start": segment.start,
                "end": segment.end,
            }
            for segment in material.content.segments[:100]
        ],
        "assets": [asset.model_dump(mode="json") for asset in material.content.assets],
    }
