"""OpenAI-compatible semantic clip selection, configured for OpenRouter by default."""

import json
import logging
import re
from collections.abc import Sequence
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.clip import ClipAnalysis
from app.pipelines.candidates import CandidateWindow
from app.prompts.clip_selection import SYSTEM_PROMPT

logger = logging.getLogger(__name__)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ClipSelector(Protocol):
    """Semantic selection contract kept independent of a particular model provider."""

    def select(
        self,
        candidates: Sequence[CandidateWindow],
        clip_count: int,
        source_duration: float,
    ) -> ClipAnalysis: ...


class OpenRouterClipSelector:
    """Calls any OpenAI-compatible provider using an OpenRouter API token by default."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def select(
        self,
        candidates: Sequence[CandidateWindow],
        clip_count: int,
        source_duration: float,
    ) -> ClipAnalysis:
        if not self.settings.llm_is_configured:
            raise LLMError("OPENROUTER_API_KEY is not configured")
        if not candidates:
            raise LLMError("No transcript candidates are available for analysis")

        client = self._create_client()
        user_message = build_selection_message(candidates, clip_count, source_duration)
        failures: list[str] = []
        for attempt in range(2):
            try:
                completion = client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=2500,
                )
                content = completion.choices[0].message.content
                if not content:
                    raise LLMError("The LLM returned an empty response")
                return parse_clip_analysis(content)
            except Exception as error:
                failures.append(str(error))
                logger.warning("Clip analysis attempt %s failed: %s", attempt + 1, error)
                user_message += "\nReturn only valid JSON matching the required schema."
        raise LLMError(f"The LLM returned invalid clip analysis after two attempts: {failures[-1]}")

    def _create_client(self) -> object:
        try:
            from openai import OpenAI

            return OpenAI(
                api_key=self.settings.llm_api_key.get_secret_value(),
                base_url=self.settings.llm_base_url,
                timeout=120.0,
                max_retries=0,
            )
        except Exception as error:
            raise LLMError(f"Could not create the OpenRouter client: {error}") from error


def build_selection_message(
    candidates: Sequence[CandidateWindow],
    clip_count: int,
    source_duration: float,
    maximum_candidates: int = 80,
) -> str:
    """Serialize a bounded candidate set instead of an entire transcript."""
    sampled = _sample_evenly(candidates, maximum_candidates)
    payload = {
        "requested_clip_count": clip_count,
        "source_duration_seconds": round(source_duration, 3),
        "candidates": [
            {
                "start": round(candidate.start, 3),
                "end": round(candidate.end, 3),
                "text": candidate.text[:1200],
            }
            for candidate in sampled
        ],
    }
    return "Select clips from this JSON data:\n" + json.dumps(payload, ensure_ascii=True)


def parse_clip_analysis(content: str) -> ClipAnalysis:
    """Validate model content before it can influence local rendering timestamps."""
    normalized = _CODE_FENCE.sub("", content.strip())
    try:
        return ClipAnalysis.model_validate_json(normalized)
    except Exception as error:
        raise LLMError(f"The LLM response does not match the clip schema: {error}") from error


def _sample_evenly(
    candidates: Sequence[CandidateWindow],
    maximum_candidates: int,
) -> list[CandidateWindow]:
    if len(candidates) <= maximum_candidates:
        return list(candidates)
    positions = {
        round(index * (len(candidates) - 1) / (maximum_candidates - 1))
        for index in range(maximum_candidates)
    }
    return [candidates[index] for index in sorted(positions)]
