# ADR-021 — Durable FIFO Run admission with serial execution

- **Status:** Accepted (owner requested 2026-10-15)

## Context

The owner revised CF-REQ-652 to retain additional Run Now, Manual URL and
scheduled orders instead of rejecting requests or skipping schedules while a
Run executes. The previous queued-or-running constraint forbids that behavior.

## Decision

Persist each accepted order as a queued Run with its selected profile,
Manual URL and effective settings snapshots. Use the existing PostgreSQL
database and in-process worker, not a second durable store or queue service.
Dispatch in ascending creation-time order, with Run ID breaking ties.

Serialize admission and claiming with a PostgreSQL transaction advisory lock.
Before claiming, check that no Run is running; retain a partial unique index
on a constant for running rows only. SQLite test stores use an immediate
write transaction in place of the advisory lock.

The single worker awaits the owned Run task, including stop/terminal cleanup,
before dispatching again. Startup handles the interrupted running Run before
claiming pending orders. Queued cancellation removes only that order from
execution. Explicit failed-Run continuation retains CF-REQ-657's safeguards;
it is not a fresh trigger and does not bypass its active-work conflict.

The existing Run APIs expose pending orders via the queued status filter
in FIFO order. The active endpoint returns the executing Run when present,
otherwise the oldest queued order. Run Now and Manual URL UI admission stays
available during another Run, while duplicate pending submissions remain disabled.

This supersedes only the single queued-or-running admission clauses of
ADR-003 and ADR-009; their database, single-user and process choices remain.

## Consequences

- Migration `0009_serial_run_queue` narrows the unique index without
  rewriting historical snapshots or deleting orders.
- Downgrading requires draining the queue first; the older constraint
  rejects coexisting active orders rather than discarding them.
- Multiple backend workers or replicas remain unsupported: interrupted-Run
  recovery assumes one process owns execution.
- Existing URL validation, profile selection, budgets, approval and
  publication safeguards remain unchanged.

## Alternatives considered

- In-memory queue: loses accepted orders on restart.
- Parallel workflow execution: violates serial execution and shared local
  resource ownership.
- A separate queue service: unnecessary infrastructure for this single-process
  application and contrary to the existing architecture.
