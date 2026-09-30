# Workflow Architecture

Decision: [ADR-004](../decisions/ADR-004-langgraph-workflow.md), [ADR-008](../decisions/ADR-008-evaluation-and-targeted-retry.md), [ADR-010](../decisions/ADR-010-simple-scheduler.md).
Behaviour: [16-scheduling-and-runs.md](../16-scheduling-and-runs.md).
Diagrams: [production-workflow](diagrams/production-workflow.puml),
[research-workflow](diagrams/research-workflow.puml),
[evaluation-retry-flow](diagrams/evaluation-retry-flow.puml).

## Components

| Component | Responsibility |
| --- | --- |
| `RunService` | Creates Runs (enforcing single active Run with a DB lock/partial unique index), snapshots profile/settings, starts the runner |
| `WorkflowRunner` | Owns the compiled LangGraph graph; runs one Run as an asyncio task; applies stage timeout; converts exceptions to Run failure; resumes interrupted Runs at startup |
| Graph nodes | One node per `Stage`; each calls exactly one use case and returns a state update |
| `RetryPlanner` (evaluation package) | Pure: from failed Evaluations + state → re-entry stage, Actions, or failure |
| `Scheduler` | In-process loop over `scheduled_task` rows |
| `RunEventPublisher` | Persists Run Events and notifies SSE subscribers in-process |

## Workflow state

The LangGraph state is a small typed model (CF-REQ-658):

| Field | Type | Purpose |
| --- | --- | --- |
| `run_id` | UUID | |
| `trigger` | `RunTrigger` | Chooses `research` vs `ingest_url` entry |
| `story_id` | UUID? | Selected Story |
| `story_fallbacks_used` | int | ≤ 2 (CF-REQ-117) |
| `story_package_id` | UUID? | |
| `story_package_version` | int? | |
| `attempt` | int | Starts at 1 |
| `revision_retries_used` | int | |
| `pending_actions` | list[`Action`] | Instructions for the re-entered stage |
| `reentry_stage` | `Stage`? | Set by `plan_retry` |
| `affected_segments` | list[int] | Segments to redo in `select_assets` / render cache |
| `clip_id` | UUID? | Current candidate |
| `last_evaluation_ids` | list[UUID] | |
| `outcome` | `RunOutcome`? | |

Everything else is loaded through repositories.

## Graph

```text
START ─► route_entry ─┬─► research ─► cluster_stories ─► select_story ─┐
                      └─► ingest_url ───────────────────────────────────┤
                                                                         ▼
                       gather_sources ──(insufficient sources & fallback left)──► select_story
                              │
                              ▼
                       extract_claims ──(insufficient claims & fallback left)──► select_story
                                              │
                                              ▼
                     build_story_package ─► write_script ──(gate fail)──► plan_retry
                                              │
                                              ▼
                     plan_visuals ─► select_assets ─► generate_narration ──(gate fail)──► plan_retry
                                              │
                                              ▼
                     transcribe_narration ─► build_captions ─► compose_clip ──(plan gate fail / asset_render_failed)──► plan_retry
                                              │
                                              ▼
                     validate_clip ──(fail)──► plan_retry
                                              │ pass
                                              ▼
                     evaluate_clip ──(fail)──► plan_retry
                                              │ pass (Clip approved)
                                              ▼
                     publish ─► END (run_completed)

plan_retry ──(retries left)──► <re-entry stage>
plan_retry ──(exhausted or abort)──► END (run_failed)
```

- Conditional edges read only state fields and Evaluation `passed` flags.
- `plan_retry` increments `attempt` and `revision_retries_used`, sets
  `reentry_stage` = earliest target stage among blocking issues
  (CF-REQ-410), and stores `pending_actions`.
- When `select_story` has no eligible candidate, or a stage raises
  `StageFailure`, the runner ends the Run as `failed`.

## Artefact reuse on re-entry

| Re-entry stage | Re-executed | Reused if inputs unchanged |
| --- | --- | --- |
| `gather_sources` | All following stages | Assets already in library (via reuse-first) |
| `write_script` | Script and all following | Visual segments/Assets for unchanged Script Segments; narration cache if text identical |
| `plan_visuals` | Plan and following | Narration, transcription, captions (script unchanged) |
| `select_assets` | Affected segments only, then composition onward | Narration, transcription, captions, other segments' renders |
| `generate_narration` | Narration and following | Visual Plan, Assets |
| `compose_clip` | Composition and evaluation | Everything else |

## Checkpointing and resumption

- LangGraph's PostgreSQL checkpointer stores state after each node in the same
  database (separate tables managed by the checkpointer package).
- `thread_id = run_id`.
- On startup, `WorkflowRunner` lists Runs with `status = running`: if
  `workflow.resume_interrupted_runs`, it resumes from the latest checkpoint
  (the interrupted node re-runs; nodes must therefore be idempotent with
  respect to their persisted outputs); otherwise it fails them with `interrupted`.
- Node idempotency rule: a node first checks whether its output for
  (`run_id`, `attempt`, stage) already exists and, if so, returns it.

## Concurrency and blocking work

- One Run at a time, as one asyncio task.
- FFmpeg and FFprobe: `asyncio.create_subprocess_exec` via the media runner.
- Whisper transcription, text extraction and image measurement: `asyncio.to_thread`.
- Stage timeout: `asyncio.timeout(workflow.stage_timeout_seconds)` around each
  node; subprocesses are killed on cancellation.

## Scheduler

- Table `scheduled_task(id, kind, due_at, payload, status, attempts, last_error, created_at, updated_at)`.
- Kinds: `daily_run`, `metric_snapshot`, `retention_cleanup`, `auto_publish` (CF-REQ-460).
- Loop every `scheduler.poll_interval_seconds`:
  1. Select due `pending` tasks ordered by `due_at` with `FOR UPDATE SKIP LOCKED`.
  2. Mark `running`; execute; mark `done` or `failed` (bounded attempts).
  3. After a `daily_run`, create the next one from the profile schedule
     (computed with `zoneinfo`, DST rules per CF-REQ-651).
- On profile schedule change, the pending `daily_run` task is replaced.
- `retention_cleanup` runs daily (CF-REQ-214).
- The loop records its last tick for the health endpoint (CF-REQ-856).
