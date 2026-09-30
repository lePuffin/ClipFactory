# ADR-002 — FastAPI for HTTP API, SSE and static UI

- **Status:** Proposed

## Context

The UI needs a REST API, a live progress stream, media streaming with range
requests, and serving of the built SPA. The backend is asyncio-based because
of I/O-heavy provider calls and in-process background work.

## Decision

Use FastAPI (with Uvicorn) and Pydantic v2 for request/response models.
Live progress uses Server-Sent Events (via a streaming response). The built
frontend is served by the same app in production.

## Consequences

- OpenAPI schema is generated automatically and used to generate frontend types.
- One process serves API, SSE, media and UI — consistent with CF-NFR-001.
- SSE is one-way; all commands use REST. WebSockets are not needed.

## Alternatives considered

- Django: heavier, sync-first ORM conflicts with SQLAlchemy choice.
- Flask/Quart: less built-in validation and OpenAPI.
- WebSockets for progress: bidirectional channel not required; SSE has built-in resume via `Last-Event-ID`.
