# 20 — Observability

Goal: for any Run, the owner can answer **"Why did today's Clip fail?"** from
the UI without reading server logs. v1.0 uses persisted Run Events plus
structured logs; no external observability platform.
Architecture: [architecture/observability-architecture.md](architecture/observability-architecture.md).

## Run Event types

Canonical `RunEventType` values. Events from the project brief are marked ●;
the others are additions required for diagnosis.

| Type | Emitted when | Required payload keys |
| --- | --- | --- |
| ● `run_started` | Run begins | `trigger`, `profile_id`, `manual_url?` |
| `stage_started` | Any stage begins | `stage`, `attempt` |
| ● `research_completed` | `research` done | `references_seen`, `articles_fetched`, `articles_skipped` |
| `stories_clustered` | `cluster_stories` done | `story_candidates` |
| ● `story_selected` | `select_story` or `ingest_url` done | `story_id`, `title`, `score?`, `fallback_index` |
| ● `sources_collected` | `gather_sources` done | `article_count`, `independent_source_count`, `preferred` |
| ● `claims_extracted` | `extract_claims` done | `accepted`, `rejected`, `corroborated`, `single_source` |
| `story_package_built` | `build_story_package` done | `story_package_id`, `version` |
| ● `script_generated` | `write_script` done (gate passed) | `version`, `word_count`, `estimated_duration_seconds` |
| ● `visual_plan_generated` | `plan_visuals` done | `version`, `segments` |
| ● `assets_selected` | `select_assets` done | counts by `reused`, `acquired`, `generated`, `fallback_card` |
| ● `assets_generated` | ≥ 1 Asset acquired or generated in `select_assets` | `asset_ids`, `providers` |
| ● `audio_generated` | `generate_narration` done | `duration_seconds`, `cached` |
| `transcription_completed` | `transcribe_narration` done | `words`, `wer` |
| ● `captions_generated` | `build_captions` done | `cues`, `font_size_px` |
| ● `composition_completed` | `compose_clip` done | `clip_id`, `duration_seconds`, `render_seconds` |
| `validation_completed` | `validate_clip` done | `passed`, `issue_codes` |
| ● `evaluation_completed` | gate or `evaluate_clip` done | `layer`, `passed`, `issue_codes`, `warning_codes` |
| ● `retry_started` | `plan_retry` decides to retry | `attempt`, `reentry_stage`, `action_types`, `retries_remaining` |
| ● `publication_started` | Per platform | `platform`, `mode` |
| ● `publication_completed` | Per platform success or dry run | `platform`, `status`, `platform_url?` |
| `publication_failed` | Per platform failure | `platform`, `error_code`, `transient` |
| `publication_awaiting_approval` | Approval gate on (CF-REQ-459) | `clip_id`, `platforms`, `auto_publish_at` |
| `publication_approval_resolved` | Owner decision or timeout; may occur after `run_completed` | `clip_id`, `decision` (`approve`/`reject`), `approved_by` |
| `provider_call_failed` | A provider call fails (after its call retries) | `port`, `provider`, `operation`, `error_code`, `transient`, `call_retries` |
| `stage_failed` | A stage raises or its gate fails without retry | `stage`, `error_code`, `message` |
| `warning` | Non-blocking condition (e.g. `budget_degraded`, `no_music_available`) | `code`, `message` |
| ● `run_completed` | Run completed | `outcome`, `clip_id` |
| ● `run_failed` | Run failed | `failure_stage`, `failure_code`, `failure_message` |

## Requirements

### CF-REQ-850 — Persisted Run Events

- **Description:** The workflow shall persist Run Events of the types above,
  with per-Run strictly increasing `sequence`, in the same transaction as the
  state change they describe where practical.
- **Acceptance:**
  - A successful fake Run persists, in order, `run_started` … `run_completed`, with every ● type relevant to the path present.
  - A failed Run's last event is `run_failed` with a non-empty `failure_message`.
- **Related:** CF-REQ-654, CF-REQ-655

### CF-REQ-851 — Structured logs

- **Description:** The backend shall emit structured logs (JSON in
  production) with `timestamp`, `level`, `logger`, `message`, and, when in a
  Run context, `run_id`, `stage`, `attempt`.
- **Acceptance:**
  - Log records produced inside a stage include `run_id` and `stage` (test with a captured handler).
- **Related:** CF-NFR-106

### CF-REQ-852 — Live event stream

- **Description:** The API shall stream Run Events over Server-Sent Events
  at `GET /api/runs/{run_id}/events/stream`, using `sequence` as the SSE `id`,
  honouring `Last-Event-ID` for resumption, sending keep-alive comments every
  15 s, and closing after `run_completed` / `run_failed`.
- **Acceptance:**
  - Connecting with `Last-Event-ID: 5` delivers events from sequence 6.
- **Related:** CF-REQ-602

### CF-REQ-853 — Provider call telemetry

- **Description:** Each provider call shall be logged with port, provider,
  operation, duration, outcome, call retries and, for LLM calls, model,
  prompt template version and token usage when reported. Failed calls also
  emit `provider_call_failed`.
- **Acceptance:**
  - The Run detail API exposes total LLM tokens per Run when the fake reports usage.

### CF-REQ-854 — Stage timing

- **Description:** Stage start and end times shall be derivable from
  `stage_started` and completion events; the Run detail API returns duration
  per stage and Attempt.
- **Acceptance:**
  - Run detail lists durations for every executed stage.

### CF-REQ-855 — LLM exchange audit

- **Description:** For every LLM call, the rendered prompt and raw response
  shall be written as JSON to the Run work directory (subject to retention),
  referenced from the log entry.
- **Acceptance:**
  - After a fake Run, the work directory contains one audit file per LLM call.
- **Related:** CF-REQ-214

### CF-REQ-856 — Health endpoint

- **Description:** `GET /api/health` shall report database connectivity,
  FFmpeg/FFprobe availability, data directory writability, scheduler loop
  liveness (last tick time) and application version, returning 200 only when
  all are healthy.
- **Acceptance:**
  - With the data directory read-only, health returns 503 naming the failed check.
