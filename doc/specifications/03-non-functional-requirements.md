# 03 — Non-Functional Requirements

General quality attributes and constraints. Security NFRs are in
[19-security.md](19-security.md) (CF-NFR-100–149); testing and quality-gate
NFRs are in [21-testing.md](21-testing.md) (CF-NFR-150–199).

## Constraints

### CF-NFR-001 — Single-host system

- **Description:** v1.0 shall run as one backend process (FastAPI + in-process
  workflow runner + in-process scheduler) with one PostgreSQL database, FFmpeg
  binaries and a local data directory. No other runtime infrastructure is required.
- **Acceptance:**
  - Following the native setup in [23-deployment.md](23-deployment.md) (backend process + PostgreSQL + FFmpeg, no containers) yields a fully working system.
- **Related:** [deployment-architecture](architecture/deployment-architecture.md), ADR-010

### CF-NFR-002 — Prohibited technology

- **Description:** The implementation shall not introduce microservices,
  Kubernetes, Celery, RQ, Temporal, Kafka, RabbitMQ, Redis, KeyDB, Dragonfly,
  service meshes, vector databases, a second database, additional agent
  frameworks (besides LangGraph for workflow), JEV, or dependencies on
  OpenShorts or OpenMontage, unless a new approved ADR demonstrates a concrete
  requirement.
- **Acceptance:**
  - A CI check fails if any prohibited package name appears in `backend/pyproject.toml` or `frontend/package.json` dependencies.
