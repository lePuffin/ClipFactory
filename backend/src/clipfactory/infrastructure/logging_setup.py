"""Process-wide log configuration (CF-REQ-851)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

_CONTEXT_FIELDS = ("run_id", "stage", "attempt")


class _ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        context = " ".join(
            f"{field}={getattr(record, field)}" for field in _CONTEXT_FIELDS if getattr(record, field, None) is not None
        )
        if not context:
            return line
        head, newline, rest = line.partition("\n")
        return f"{head} [{context}]{newline}{rest}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, log_format: Literal["json", "console"]) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter() if log_format == "json" else _ConsoleFormatter())
    logger = logging.getLogger("clipfactory")
    logger.handlers[:] = [handler]
    logger.setLevel(level.upper())
    logger.propagate = False
