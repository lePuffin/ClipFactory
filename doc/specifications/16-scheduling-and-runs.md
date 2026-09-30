# 16 — Scheduling, Runs and Workflow Execution

A Run is one execution of the production workflow. Architecture:
[architecture/workflow-architecture.md](architecture/workflow-architecture.md),
diagram [production-workflow.puml](architecture/diagrams/production-workflow.puml).
Decisions: [ADR-004](decisions/ADR-004-langgraph-workflow.md),
[ADR-010](decisions/ADR-010-simple-scheduler.md).

## Stages

Canonical `Stage` enum, in pipeline order. Names are used verbatim in code,
Run Events, API and UI.

| # | Stage | Produces | Spec |
| --- | --- | --- | --- |
| 1 | `research` | Candidate Sources | [05](05-research-and-source-grounding.md) |
| 1′ | `ingest_url` | Source + Story candidate from a Manual URL (replaces 1–2) | [17](17-manual-input.md) |
| 2 | `cluster_stories` | Story candidates | [05](05-research-and-source-grounding.md) |
| 3 | `select_story` | Selected Story | [05](05-research-and-source-grounding.md) |
| 4 | `gather_sources` | Additional evidence Sources | [05](05-research-and-source-grounding.md) |
| 5 | `extract_claims` | Claims with evidence | [05](05-research-and-source-grounding.md) |
| 6 | `build_story_package` | Story Package, key facts | [06](06-story-and-script.md) |
| 7 | `write_script` | Script + social metadata text; script gate | [06](06-story-and-script.md) |
| 8 | `plan_visuals` | Visual Plan | [08](08-visual-production.md) |
| 9 | `select_assets` | Selected Assets (reuse / acquire / generate / card), music | [07](07-asset-management.md) |
| 10 | `generate_narration` | Narration Asset; narration gates | [09](09-audio-and-tts.md) |
| 11 | `transcribe_narration` | Word timings, WER | [09](09-audio-and-tts.md) |
| 12 | `build_captions` | Caption Track, reconciled segment timing | [09](09-audio-and-tts.md), [08](08-visual-production.md) |
| 13 | `compose_clip` | Plan gate, Clip candidate | [10](10-composition.md) |
| 14 | `validate_clip` | Deterministic Evaluation | [11](11-evaluation-and-retry.md) |
| 15 | `evaluate_clip` | Semantic Evaluation; Clip approved or rejected | [11](11-evaluation-and-retry.md) |
| 16 | `plan_retry` | Re-entry decision (only after a failure) | [11](11-evaluation-and-retry.md) |
| 17 | `publish` | Publications, metric tasks | [12](12-publishing.md) |

## Requirements

### CF-REQ-650 — Run triggers

- **Description:** A Run shall be created by exactly one trigger:
  `scheduled` (daily schedule), `run_now` (UI/API), or `manual_url`
  (UI/API with URL).
- **Acceptance:**
  - Each trigger creates a Run with the matching `trigger` value and emits `run_started`.

### CF-REQ-651 — Daily schedule

- **Description:** When the active profile's `schedule.enabled` is true, the
  scheduler shall trigger a Run daily at `schedule.local_time` in
  `schedule.timezone` (default 05:00 Europe/Lisbon).
- **Behaviour:** The scheduler is an in-process loop polling persisted
  scheduled tasks every `scheduler.poll_interval_seconds`. A daily task missed
  while the application was down runs at startup if less than
  `scheduler.missed_run_grace_minutes` late; otherwise it is skipped and
  logged. Non-existent local times (DST gaps) run at the next valid minute;
  repeated local times (DST overlap) run once.
- **Acceptance:**
  - With a fake clock at 04:59:50 → 05:00:20 (poll 30 s), exactly one Run is created.
  - Restarting the app at 05:30 (grace 60) creates the missed Run; at 06:30 it does not.
  - Changing `local_time` to 06:15 reschedules the next task accordingly.
- **Related:** ADR-010, OD-008

### CF-REQ-652 — Single active Run

