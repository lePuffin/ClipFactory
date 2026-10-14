# ADR-003 — PostgreSQL as the only durable database

- **Status:** Proposed

## Context

ClipFactory must persist domain data, Run state and events, settings,
scheduled tasks, analytics snapshots and workflow checkpoints, and must
search the Asset library by text and tags.

## Decision

Use PostgreSQL (≥ 16) as the single durable database, accessed through SQLAlchemy 2
with Alembic migrations. PostgreSQL also provides: full-text search for Asset
matching (no vector DB), `FOR UPDATE SKIP LOCKED` for scheduled tasks (no
queue), partial unique indexes for the single-active-Run rule, JSONB for
value-object lists, and storage for LangGraph checkpoints.

## Consequences

- Tests need PostgreSQL (CI service container; local compose).
- No second durable store (Redis, vector DB) — CF-NFR-002. ADR-016 permits
  disposable Dragonfly state for the rolling LLM RPM window and circuit only.
- Secrets are not stored in the database (CF-NFR-106).

## Alternatives considered

- SQLite: simpler, but weaker concurrency and no `SKIP LOCKED`; LangGraph Postgres checkpointer and full-text search features favour PostgreSQL.
- Adding a vector database for asset similarity: no demonstrated need; full-text + tags suffice for v1.0.
