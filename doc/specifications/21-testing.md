# 21 — Testing and Quality Gates

Tests are executable requirements. Do not weaken, skip or delete a test to
make an implementation pass; change the requirement first if the behaviour
must change ([01-requirements.md](01-requirements.md#changing-requirements)).

## Required test categories

Every category is mandatory in v1.0; coverage thresholds come later
(CF-NFR-152). A test belongs to one category, tagged with a pytest marker of
the same name (`unit`, `integration`, `pipeline`, `llm_contract`, `rendering`,
`failure_recovery`) or the matching folder for frontend tests.

| Category | What it proves | Examples |
| --- | --- | --- |
| **Unit** | Pure rules and components in isolation | Duration bounds, scoring, routing table rows, word budget, caption layout, frame sampling times, ducking envelope, music selection, cost estimation, limiter arithmetic, React components |
| **Integration** | Real infrastructure boundaries | PostgreSQL repositories and migrations, FastAPI endpoints incl. SSE and signed media URLs, adapters against mocked HTTP (ComfyUI, Higgsfield, OpenRouter, platforms), scheduler with fake clock |
| **Pipeline** | Whole workflow paths with all providers `fake` | Scheduled / Run Now / Manual URL Runs end to end, targeted retry paths, story fallback, approval gate, degradation under budget |
| **LLM contract** | Each of the 4 LLM tasks is well-formed and within budget | Prompt template renders for fixtures; recorded model outputs validate against the task schema; invalid/partial outputs trigger exactly one repair; request count per Run ≤ 4 on the happy path; images attached only to `evaluate_clip`; opt-in live check against the configured model |
| **Rendering** | FFmpeg output is correct | Motion filters, transitions, fit modes, captions (bounds, escaping, contrast), ducking, loudness, output format and probe values, frame extraction |
| **Failure / recovery** | The system fails safely and resumes | Provider transient/permanent errors, 429 per-minute vs daily, circuit breaker, daily/Run LLM caps, cost limits, stage timeout, process kill and resume, interrupted publication, corrupt media quarantine |

## Test levels

| Level | Location | Scope | External dependencies |
| --- | --- | --- | --- |
| Unit | `backend/tests/unit/`, `frontend/src/**/*.test.ts(x)` | Domain rules, validators, gates, scoring, routing, caption layout, composition spec/commands, provider adapters with mocked HTTP, React components/hooks | None |
| Contract | `backend/tests/contract/` | One shared test suite per port run against every implementation (fakes always; real adapters only when opted in) | None by default |
| Integration | `backend/tests/integration/` | PostgreSQL repositories and migrations, FastAPI endpoints (incl. SSE), FFmpeg/FFprobe runner and composition with fixture media, workflow persistence/resume, scheduler with fake clock | PostgreSQL, FFmpeg |
| End-to-end | `backend/tests/e2e/` (API level) and `frontend/tests/e2e/` (Playwright) | Critical user journeys against a running app with all providers `fake` | PostgreSQL, FFmpeg, browser |
| Live (opt-in) | `backend/tests/live/` | Real provider smoke tests | Credentials; `LIVE_TESTS=1` |

## Fakes

Every port has a deterministic fake in `clipfactory/infrastructure/providers/fakes/`,
selectable via configuration (`fake`), used by tests and local demo mode:

| Port | Fake behaviour |
| --- | --- |
| `LLMProvider` | Returns scripted responses keyed by task name; can inject invalid JSON, transient and permanent errors, per-minute and daily 429s, image rejection; reports token usage and cost |
| `NewsSource` | Serves fixture articles from `backend/tests/fixtures/news/` including the Reuters/AP/BBC/CNN/Blog syndication set |
| `MediaSourceProvider` | Serves fixture images/videos with provenance, including invalid and oversized cases |
| `ImageProvider` / `VideoProvider` | Renders a deterministic gradient image/clip with FFmpeg |
| `TTSProvider` | Generates a tone/silence WAV with duration `words × 60 / wpm` |
| `TranscriptionProvider` | Returns script words with evenly distributed timestamps; can inject substitutions |
| `Publisher` | Records requests, returns configured results; fake metrics |
| `StorageProvider` | The real local implementation on a temporary directory (no fake needed) |
| Clock | Injectable `Clock` with a controllable fake for scheduler and retention tests |

## Critical E2E journeys

| ID | Journey | Covers |
| --- | --- | --- |
| E2E-1 | Run Now → research → selection → production → evaluation pass → dry-run publication → dashboard shows completed | CF-AC-001 … CF-AC-012 |
| E2E-2 | Evaluation fails once (fake) → targeted retry → pass | CF-AC-008 |
| E2E-3 | Evaluation always fails → Run failed after max retries, no publication, Run detail shows why | CF-AC-009 |
| E2E-4 | Manual URL → same pipeline → approved Clip | CF-AC-015 |
| E2E-5 | Scheduled Run at 05:00 with fake clock | CF-AC-016 |
| E2E-6 | Live progress over SSE, reconnect | CF-AC-013 |
| E2E-7 | Edit Content Profile and settings; invalid input rejected | CF-AC-014 |
| E2E-8 | Asset library: reused Asset in second Run; retire Asset | CF-AC-005 |
| E2E-9 | Metric snapshot collection and analytics page with estimated revenue label | CF-AC-011 |
| E2E-10 | Approval gate on + low budget: generation degrades with `budget_degraded`, Clip awaits approval, dashboard shows cost and countdown, auto-publish after timeout (fake clock) | CF-AC-010, CF-AC-023 |

## Requirement tagging

Tests declare the requirements they verify with a pytest marker:

```python
@pytest.mark.req("CF-REQ-401")
def test_clip_duration_boundaries(...): ...
```

Vitest/Playwright tests include the ID in the test title: `it("CF-REQ-611 renders source titles as text", …)`.
`scripts/check_traceability.py` (created in Phase 1) lists requirements with
no tagged test; Phase 10 requires that list to be empty except for
requirements explicitly verified by review (marked `Review` in
[traceability.md](traceability.md)).

## Requirements

### CF-NFR-150 — Mandatory tests for behaviour

- **Description:** Every implemented requirement whose verification method
  in [traceability.md](traceability.md) includes an automated test level
  (`Unit`, `Contract`, `Integration`, `E2E`, `Vitest`, `Playwright`) shall
  have at least one automated test tagged with its ID. Requirements verified
  only by `CI`, `Review`, `Measurement` or `Manual` are checked by those means.
- **Acceptance:**
  - `check_traceability.py` reports zero untested `Test`-method requirements at release.

### CF-NFR-151 — Normal CI needs no external services

- **Description:** Default test runs shall not require internet access,
  provider credentials or paid APIs. Live tests are skipped unless
  `LIVE_TESTS=1`.
- **Acceptance:**
  - CI runs with no provider secrets configured and passes.

### CF-NFR-152 — Coverage policy

- **Description:** Coverage shall be measured and reported (backend branch
  coverage with `pytest-cov`, frontend line coverage with Vitest) from Phase 1,
  but **no threshold is enforced** until the baseline implementation exists.
  In Phase 10 the owner sets thresholds from the measured baseline (OD-017)
  and they are then enforced in CI. Every required test category must contain
  tests for the parts of the system it covers regardless of coverage numbers.
- **Acceptance:**
  - CI publishes coverage reports without failing on a threshold before Phase 10.
  - Each of the six categories has at least one test per applicable pipeline stage (checked by marker count per package in the Phase 10 report).

### CF-NFR-153 — Quality gate commands

- **Description:** A change is complete only when these pass:

  ```bash
  # backend (from backend/)
  uv run ruff check .
  uv run ruff format --check .
  uv run pyright
  uv run pytest

  # frontend (from frontend/)
  npm run lint
  npm run typecheck
  npm run test
  npm run build

  # documentation (from repository root)
  python3 scripts/check_docs.py
  ```

  `make check` at the repository root runs all of them.
- **Acceptance:**
  - CI runs the same commands (see [22-development-workflow.md](22-development-workflow.md#continuous-integration)).

### CF-NFR-154 — Test isolation and determinism

- **Description:** Tests shall be independent and order-insensitive; each
  integration test uses a transaction rollback or a fresh schema; time is
  controlled with the fake clock; no test sleeps on real time for more than 1 s.
- **Acceptance:**
  - Running the suite with `-p randomly` (or reversed order) passes.

### CF-NFR-155 — Media fixtures

- **Description:** Media fixtures shall be small (total ≤ 20 MB), licence-clean
  (generated by FFmpeg or CC0) and documented in
  `backend/tests/fixtures/README.md` with their origin.
- **Acceptance:**
  - Fixture README lists every fixture file with origin and licence.

### CF-NFR-156 — Architecture tests

- **Description:** The backend suite shall include architecture tests
  enforcing CF-NFR-020, CF-NFR-021, CF-NFR-002 and CF-NFR-102.
- **Acceptance:**
  - Introducing `import httpx` into `clipfactory/domain` makes the suite fail.

### CF-NFR-157 — Regression tests for defects

- **Description:** Every fixed defect shall get a regression test reproducing it.
- **Acceptance:**
  - Reviewer checklist item; PR template question.
