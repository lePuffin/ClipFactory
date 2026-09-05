"""OpenAI-compatible generation of validated multi-source reel narration."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.models.article import ArticleDocument
from app.models.script import ReelScript
from app.models.transcript import TranscriptSegment
from app.prompts.reel_script import SYSTEM_PROMPT

logger = logging.getLogger(__name__)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ScriptGenerator(Protocol):
    """Produces a structured reel narration from normalized source material."""

    def generate(
        self,
        articles: Sequence[ArticleDocument],
        video_transcripts: Mapping[str, Sequence[TranscriptSegment]],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
    ) -> ReelScript: ...


class OpenRouterScriptGenerator:
    """Calls the configured OpenAI-compatible provider and validates every response."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        articles: Sequence[ArticleDocument],
        video_transcripts: Mapping[str, Sequence[TranscriptSegment]],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
    ) -> ReelScript:
        if not self.settings.llm_is_configured:
            raise LLMError("OPENROUTER_API_KEY is not configured")
        user_message = build_script_message(
            articles,
            video_transcripts,
            minimum_duration_seconds,
            maximum_duration_seconds,
        )
        allowed_source_ids = {article.source_id for article in articles} | set(video_transcripts)
        if not allowed_source_ids:
            raise LLMError("A reel requires at least one article or transcribed video source")

        client = self._create_client()
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
                    temperature=0.25,
                    max_tokens=4_000,
                )
                content = completion.choices[0].message.content
                if not content:
                    raise LLMError("The LLM returned an empty reel script")
                script = parse_reel_script(content)
                self._validate_script(
                    script,
                    allowed_source_ids,
                    minimum_duration_seconds,
                    maximum_duration_seconds,
                )
                return script
            except Exception as error:
                failures.append(str(error))
                logger.warning("Reel script attempt %s failed: %s", attempt + 1, error)
                user_message += (
                    "\nReturn only valid JSON using only supplied source IDs and durations."
                )
        raise LLMError(
            f"The LLM returned an invalid reel script after two attempts: {failures[-1]}"
        )

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

    def _validate_script(
        self,
        script: ReelScript,
        allowed_source_ids: set[str],
        minimum_duration_seconds: int,
        maximum_duration_seconds: int,
    ) -> None:
        unknown_source_ids = {
            source_id
            for sentence in script.sentences
            for source_id in sentence.source_ids
            if source_id not in allowed_source_ids
        }
        if unknown_source_ids:
            raise LLMError("The reel script referenced sources that were not provided")
        if not minimum_duration_seconds <= script.planned_duration <= maximum_duration_seconds:
            raise LLMError(
                "The reel script duration is outside the allowed range "
                f"({script.planned_duration:.1f}s; expected {minimum_duration_seconds}-"
                f"{maximum_duration_seconds}s)"
            )


def build_script_message(
    articles: Sequence[ArticleDocument],
    video_transcripts: Mapping[str, Sequence[TranscriptSegment]],
    minimum_duration_seconds: int,
    maximum_duration_seconds: int,
    maximum_characters_per_source: int = 8_000,
) -> str:
    """Serialize bounded source content for the narrative model."""
    sources: list[dict[str, object]] = []
    for article in articles:
        sources.append(
            {
                "id": article.source_id,
                "type": "article",
                "title": article.title,
                "content": article.text[:maximum_characters_per_source],
            }
        )
    for source_id, transcript in video_transcripts.items():
        text = " ".join(
            f"[{segment.start:.1f}-{segment.end:.1f}] {segment.text}" for segment in transcript
        )
        if text:
            sources.append(
                {
                    "id": source_id,
                    "type": "video_transcript",
                    "content": text[:maximum_characters_per_source],
                }
            )
    if not sources:
        raise LLMError("A reel requires usable article text or a video transcript")
    payload = {
        "duration_range_seconds": {
            "minimum": minimum_duration_seconds,
            "maximum": maximum_duration_seconds,
        },
        "sources": sources,
    }
    return "Create a news reel script from this JSON source data:\n" + json.dumps(
        payload,
        ensure_ascii=True,
    )


def parse_reel_script(content: str) -> ReelScript:
    """Validate untrusted model output before it reaches audio or video composition."""
    normalized = _CODE_FENCE.sub("", content.strip())
    try:
        return ReelScript.model_validate_json(normalized)
    except Exception as error:
        raise LLMError(
            f"The LLM response does not match the reel script schema: {error}"
        ) from error