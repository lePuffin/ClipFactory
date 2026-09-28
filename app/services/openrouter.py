"""Shared retry behavior for OpenRouter requests."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping

from app.core.config import Settings
from app.core.exceptions import LLMError

logger = logging.getLogger(__name__)
_FALLBACK_RATE_LIMIT_WAIT_SECONDS = 5.0


def request_with_rate_limit_retries[Result](
    settings: Settings,
    request: Callable[[], Result],
    *,
    sleeper: Callable[[float], None] | None = None,
) -> Result:
    """Retry a server-reported OpenRouter rate limit without changing the request."""
    sleep = time.sleep if sleeper is None else sleeper
    retries = settings.llm_rate_limit_retries
    for attempt in range(retries + 1):
        try:
            return request()
        except Exception as error:
            if not _is_rate_limit_error(error):
                raise LLMError(f"The OpenRouter request failed: {error}") from error
            if attempt == retries:
                raise LLMError(
                    "The configured OpenRouter model is temporarily rate-limited. "
                    f"Retried {retries} times; try again shortly."
                ) from error
            wait_seconds = _rate_limit_wait_seconds(
                error,
                settings.llm_rate_limit_max_wait_seconds,
            )
            logger.warning(
                "OpenRouter rate limit reached; retrying in %.1f seconds (%s/%s)",
                wait_seconds,
                attempt + 1,
                retries,
            )
            sleep(wait_seconds)
    raise AssertionError("Rate-limit retry loop exited unexpectedly")


def _is_rate_limit_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    return getattr(error, "status_code", None) == 429 or getattr(
        response, "status_code", None
    ) == 429


def _rate_limit_wait_seconds(error: Exception, maximum_wait_seconds: float) -> float:
    retry_after = _retry_after_seconds(error)
    wait_seconds = _FALLBACK_RATE_LIMIT_WAIT_SECONDS if retry_after is None else retry_after
    return min(wait_seconds, maximum_wait_seconds)


def _retry_after_seconds(error: Exception) -> float | None:
    body = getattr(error, "body", None)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = None
    for payload in (body, getattr(error, "error", None)):
        retry_after = _metadata_retry_after_seconds(payload)
        if retry_after is not None:
            return retry_after

    headers = getattr(getattr(error, "response", None), "headers", None)
    get_header = getattr(headers, "get", None)
    if callable(get_header):
        retry_after = _as_wait_seconds(get_header("retry-after"))
        if retry_after is None:
            retry_after = _as_wait_seconds(get_header("Retry-After"))
        if retry_after is not None:
            return retry_after
    return None


def _metadata_retry_after_seconds(payload: object) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    for candidate in (payload, payload.get("error")):
        if not isinstance(candidate, Mapping):
            continue
        metadata = candidate.get("metadata")
        if isinstance(metadata, Mapping):
            retry_after = _as_wait_seconds(metadata.get("retry_after_seconds"))
            if retry_after is not None:
                return retry_after
    return None


def _as_wait_seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        wait_seconds = float(value)
    except (TypeError, ValueError):
        return None
    return wait_seconds if wait_seconds >= 0 else None