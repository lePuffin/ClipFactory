# 24 — Acceptance Criteria (v1.0.0 Definition of Done)

ClipFactory v1.0.0 is complete when **every** scenario below passes, all
quality gates pass (CF-NFR-153), and the traceability report shows every
`Test`-verified requirement covered by a tagged test
([traceability.md](traceability.md)). This is the final checklist of the
implementation session ([25-roadmap.md](25-roadmap.md#phase-10--final-validation)).

Unless stated otherwise, scenarios run with all providers set to `fake`,
PostgreSQL and FFmpeg real, publishing mode `dry_run`.

## Checklist

### CF-AC-001 — Research

- Given the fixture news set (≥ 40 references incl. the Reuters/AP/BBC/CNN/Blog set, a blocked publisher, stale items), when a Run starts, then at most `max_candidate_articles` articles are fetched, blocked/stale items are excluded, exact duplicates are stored once and the Blog copy is marked syndicated of Reuters.
- **Requirements:** CF-REQ-100–104, CF-REQ-118
- **Verified by:** integration + E2E-1

### CF-AC-002 — Story selection

- The syndication set forms one Story candidate with `article_count = 5`, `independent_source_count = 4`; selection is deterministic for fixed fake ratings; excluded topics and recently covered Stories are rejected with reasons visible in Run detail.
- **Requirements:** CF-REQ-105–109, CF-REQ-111
- **Verified by:** unit + E2E-1

### CF-AC-003 — Source grounding

- Additional Sources are gathered up to the preferred count; every accepted Claim has verified verbatim evidence; fabricated excerpts are unverified; support levels are correct; single-source Claims are attributed in the script; a Story with < 3 accepted Claims falls back to the next candidate.
- **Requirements:** CF-REQ-110, CF-REQ-112–117
- **Verified by:** unit + integration

### CF-AC-004 — Story Package and script

- A versioned Story Package exists; the script is in the profile language, within the word budget, 4–8 segments, hook ≤ 5 s, every segment cites accepted Claims; each script-gate failure code triggers a revision; social metadata contains source and asset attributions and disclosure flags.
- **Requirements:** CF-REQ-150–162
- **Verified by:** unit + E2E-1

### CF-AC-005 — Visual planning and asset reuse

- Each Script Segment has Visual Segments with asset requirements, deterministic motion and transitions; a second Run needing the same subject reuses the library Asset without external calls; a retired Asset is never selected; the same Asset is not used twice in one Clip.
- **Requirements:** CF-REQ-204–206, CF-REQ-211–213, CF-REQ-250–257
- **Verified by:** unit + E2E-8

### CF-AC-006 — Media acquisition, generation and provenance

- Missing media is acquired from a `MediaSourceProvider` with full provenance; invalid, oversized and low-resolution media are rejected; generation is used only when allowed, in the profile's provider order, with fallback when a provider is unreachable; real identifiable people come only from licensed real media; ComfyUI templates are validated and filled correctly; when nothing is available a deterministic title card is used; every Asset has a licence; attribution-required Assets appear in the description.
- **Requirements:** CF-REQ-200–203, CF-REQ-207–210, CF-REQ-214–217
- **Verified by:** unit + contract + integration

### CF-AC-007 — Narration, transcription and captions

- Narration is produced via `TTSProvider` (Google Chirp 3 HD, voice `en-US-Chirp3-HD-Leda` in live tests), stored as a non-reusable Asset, cached by text hash; duration gate produces actionable word deltas; transcription uses `large-v3-turbo` by default; captions use Script spelling with transcription timing, 2 centred lines within 6 % side margins, 88 % text width and 10 % bottom margin, readable box/shadow, and hostile caption text renders literally; music is selected from the local manifest-described library by metadata (no LLM), respects platform restrictions, ducks to −20 dB under narration, and its absence is only a warning.
- **Requirements:** CF-REQ-300–305, CF-REQ-310–314, CF-REQ-320–322
- **Verified by:** unit + integration

### CF-AC-008 — Evaluation and targeted retry

- Deterministic validation and semantic evaluation produce Evaluations with issues and actions; semantic evaluation uses metadata always and 5 sampled frames when visual evaluation is enabled, in one request, falling back to metadata-only if the model rejects images; a single injected `visual_irrelevant` issue on segment 2 causes re-entry at `select_assets` for segment 2 only, with no new TTS, transcription or script calls, then approval.
- **Requirements:** CF-REQ-400, CF-REQ-405–410, CF-REQ-412, CF-REQ-414, CF-REQ-415
- **Verified by:** unit + E2E-2

### CF-AC-009 — Bounded retries and no publication of failures

- With an always-failing evaluator and `max_revision_retries = 3`, the Run makes exactly 4 Attempts, fails with `evaluation_failed_after_retries`, creates no Publication, and Run detail shows the final issues.
- **Requirements:** CF-REQ-411, CF-REQ-413, CF-REQ-450, CF-REQ-655
- **Verified by:** E2E-3

### CF-AC-010 — Publishing

- In `dry_run`, Publications with status `dry_run` are created for each enabled platform without platform calls; in `live` with fakes, one platform failing yields `partially_published`; a resumed Run never re-uploads a `published` Publication; disclosure flags are mapped by adapters; with the approval gate on, nothing is published before Approve or the 10-minute timeout, Reject yields `not_published`; the Instagram and Facebook adapters receive a valid signed media URL that expires and cannot be reused after publication.
- **Requirements:** CF-REQ-451–457, CF-REQ-459–461, CF-REQ-613, CF-NFR-114
- **Verified by:** unit + integration + E2E-1, E2E-10

### CF-AC-011 — Analytics

- A published Publication gets tasks at 1 h/6 h/24 h/48 h/7 d/30 d; with a fake clock, snapshots are captured once each; missing metrics are null and shown as "n/a"; revenue is labelled estimated with its basis, or null when no basis exists.
- **Requirements:** CF-REQ-458, CF-REQ-500–506, CF-REQ-603
- **Verified by:** integration + E2E-9

### CF-AC-012 — Composition output

- The approved Clip is 720×1280, SAR 1:1, 30 FPS constant, H.264/AAC MP4 with faststart, duration = lead-in + narration + tail within 60–90 s; boundary durations 59/60/90/91 s behave as specified; the composition spec hash is stable; a corrupt Asset is quarantined and reselected.
- **Requirements:** CF-REQ-350–359, CF-REQ-401–404
- **Verified by:** unit + integration (real FFmpeg) + E2E-1

### CF-AC-013 — Dashboard and live progress

- Starting Run Now from the UI shows stage-by-stage progress via SSE without reload, survives a reconnect without duplicate/missing events, and the dashboard shows recent Runs, 7-day totals with "Estimated revenue", and the next scheduled Run.
- **Requirements:** CF-REQ-600–602, CF-REQ-608, CF-REQ-852
- **Verified by:** E2E-6 (Playwright)

### CF-AC-014 — Settings and Content Profile

- The owner edits the Content Profile and application settings; invalid values are rejected with field errors; credential status is visible without secrets; edits affect only subsequent Runs.
- **Requirements:** CF-REQ-550–555, CF-REQ-606–607, CF-REQ-750–754
- **Verified by:** E2E-7 + integration

### CF-AC-015 — Manual URL

- Submitting a valid fixture URL runs `ingest_url` then the normal pipeline to an approved Clip; private/loopback/non-HTTP URLs are rejected with 422; excluded-topic warnings do not block.
- **Requirements:** CF-REQ-609, CF-REQ-700–703
- **Verified by:** E2E-4

### CF-AC-016 — Scheduling and Runs

- With a fake clock, a Run starts at 05:00 in the profile timezone exactly once; a missed schedule within grace runs at startup; concurrent triggers produce one Run and a 409; a process kill after `write_script` resumes at `plan_visuals`; stage timeouts fail the Run with `stage_timeout`.
- **Requirements:** CF-REQ-650–660
- **Verified by:** integration + E2E-5

### CF-AC-017 — Observability ("Why did today's Clip fail?")

- For each failure code in CF-REQ-655, the Run detail page shows the failing stage, code, actionable message, the events leading to it, and relevant Evaluations; logs carry `run_id`/`stage`; LLM exchanges are auditable; health reports each dependency.
- **Requirements:** CF-REQ-604, CF-REQ-850–856
- **Verified by:** integration + E2E-3

### CF-AC-018 — Security

- SSRF, path traversal, hostile media, command-injection-shaped filenames, XSS-shaped titles, prompt-injection article text and secret-in-log tests all pass; non-loopback binding requires a token.
- **Requirements:** CF-NFR-100–114, CF-REQ-611
- **Verified by:** unit + integration

### CF-AC-019 — Testing and quality gates

- `make check` passes; CI is green; all six test categories (unit, integration, pipeline, LLM contract, rendering, failure/recovery) exist for every applicable stage; coverage is reported and the owner has set thresholds from the measured baseline; no default test needs network or credentials; every `Test`-method requirement has a tagged test.
- **Requirements:** CF-NFR-150–157
- **Verified by:** CI

### CF-AC-020 — Architecture conformance

- Architecture tests pass (layering, provider isolation, subprocess confinement, prohibited dependencies); the only runtime infrastructure is the app process, PostgreSQL, FFmpeg and the data directory; switching any provider to `fake` requires configuration only.
- **Requirements:** CF-NFR-001–003, CF-NFR-020–024, CF-REQ-751
- **Verified by:** unit (architecture tests) + review

### CF-AC-021 — Non-functional measurements

- The benchmark (CF-NFR-030) has been run on the production host for the benchmark set; the Phase 10 report contains the measurements, the derived v1.0 targets have been added to [03](03-non-functional-requirements.md) through the change process, and accessibility results meet CF-NFR-040; UI is usable at 390 px width.
- **Requirements:** CF-NFR-010–013, CF-NFR-030–033, CF-NFR-040–041, CF-NFR-050–052
- **Verified by:** measurement + review

### CF-AC-022 — Deployment and documentation

- A fresh WSL2/Linux host following [23-deployment.md](23-deployment.md) runs the system natively (no containers); backup/restore works once; `python3 scripts/check_docs.py` passes; specifications, ADRs and code agree (reviewer agent report has no open blocking findings).
- **Requirements:** CF-NFR-001, CF-NFR-051
- **Verified by:** manual + review

### CF-AC-023 — Cost governance

- Every paid call records a cost entry (reported or estimated); Run and monthly totals are correct; a call that would exceed €1.00 per Clip or €30.00 per month is not made; generation degrades to free providers, stock media or title cards with a `budget_degraded` warning; a refused LLM/TTS call fails the Run with `budget_exceeded`; scheduled Runs are skipped once the monthly limit is reached; the UI shows cost per Run/Clip and month-to-date versus limits.
- **Requirements:** CF-REQ-612, CF-REQ-661–665, CF-NFR-052
- **Verified by:** unit + integration + E2E-10

### CF-AC-024 — LLM request governance

- A first-attempt Run makes exactly 4 LLM requests (3 for Manual URL) and never more than 8; the RPM limiter holds requests beyond 20/minute; Runs do not start with fewer than 4 daily requests left and fail cleanly with `llm_budget_exhausted` when the daily 50 is reached; every request is persisted and visible in the usage API/dashboard; 400s are not retried, per-minute 429s are retried after `Retry-After`, daily 429s open the circuit until reset; the circuit fails fast and recovers via a half-open trial; no external store (Dragonfly/Redis) is used.
- **Requirements:** CF-REQ-666–671, CF-REQ-758
- **Verified by:** unit + integration + pipeline + failure/recovery tests
