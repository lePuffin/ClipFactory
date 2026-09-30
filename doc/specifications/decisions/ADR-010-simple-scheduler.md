# ADR-010 — In-process, PostgreSQL-backed scheduler

- **Status:** Proposed

## Context

ClipFactory needs a daily Run (05:00 by default), metric snapshots at fixed
offsets after publication, and daily retention cleanup — all in one process,
surviving restarts, testable with a fake clock.

## Decision

Implement a small scheduler loop inside the backend process that polls a
`scheduled_task` table every `scheduler.poll_interval_seconds`, claims due
tasks with `FOR UPDATE SKIP LOCKED`, executes them, and schedules the next
daily task using `zoneinfo`. Missed tasks run late within a grace period
(daily Run) or at the next tick (metrics).

## Consequences

- Durable schedules without extra infrastructure; ~200 lines of testable code.
- Requires exactly one backend worker/replica (CF-NFR-001).
- Minute-level precision (poll interval) is sufficient.

## Alternatives considered

- Celery beat / RQ scheduler / Temporal: distributed infrastructure, prohibited.
- APScheduler: capable, but its persistent job store semantics and version transition (3.x → 4.x) add risk; the required behaviour is small.
- OS cron calling an endpoint: splits configuration outside the app; metric offsets are per publication and dynamic.
