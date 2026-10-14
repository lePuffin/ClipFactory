---
name: debugging
description: "ClipFactory debugging procedure. Use when a Run failed, a stage or test fails, FFmpeg errors, a provider call fails, evaluation keeps failing, retries are exhausted, SSE progress stalls, or the scheduler did not trigger. Answers 'why did today's Clip fail?'."
---
# Debugging skill

Observability model: [20-observability.md](../../../doc/specifications/20-observability.md),
[observability-architecture.md](../../../doc/specifications/architecture/observability-architecture.md).

## Why did a Run fail?

1. `GET /api/runs/{id}` → `failure_stage`, `failure_code`, `failure_message`.
2. Look up the code in [16-scheduling-and-runs.md § CF-REQ-655](../../../doc/specifications/16-scheduling-and-runs.md#cf-req-655--run-failure).
3. `GET /api/runs/{id}/events` → read events before `run_failed`
   (`stage_failed`, `provider_call_failed`, `evaluation_completed`, `retry_started`).
4. If evaluation-related: inspect each Attempt's Evaluations (issues, actions)
   and the [routing table](../../../doc/specifications/11-evaluation-and-retry.md#issue-routing-table-canonical).
5. If LLM-related: open `${DATA_DIR}/work/<run_id>/llm/*.json` for the prompt/response.
6. Correlate logs by `run_id` and `stage`.

## Common causes

| Symptom | Check |
|---|---|
| `no_candidates` | `research.feeds` empty (OD-003) or all feeds failing |
| `llm_invalid_output` | Model lacks structured output; see OD-001; schema repair count |
| `narration_too_short` repeatedly | Target = minimum duration (OD-002); wpm estimate vs actual voice speed |
| `caption_out_of_bounds` | Long unbreakable tokens; font/safe area settings |
| `composition_failed` | FFmpeg stderr tail in the event; FFmpeg build lacks libass/libx264 |
| Transcription crash | Whisper device/compute type (OD-007) |
| Publication `not_configured` / `unknown_outcome` | Credentials; interrupted upload — check the platform manually |
| No 05:00 Run | Scheduler disabled, timezone (OD-008), grace window, health endpoint scheduler tick |

## Procedure for code defects

1. Reproduce with fakes in a failing test tagged with the relevant ID.
2. Find the root cause (not the symptom); check if the spec is ambiguous.
3. Fix in the correct layer; keep the regression test (CF-NFR-157).
4. Run the validation skill.
