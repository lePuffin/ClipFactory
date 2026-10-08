# ADR-016 — Compose-managed PostgreSQL and Dragonfly for local operation

- **Status:** Accepted — owner approved 2026-10-01
- **Supersedes:** [ADR-015](ADR-015-llm-request-governance.md)

## Context

ClipFactory needs reproducible local dependency setup and conservative LLM
request governance. ADR-015 kept the rolling requests-per-minute window and
circuit-breaker state in process memory because the backend is a single
process. The owner explicitly approved adding Dragonfly on 2026-10-01 while
retaining the single native backend process and PostgreSQL durability.

## Decision

- Docker Compose manages PostgreSQL 16 and Dragonfly for local development
  and the owner's WSL2 deployment. It does not run the backend, frontend,
  FFmpeg or provider adapters.
- PostgreSQL remains the only durable source of truth. Domain data, settings,
  Run Events, scheduled tasks, LangGraph checkpoints, LLM request records and
  daily usage accounting remain in PostgreSQL.
- Dragonfly is a disposable operational state store used only for the rolling
  LLM requests-per-minute window and LLM circuit-breaker state. It stores no
  domain data, workflow state, daily usage totals or credentials.
- The backend remains one native Python process with one Uvicorn worker.
- `DRAGONFLY_URL` configures the dependency. If Dragonfly is unavailable,
  LLM calls fail closed before contacting a provider; the service reports the
  dependency failure and does not silently fall back to process-local state.
- The local operational CLI contract is `clipfactory setup`,
  `clipfactory doctor` and `clipfactory run` (CF-REQ-755 – CF-REQ-757).

## Consequences

- Local setup gains one Compose-managed service and requires Docker with the
  Compose plugin.
- Restarting or deleting Dragonfly may discard circuit state. The rolling
  window is rebuilt from durable `LLMRequest` rows in PostgreSQL before LLM
  traffic resumes; circuit state may restart closed because it is explicitly
  transient.
- Backups and restores include PostgreSQL and `DATA_DIR`; Dragonfly is not
  backed up.
- Tests must prove that Dragonfly contains only namespaced rolling-window and
  circuit keys and that an unavailable Dragonfly prevents provider calls.

## Alternatives considered

- **Process memory plus PostgreSQL (ADR-015):** fewer services, but does not
  provide the approved local operational boundary for shared limiter state.
- **Run the backend in Compose:** rejected; native execution keeps the current
  development workflow and single-process architecture.
- **Persist usage or workflow state in Dragonfly:** rejected; it would create
  a second durable source of truth and complicate backup and recovery.
- **Redis or KeyDB:** no additional requirement; Dragonfly is the approved
  implementation for this narrowly scoped state.
