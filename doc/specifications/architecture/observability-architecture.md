# Observability Architecture

Requirements: [20-observability.md](../20-observability.md).

## Signals

| Signal | Store | Consumer |
| --- | --- | --- |
| Run Events | `run_event` table | Run detail API, SSE, dashboard |
| Structured logs | stdout (JSON in production), optionally redirected to `${DATA_DIR}/logs/` | Operator (terminal running `clipfactory serve`) |
| LLM audit files | `work/<run_id>/llm/*.json` | Debugging prompts/responses |
| Evaluations | `evaluation` table | Run detail, retry planner |
| Health | `/api/health` | Operator, container health check |

No metrics backend, tracing system or log aggregation service in v1.0.

## Event flow

```text
use case / node ──► RunEventPublisher.emit(run_id, type, payload)
                       ├─► INSERT run_event (next sequence, in current transaction)
                       └─► after commit: notify in-process subscribers (asyncio queues per SSE client)
SSE endpoint ──► on connect: replay events with sequence > Last-Event-ID, then stream live
```

In-process notification suffices because there is one process
(no Redis/pub-sub; CF-NFR-002). Subscribers are bounded queues; a slow
client is disconnected and resumes via `Last-Event-ID`.

## Logging

- Library: standard `logging` configured with a JSON formatter (e.g.
  `structlog` or a small custom formatter — implementation choice, one only).
- Context variables (`contextvars`) carry `run_id`, `stage`, `attempt` into
  every record emitted inside a Run.
- A redaction filter removes configured secret values and auth headers (CF-NFR-106).

## "Why did today's Clip fail?"

The Run detail API composes: `failure_stage`/`failure_code`/`failure_message`,
the last N events before `run_failed`, failed Evaluations per Attempt with
issues and actions, provider call failures, and stage timings. The UI shows
this at the top of the Run detail page (CF-REQ-604).
