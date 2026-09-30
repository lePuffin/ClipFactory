# ADR-001 — Python 3.13 and uv for the backend

- **Status:** Proposed

## Context

The backend orchestrates LLM calls, media processing, HTTP APIs and a
workflow engine. The strongest ecosystem for LLM tooling (LangGraph,
OpenAI-compatible clients), transcription (faster-whisper) and text
extraction is Python. Reproducible environments are required for CI and the
future one-shot implementation.

## Decision

- Backend language: Python ≥ 3.13.
- Environment and dependency management: `uv` with a committed `uv.lock`;
  CI installs with `uv sync --locked`.
- Quality tooling: Ruff (lint + format), Pyright, pytest (+ pytest-asyncio,
  pytest-cov), pre-commit.

## Consequences

- One tool (`uv`) for Python versions, virtualenvs, locking and running.
- Some libraries may lag on 3.13 wheels; if a required library lacks 3.13
  support, record it and choose an alternative rather than downgrading silently.
- Black, isort and Flake8 are not used (Ruff covers them).

## Alternatives considered

- Poetry / pip-tools: slower, more tools to combine.
- Node.js/TypeScript backend: weaker ML/transcription ecosystem.
- Python 3.12 (used by an earlier prototype): superseded by the brief's 3.13+ requirement.
