# ADR-015 — LLM request governance in-process and in PostgreSQL (no Dragonfly)

- **Status:** Superseded by [ADR-016](ADR-016-compose-postgresql-and-dragonfly.md)

## Context

The initial LLM is a free OpenRouter model with tight limits (baseline
assumption 20 requests/minute, 50 requests/day). ClipFactory must pace
requests, enforce a daily budget, account usage persistently, retry only
when it makes sense, and stop cleanly when the budget is exhausted. During
the owner review it was suggested that Dragonfly could hold distributed
rate-limit and usage state.

## Decision

- All LLM requests go through one wrapper around `LLMProvider` that applies:
  RPM limiter, daily budget, per-Run cap, selective retries with backoff,
  schema-repair accounting and a circuit breaker (CF-REQ-666 – CF-REQ-671).
- Usage is persisted as `LLMRequest` rows in PostgreSQL; the rolling-minute
  window and circuit state live in process memory and are rebuilt from
  PostgreSQL at startup.
- Dragonfly (or Redis/KeyDB) is **not** introduced.
- The application pipeline is shaped to need at most 4 LLM requests per Clip
  on the happy path (one request per task: `rank_stories`, `extract_claims`,
  `write_script`, `evaluate_clip`).

## Consequences

- No extra service to run on the owner's WSL2 host; limits survive restarts.
- Correct only while there is a single backend process — already a v1.0
  constraint (CF-NFR-001).
- Fewer, larger LLM requests: prompts combine several outputs, so schema
  validation and repair (CF-REQ-758) matter more.
- Switching to a paid or different provider (OpenAI, Luna, Terra, local) is a
  configuration change; limits are raised in settings.

## Alternatives considered

- **Dragonfly/Redis for shared limiter state:** only useful when several
  processes or hosts share one quota. ClipFactory has one process, and
  distributed caches are prohibited without a concrete requirement
  (CF-NFR-002). Revisit with a new ADR if multiple workers are ever needed.
- **Provider-side limits only (react to 429s):** wastes scarce daily requests
  and cannot guarantee a Run has enough budget before it starts.
- **One LLM request per sub-task (≈ 10 per Clip):** exceeds the free-tier budget.
