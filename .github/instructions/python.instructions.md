---
description: "Use when writing or editing Python backend code for ClipFactory: domain, ports, use cases, providers, FastAPI, SQLAlchemy, Alembic, LangGraph workflow, FFmpeg runner."
applyTo: "backend/**/*.py"
---
# Python backend rules

Canonical references: [application-architecture](../../doc/specifications/architecture/application-architecture.md),
[provider-architecture](../../doc/specifications/architecture/provider-architecture.md),
[04-domain-model](../../doc/specifications/04-domain-model.md).

## Language and style

- Python ≥ 3.13, full type hints, Pyright-clean (`strict` in `clipfactory.domain`).
- Ruff is the only formatter/linter. No Black/isort/Flake8.
- Pydantic v2 for validation models; SQLAlchemy 2 typed ORM (`Mapped[...]`).
- `async` for I/O; blocking work via `asyncio.to_thread` or subprocess (CF-NFR-012).
- Time via the injected `Clock`; never `datetime.now()` in domain or use cases.
- Comments only for what the code cannot say.

## Layering (enforced by architecture tests)

- `domain`: stdlib + Pydantic only. No I/O.
- `ports`: Protocols only.
- Feature packages (`research`, `planning`, `assets`, `production`,
  `composition`, `evaluation`, `publishing`, `analytics`): use cases depending
  on `domain` and `ports`.
- `workflow`: the only place importing `langgraph` (besides `bootstrap.py`).
- `infrastructure`: the only place importing `sqlalchemy`, `httpx`, vendor
  SDKs or `subprocess`.
- `api`: FastAPI routers and schemas; no business logic.

## Providers

- New external capability ⇒ adapter in `infrastructure/providers/<port>/`,
  a fake, and the shared contract tests. Convert vendor errors to
  `ProviderError(transient, code, message)` without secrets.
- Use the shared resilience wrapper for timeouts and call retries.
- LLM calls: `generate_structured` with a Pydantic schema and a versioned
  prompt template from `clipfactory/prompts/`; untrusted text in delimited data blocks.

## Safety

- Outbound HTTP to external URLs only via the safe HTTP client (CF-NFR-103).
- FFmpeg/FFprobe only via the media runner with argument lists (CF-NFR-102).
- Storage keys only through `StorageProvider` (CF-NFR-105).
- No f-string SQL (CF-NFR-109). No secrets in logs (CF-NFR-106).

## Errors and events

- Raise `DomainError`, `ProviderError`, `StageFailure` as specified; never
  swallow exceptions silently.
- Emit Run Events from [20-observability](../../doc/specifications/20-observability.md#run-event-types) with the required payload keys.
