"""Shared OpenAI-compatible structured-output client for the reel pipeline."""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import re
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from app.core.config import Settings
from app.core.exceptions import LLMError
from app.services.openrouter import request_with_rate_limit_retries

logger = logging.getLogger(__name__)
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAXIMUM_VISION_IMAGE_BYTES = 5_000_000


class OpenRouterJSONClient:
    """Requests JSON and retries when an untrusted response fails validation."""

    def __init__(
        self,
        settings: Settings,
        *,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.settings = settings
        self._sleeper = time.sleep if sleeper is None else sleeper

    def generate[Model: BaseModel](
        self,
        system_prompt: str,
        payload: object,
        parser: Callable[[str], Model],
        maximum_tokens: int,
        image_path: Path | None = None,
    ) -> Model:
        if not self.settings.llm_is_configured:
            raise LLMError("OPENROUTER_API_KEY is not configured")
        client = self._create_client()
        user_content = self._user_content(payload, image_path)
        failures: list[str] = []
        for attempt in range(2):
            content = self._request_with_rate_limit_retries(
                client,
                system_prompt,
                user_content,
                maximum_tokens,
            )
            try:
                if not content:
                    raise LLMError("The LLM returned an empty structured response")
                return parser(content)
            except Exception as error:
                failures.append(str(error))
                logger.warning("Reel LLM attempt %s failed: %s", attempt + 1, error)
                user_content = self._retry_content(user_content, error)
        raise LLMError(
            "The LLM returned invalid structured output after two attempts: "
            f"{failures[-1] if failures else 'unknown failure'}"
        )

    def _request_with_rate_limit_retries(
        self,
        client: object,
        system_prompt: str,
        user_content: str | list[dict[str, object]],
        maximum_tokens: int,
    ) -> str | None:
        return request_with_rate_limit_retries(
            self.settings,
            lambda: client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                temperature=0.15,
                max_tokens=maximum_tokens,
            ).choices[0].message.content,
            sleeper=self._sleeper,
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

    def _user_content(
        self, payload: object, image_path: Path | None
    ) -> str | list[dict[str, object]]:
        text = "Use this source data:\n" + json.dumps(payload, ensure_ascii=True)
        if image_path is None:
            return text
        return [
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": self._image_data_url(image_path)},
            },
        ]

    def _retry_content(
        self,
        content: str | list[dict[str, object]],
        error: Exception,
    ) -> str | list[dict[str, object]]:
        validation_failure = " ".join(str(error).split())[:2_000] or "unknown validation failure"
        instruction = (
            "\nThe previous JSON response failed validation:\n"
            f"{validation_failure}\n"
            "Return a complete corrected JSON object matching the requested schema "
            "and supplied IDs."
        )
        if isinstance(content, str):
            return content + instruction
        retry = [dict(item) for item in content]
        first = retry[0]
        first["text"] = str(first["text"]) + instruction
        return retry

    def _image_data_url(self, image_path: Path) -> str:
        if not image_path.is_file():
            raise LLMError("The local image source is unavailable for analysis")
        if image_path.stat().st_size > _MAXIMUM_VISION_IMAGE_BYTES:
            raise LLMError("The local image source is too large for vision analysis")
        mime_type, _ = mimetypes.guess_type(image_path.name)
        if not mime_type or not mime_type.startswith("image/"):
            raise LLMError("The local image source has an unsupported content type")
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"


def parse_json_model[Model: BaseModel](
    content: str,
    model_type: type[Model],
    *,
    normalizer: Callable[[object], object] | None = None,
) -> Model:
    """Parse a possibly fenced model response into a strict Pydantic record."""
    normalized = _CODE_FENCE.sub("", content.strip())
    try:
        if normalizer is not None:
            return model_type.model_validate(normalizer(json.loads(normalized)))
        return model_type.model_validate_json(normalized)
    except Exception as error:
        raise LLMError(f"The LLM response does not match the required schema: {error}") from error