- **Related:** [system-architecture](architecture/system-architecture.md#prohibited-technology)

### CF-NFR-003 — Technology baseline

- **Description:** Backend: Python ≥ 3.13, uv, FastAPI, Pydantic v2,
  SQLAlchemy 2, Alembic, PostgreSQL (≥ 16), LangGraph, httpx, FFmpeg (≥ 6).
  Frontend: TypeScript (strict), React, Vite, Tailwind CSS. New runtime
  dependencies require a one-line justification in the PR description and,
  if architectural, an ADR.
- **Related:** ADR-001, ADR-002, ADR-003, ADR-004

## Reliability

### CF-NFR-010 — Bounded external calls

- **Description:** Every provider call shall have a timeout and be retried
  only on transient errors (network errors, timeouts, HTTP 408/429/5xx) up to
  `providers.max_call_retries`, with exponential backoff and jitter capped at
  `providers.call_retry_max_delay_seconds`, honouring `Retry-After` up to that cap.
- **Acceptance:**
  - A fake returning 429 with `Retry-After: 5` is retried after ≥ 5 s (fake clock).
  - A 400 response is not retried.
- **Related:** CF-REQ-414

### CF-NFR-011 — Bounded behaviour

- **Description:** Every loop driven by external outcomes shall be bounded:
  call retries, schema repairs, revision retries, Story fallbacks
  (CF-REQ-117), redirects, pagination, and snapshot attempts.
- **Acceptance:**
  - Each bound has a unit test demonstrating termination at the limit.

### CF-NFR-012 — Non-blocking server

- **Description:** CPU-heavy or blocking work (FFmpeg, transcription, text
  extraction, image processing) shall run outside the asyncio event loop
  (subprocess or worker thread), so API and SSE stay responsive during a Run.
- **Acceptance:**
  - During a fake Run with a 5 s blocking composition, `/api/health` responds in < 500 ms.

### CF-NFR-013 — Data integrity

- **Description:** PostgreSQL is the source of truth for metadata; schema
  changes are made only via Alembic migrations; each stage commits its domain
  writes atomically.
- **Acceptance:**
  - `alembic upgrade head` on an empty database, then `alembic downgrade base`, succeeds in CI.

## Architecture quality

### CF-NFR-020 — Provider isolation

- **Description:** Domain and application code shall depend only on port
  interfaces; third-party SDKs and HTTP details of external services appear
  only in `infrastructure/providers/*`.
- **Acceptance:**
  - An architecture test fails if `clipfactory.domain` or application packages import `httpx`, `google`, `openai`, `sqlalchemy`, `langgraph`, `fastapi` or any `infrastructure` module.
- **Related:** ADR-005, [provider-architecture](architecture/provider-architecture.md)

### CF-NFR-021 — Layer dependencies

- **Description:** Package dependencies shall follow the rules in
  [application-architecture](architecture/application-architecture.md#dependency-rules),
  enforced by an automated test.
- **Acceptance:**
  - The architecture test enumerates all imports and reports violations with file and line.

### CF-NFR-022 — Static typing

- **Description:** Pyright shall pass with `typeCheckingMode = "standard"` for
  the backend and `"strict"` for `clipfactory.domain`; TypeScript shall
  compile with `strict: true`.
- **Acceptance:**
  - CI runs `uv run pyright` and `npm run typecheck` with zero errors.

### CF-NFR-023 — Deterministic components

- **Description:** Components specified as deterministic (validators, gates,
  scoring, routing, caption layout, composition spec and command building,
  timing reconciliation) shall be pure functions of their inputs and injected
  clock, with no LLM calls and no randomness.
- **Acceptance:**
  - Tests call each twice with identical inputs and compare outputs for equality.

### CF-NFR-024 — Run reproducibility record

- **Description:** Each Run shall record the application version, FFmpeg
  version, provider names, LLM model identifiers and prompt template
  versions used.
- **Acceptance:**
  - Run detail API shows these values for a completed fake Run.

## Performance and capacity (benchmark first — OD-015)

No performance targets are set before measurement. v1.0 targets are derived
in Phase 10 from benchmarks of representative Clips on the production host
and then written back into these requirements.

### CF-NFR-030 — Benchmark methodology

- **Description:** The repository shall provide a benchmark command
  (`clipfactory benchmark`) that runs a fixed benchmark set and records timing
  and resource data per stage.
- **Behaviour:**
  - **Benchmark set:** at least 5 representative Clips: 3 from frozen fixture
    Stories (Sources stored in `backend/tests/fixtures/benchmark/`) covering
    ≈ 60 s, ≈ 75 s and ≈ 90 s narration with photo-heavy, B-roll-heavy and
    mixed visuals; 2 live Runs with real providers when credentials exist.
  - **Configurations:** (a) all fakes except FFmpeg and Whisper (local
    compute only); (b) real providers; each run with Whisper on CPU and on GPU
    where available; generation off and on.
  - **Measurements per Run:** wall time per stage and total; LLM requests
    and latency per task; TTS latency; transcription real-time factor;
    composition time and encode speed (× real time); peak RSS and GPU memory;
    Clip size and bitrate; cost entries.
  - **Protocol:** host description recorded (CPU, RAM, GPU, OS, FFmpeg and
    model versions); one warm-up run discarded; each fixture measured 3×;
    report median and max; results written as JSON + Markdown under
    `${DATA_DIR}/benchmarks/<timestamp>/`.
- **Acceptance:**
  - The command produces the report for configuration (a) in CI-like conditions without network access.
  - Phase 10 adds measured targets to this document through the change process (01-requirements.md).

### CF-NFR-031 — Fake-provider end-to-end duration is measured

- **Description:** CI shall record the duration of the fake-provider
  end-to-end Run test in the job summary so a baseline exists; no threshold
  until Phase 10.
- **Acceptance:**
  - CI job summary shows the E2E-1 duration.

### CF-NFR-032 — API responsiveness is measured

- **Description:** The benchmark shall include a seeded-database API
  measurement (1 000 Runs, 10 000 Assets) reporting p50/p95 latency of the
  non-media endpoints; targets are set in Phase 10.
- **Acceptance:**
  - The benchmark report contains the p50/p95 table.

### CF-NFR-033 — Clip size is measured

- **Description:** The benchmark shall report file size and average bitrate
  per Clip at default encoding settings; a size target is set in Phase 10.
- **Acceptance:**
  - The benchmark report lists size and bitrate for every benchmark Clip.

## Usability

### CF-NFR-040 — Accessibility and browsers

- **Description:** The UI shall meet WCAG 2.1 AA colour contrast in the dark
  theme, be operable by keyboard, and support the latest two versions of
  Chromium-based browsers, Firefox and Safari.
- **Acceptance:**
  - Playwright + axe-core check reports no serious/critical violations on each page.

### CF-NFR-041 — UI language [Derived]

- **Description:** The UI text shall be English in v1.0; content language
  is independent (Content Profile).
- **Acceptance:**
  - Changing profile language does not change UI labels.

## Portability and operations

### CF-NFR-050 — Supported environments

- **Description:** Linux x86_64 is the production target. Development on
  Linux and Windows via WSL2 is supported; macOS is best-effort.
- **Acceptance:**
  - CI runs on `ubuntu-latest`.

### CF-NFR-051 — Backup and restore

- **Description:** Backup shall consist of a PostgreSQL dump plus the data
  directory; the procedure is documented and restorable to a new host.
- **Acceptance:**
  - [23-deployment.md](23-deployment.md#backup-and-restore) procedure tested once during Phase 10.

### CF-NFR-052 — Cost visibility

- **Description:** Each Run shall record LLM token usage per call and in
  total when reported by the provider, the number of TTS characters
  synthesised, generated media units, and the resulting cost entries
  (CF-REQ-661).
- **Acceptance:**
  - Run detail shows usage and cost totals for a fake Run whose fakes report usage.
- **Related:** CF-REQ-661, CF-REQ-665