- **Description:** At most one Run shall be `queued` or `running` at a time.
- **Behaviour:** Run Now / Manual URL while a Run is active returns HTTP 409
  with the active Run ID. A scheduled trigger while a Run is active is skipped
  with a warning log and a skipped-task record.
- **Acceptance:**
  - Two concurrent Run Now requests produce one Run and one 409 (enforced by a database constraint or lock, not only in memory).

### CF-REQ-653 — Run snapshot

- **Description:** At start, a Run shall store an immutable snapshot of the
  active Content Profile and effective application settings, and use only the
  snapshot for its whole execution, including resumptions.
- **Acceptance:**
  - Changing `workflow.max_revision_retries` during a Run does not change that Run's limit.
- **Related:** CF-REQ-555

### CF-REQ-654 — Stage execution

- **Description:** The workflow shall execute stages in the order of the
  stage table, update `Run.current_stage`, and emit the stage's completion
  Run Event (see [20-observability.md](20-observability.md#run-event-types)).
- **Acceptance:**
  - A successful fake Run emits events whose stage order matches the table (with `ingest_url` only for manual URL Runs).

### CF-REQ-655 — Run failure

- **Description:** A Run that cannot produce an approved Clip shall end
  `failed` with `failure_stage`, machine-readable `failure_code` and an
  actionable `failure_message`, and emit `run_failed`.
- **Behaviour:** Known failure codes include `no_candidates`,
  `no_suitable_story`, `insufficient_sources`, `insufficient_claims`,
  `llm_invalid_output`, `provider_unavailable`, `composition_failed`,
  `composition_defect`, `evaluation_failed_after_retries`, `stage_timeout`,
  `interrupted`, `internal_error`, `budget_exceeded` (CF-REQ-664), `llm_budget_exhausted` (CF-REQ-668), `llm_unavailable` (CF-REQ-671), and for Manual URL Runs `url_unreachable`,
  `url_not_article`, `url_blocked_source` (CF-REQ-701).
- **Acceptance:**
  - Every failure code has a test producing it with fakes.
  - An unexpected exception results in `internal_error` with the exception type (not the full stack) in the message and the stack in the log.

### CF-REQ-656 — Stage timeout

- **Description:** A stage running longer than `workflow.stage_timeout_seconds`
  shall be cancelled and the Run failed with `stage_timeout`.
- **Acceptance:**
  - A fake provider sleeping beyond a 1 s timeout (test setting) fails the Run with `stage_timeout`.

### CF-REQ-657 — Resumption after restart

- **Description:** On startup, Runs left `running` shall be resumed from the
  last completed stage when `workflow.resume_interrupted_runs` is true;
  otherwise marked `failed` with `interrupted`.
- **Acceptance:**
  - Killing the process after `write_script` and restarting resumes at `plan_visuals` without a new LLM script call.
- **Related:** ADR-004, CF-REQ-455

### CF-REQ-658 — Lean workflow state

- **Description:** The workflow state object shall contain only identifiers
  and small control data (Run ID, Story Package ID and version, Attempt,
  pending Actions, re-entry stage). Domain data is read from and written to
  repositories.
- **Rationale:** Keeps LangGraph a replaceable orchestration detail and
  checkpoints small.
- **Acceptance:**
  - A test asserts the state model's fields are limited to the documented set.
- **Related:** ADR-004

### CF-REQ-659 — Run APIs

- **Description:** The API shall provide: start Run Now (202 + Run ID), start
  Manual URL Run (202 + Run ID), get active Run, list Runs (paginated,
  filterable by status/outcome/trigger), get Run detail.
- **Acceptance:**
  - Endpoint contract tests per [HTTP API](architecture/application-architecture.md#http-api).
- **Related:** CF-REQ-608, CF-REQ-609

### CF-REQ-660 — Scheduler can be disabled

- **Description:** `SCHEDULER_ENABLED=false` shall prevent the
  scheduler loop from starting (Run Now and Manual URL still work).
- **Acceptance:**
  - With the flag false, no scheduled task is executed even when due.

## Cost governance

Owner decision (2026-09-28, OD-016): record usage, show cost in the UI, and
never spend above the per-Clip and monthly limits set in Settings.

### CF-REQ-661 — Cost recording

- **Description:** Every paid provider call shall produce a `CostEntry` with
  provider, operation, quantity and amount in `budget.currency`, using the
  provider-reported cost when available (`basis = reported`) and otherwise the
  `budget.price_table` estimate (`basis = estimated`). USD prices are
  converted with `budget.usd_to_currency_rate`. Free/local providers record
  nothing.
- **Acceptance:**
  - A fake LLM reporting cost 0.004 USD with rate 0.92 records 0.00368 EUR, basis `reported`.
  - 3 000 TTS characters at 16 USD / 1 M chars record 0.04416 EUR, basis `estimated`.
  - `Run.cost_total` equals the sum of its entries.
- **Related:** CF-NFR-052, OD-020

### CF-REQ-662 — Per-Clip cost limit

- **Description:** Before any paid provider call, the system shall estimate
  its cost and refuse the call if the Run's spent amount plus the estimate
  would exceed `budget.max_cost_per_clip`.
- **Behaviour:** The limit applies to one Run (all Attempts of its Clip).
  Refusal triggers degradation (CF-REQ-664).
- **Acceptance:**
  - With a limit of 1.00 EUR, 0.95 EUR spent and a 0.10 EUR estimate, the call is not made.
  - With a limit of 0, no paid call is ever made.

### CF-REQ-663 — Monthly cost limit

- **Description:** Before any paid provider call, the system shall refuse the
  call if the month-to-date spend (calendar month in the profile timezone)
  plus the estimate would exceed `budget.max_cost_per_month`. When the monthly
  limit is already reached, scheduled Runs are skipped (warning log and
  skipped-task record) and Run Now / Manual URL return HTTP 409 with code
  `budget_exhausted`.
- **Acceptance:**
  - With 30.00 EUR spent in September, a scheduled Run on 30 September is skipped; on 1 October it runs.

### CF-REQ-664 — Degrade before failing

- **Description:** When a paid call is refused by a limit, the stage shall use
  a free alternative where one exists, emit a `warning` event
  `budget_degraded`, and continue; if no free alternative exists, the Run
  fails with `budget_exceeded`.
- **Behaviour:** Free alternatives in order: generation → next free provider
  in the profile order, then library/stock media, then title card
  (CF-REQ-208, CF-REQ-209); revision retries that would require paid calls are
  not started. LLM and TTS calls have no free alternative in v1.0 and fail the
  Run with `budget_exceeded`.
- **Acceptance:**
  - A refused Higgsfield call falls back to a title card and the Run completes with a `budget_degraded` warning.
  - A refused script LLM call fails the Run with `budget_exceeded` at `write_script`.

### CF-REQ-665 — Cost visibility API

- **Description:** The API shall expose cost per Run (entries and total) and
  a budget summary: month-to-date spend, monthly limit, per-Clip limit, and
  remaining amounts.
- **Acceptance:**
  - `GET /api/budget` returns month-to-date spend equal to the sum of the month's entries.
- **Related:** CF-REQ-612

## LLM request governance

The initial LLM is a free OpenRouter model, treated as a constrained
resource (baseline assumption: 20 requests/minute, 50 requests/day; OD-021).
All LLM requests pass through one shared wrapper in the `LLMProvider`
adapter layer that enforces the rules below for every provider, so moving to
another provider or model changes only configuration. State lives in
PostgreSQL and process memory; no external store is used
([ADR-015](decisions/ADR-015-llm-request-governance.md)).

| # | LLM task | Stage | Replaces |
| --- | --- | --- | --- |
| 1 | `rank_stories` | `select_story` | clustering merge + story rating |
| 2 | `extract_claims` | `extract_claims` | per-Source claim calls + key-fact ranking + Manual URL summary |
| 3 | `write_script` | `write_script` | script + social metadata + visual plan draft |
| 4 | `evaluate_clip` | `evaluate_clip` | semantic + visual evaluation (5 frames) |

Manual URL Runs skip task 1 (3 requests). Asset choice, music selection,
visual planning normalisation and issue routing make no LLM request.

### CF-REQ-666 — LLM requests per Clip

- **Description:** A Run that passes every gate and evaluation on its first
  Attempt shall make at most `llm.target_requests_per_clip` (4) LLM requests,
  one per task in the table above. Every Run shall stop making LLM requests at
  `llm.max_requests_per_run` (default 8), counting schema repairs, call
  retries and revision retries.
- **Failure:** Reaching the per-Run cap fails the Run with `llm_budget_exhausted`
  at the current stage.
- **Acceptance:**
  - A fake end-to-end Run that passes first time records exactly 4 `LLMRequest` rows (3 for Manual URL).
  - A Run whose evaluator always fails stops at 8 requests.
  - Run detail reports requests used versus target and cap.

### CF-REQ-667 — Requests-per-minute limiter

- **Description:** LLM requests shall be paced so that no more than
  `llm.requests_per_minute` are started in any rolling 60-second window.
- **Behaviour:** A request that would exceed the limit waits (bounded by the
  stage timeout) instead of being sent. The window is initialised from
  persisted `LLMRequest` rows at startup, so restarts do not reset it.
- **Acceptance:**
  - With a fake clock and limit 2, the third request in a minute starts only after the first leaves the window.

### CF-REQ-668 — Daily request budget

- **Description:** The system shall count LLM requests per day (day boundary
  in `llm.daily_reset_timezone`, default UTC) from persisted records and never
  start a request beyond `llm.requests_per_day`.
- **Behaviour:** A Run (scheduled, Run Now or Manual URL) starts only if at
  least `llm.min_daily_requests_to_start_run` requests remain; otherwise
  scheduled Runs are skipped with a warning and Run Now / Manual URL return
  409 `llm_budget_exhausted`. If the budget runs out mid-Run, the Run fails
  with `llm_budget_exhausted` (artefacts kept; not resumed automatically).
- **Acceptance:**
  - With 47 requests used today and a minimum of 4, Run Now returns 409.
  - At 00:00 UTC the count resets and a Run can start.

### CF-REQ-669 — Persistent usage accounting

- **Description:** Every LLM request attempt (including repairs, retries and
  requests refused by the limiter) shall be persisted as an `LLMRequest`
  record with task, model, outcome, HTTP status, token usage, reported cost
  and relevant rate-limit response headers.
- **Acceptance:**
  - `GET /api/llm/usage` returns today's count, remaining daily requests, last-minute count and per-task totals matching the records.
  - The dashboard shows today's LLM requests used / limit (CF-REQ-612).

### CF-REQ-670 — Bounded, non-blind LLM retries

- **Description:** LLM retries shall be selective and bounded: retry only
  network errors, timeouts, HTTP 408/5xx and HTTP 429 that indicates a
  per-minute limit; never retry 400/401/403/404, context-length or
  content-policy errors, or 429 indicating the daily/credit limit. Retries use
  exponential backoff with jitter (`providers.call_retry_*`), honour
  `Retry-After` up to the cap, re-check the RPM limiter and daily budget
  before each attempt, and count against all limits.
- **Acceptance:**
  - A 400 response makes exactly 1 request.
  - A per-minute 429 with `Retry-After: 5` is retried after ≥ 5 s (fake clock) and both attempts are recorded.
  - A daily-limit 429 is not retried and opens the circuit until the daily reset (CF-REQ-671).

### CF-REQ-671 — Circuit breaker and exhaustion handling

- **Description:** The LLM wrapper shall open a circuit after
  `llm.circuit_failure_threshold` consecutive transient failures (for
  `llm.circuit_open_seconds`) or on a daily-limit response (until the next
  daily reset). While open, requests fail immediately with
  `ProviderError(code = llm_unavailable)` without contacting the provider;
  after the open period one trial request is allowed (half-open).
- **Behaviour:** A stage whose LLM request fails with `llm_unavailable` fails
  the Run with that code (evaluation never approves without its request,
  CF-REQ-405). The circuit state and reason are shown on the dashboard and in
  the health endpoint (degraded, not down).
- **Acceptance:**
  - After 3 consecutive fake timeouts, the 4th request fails in < 10 ms without a provider call.
  - After 300 s (fake clock) a single trial request is sent; success closes the circuit.
