# 25 — Implementation Roadmap

Plan for the **future** one-shot implementation session. It is not executed
in the documentation session. The orchestrating agent is
[`clipfactory`](../../.github/agents/clipfactory.agent.md).

## Rules for every phase

- Work only from the specification; conflicts go to
  [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md) before code.
- Tests first or alongside code, tagged with requirement IDs.
- End each phase with the quality gate (CF-NFR-153) for the parts that exist,
  update [traceability.md](traceability.md) status, and commit.
- Continue to the next phase automatically unless genuinely blocked
  (missing decision that has no provisional choice, failing external
  prerequisite). Never declare completion without running validation.

## Phase 0 — Specification validation

- **Objective:** Confirm the baseline is implementable as written.
- **Requirements:** all; focus on [26](26-open-decisions-and-conflicts.md).
- **Dependencies:** Owner-approved baseline.
- **Outputs:** Reviewer report (`.github/prompts/review-architecture.prompt.md`); resolved or explicitly accepted ODs; conflict C-6 fixed.
- **Tests:** `python3 scripts/check_docs.py`.
- **Acceptance:** No blocking reviewer findings; baseline status `Approved` in [01-requirements.md](01-requirements.md#status).

## Phase 1 — Repository foundation

- **Objective:** Buildable, testable skeleton with quality gates.
- **Requirements:** CF-NFR-001–003, CF-NFR-020–022, CF-NFR-150–157, CF-REQ-750–751, CF-REQ-856.
- **Dependencies:** Phase 0.
- **Outputs:** `backend/` uv project (Ruff, Pyright, pytest config, coverage), package skeleton for packages that receive code in this phase, settings loading, structured logging, composition root, health endpoint, architecture tests, `frontend/` Vite + React + TS + Tailwind + ESLint + Prettier + Vitest + Playwright, `Makefile`, `.pre-commit-config.yaml`, `.env.example`, `scripts/check_traceability.py`, CI jobs active.
- **Tests:** Architecture tests; settings validation; health endpoint; frontend smoke test.
- **Acceptance:** `make check` and CI green.

## Phase 2 — Domain and persistence

- **Objective:** Domain model, invariants, repositories, migrations.
- **Requirements:** [04-domain-model.md](04-domain-model.md) invariants, CF-REQ-550–555, CF-REQ-754, CF-NFR-013, CF-NFR-105, CF-NFR-109.
- **Dependencies:** Phase 1.
- **Outputs:** Domain entities/value objects, ports (repositories + providers), SQLAlchemy models, Alembic initial migration, repositories, `LocalStorageProvider`, seeding, fakes for all provider ports, fake clock.
- **Tests:** Unit tests for invariants; repository integration tests; migration up/down; storage path safety.
- **Acceptance:** CF-AC-014 backend parts; CF-AC-020 layering.

## Phase 3 — Research

- **Objective:** From Run start to Claims.
- **Requirements:** CF-REQ-100–118, CF-REQ-650, CF-REQ-652–655, CF-REQ-658, CF-REQ-661–663, CF-REQ-666–671, CF-REQ-758, CF-REQ-850–851, CF-REQ-853, CF-REQ-855, CF-NFR-010–011, CF-NFR-103, CF-NFR-107–108.
- **Dependencies:** Phase 2.
- **Outputs:** Safe HTTP client, `RssNewsSource` with the starter feeds verified, article extraction, dedup/syndication, clustering, scoring, gathering, claim extraction/verification, `OpenAICompatibleLLMProvider` (configured with `google/gemma-4-31b-it:free`, availability checked live) with the LLM governance wrapper (RPM limiter, daily budget, per-Run cap, usage records, selective retries, circuit breaker — CF-REQ-666–671), prompt templates for `rank_stories` and `extract_claims` with LLM-contract tests, LangGraph skeleton with research stages, Run Events, cost recording and budget checks (CF-REQ-661–663) in the shared provider wrapper.
- **Tests:** Unit for each rule; contract tests for `NewsSource` and `LLMProvider`; integration Run to `extract_claims` with fakes.
- **Acceptance:** CF-AC-001–003.

## Phase 4 — Story, script and planning

- **Objective:** Story Package, script with gate, social metadata, Visual Plan.
- **Requirements:** CF-REQ-150–162, CF-REQ-250–251, CF-REQ-253.
- **Dependencies:** Phase 3.
- **Outputs:** Planning use cases, script gate, revision input handling, visual planner.
- **Tests:** Unit for gate codes and word budget; integration Run to `plan_visuals`.
- **Acceptance:** CF-AC-004; planning parts of CF-AC-005.

## Phase 5 — Assets and production

- **Objective:** Assets selected/acquired/generated; narration, transcription, captions, music.
- **Requirements:** CF-REQ-200–217, CF-REQ-300–322, CF-REQ-664, CF-NFR-104.
- **Dependencies:** Phase 4.
- **Outputs:** Asset manager, `PexelsMediaSource`, `PixabayMediaSource`, `UnsplashMediaSource`, `WikimediaCommonsMediaSource`, media validation, title cards, `ComfyUIImageProvider`/`ComfyUIVideoProvider`, `WanLocalVideoProvider` (optional `local-gen` group), `HiggsfieldImageProvider`/`HiggsfieldVideoProvider` (API, auth and prices verified — OD-020), generation fallback and budget degradation, `GoogleTTSProvider` (Chirp 3 HD), `WhisperLocalTranscriptionProvider` (`large-v3-turbo`), alignment, caption layout, music manifest import and metadata-driven selection.
- **Tests:** Unit + contract; integration with fixture media; opt-in live tests.
- **Acceptance:** CF-AC-005–007.

## Phase 6 — Composition and evaluation

- **Objective:** Clip rendering, validation, semantic evaluation, targeted retry.
- **Requirements:** CF-REQ-252, CF-REQ-254–257, CF-REQ-350–359, CF-REQ-400–415, CF-REQ-656–657, CF-NFR-012, CF-NFR-023, CF-NFR-102.
- **Dependencies:** Phase 5.
- **Outputs:** Composition spec + command builder, media runner, validators, frame sampling, semantic evaluator (metadata + 5 frames, vision fallback), routing table, retry planner, resume behaviour.
- **Tests:** Command-builder unit tests; real-FFmpeg integration; retry scenarios; resume after kill.
- **Acceptance:** CF-AC-008, CF-AC-009, CF-AC-012.

## Phase 7 — Publishing and analytics

- **Objective:** Publications and Metric Snapshots.
- **Requirements:** CF-REQ-450–461, CF-REQ-500–506, CF-REQ-651, CF-REQ-660, CF-REQ-214, CF-NFR-114.
- **Dependencies:** Phase 6.
- **Outputs:** Publishing use case, YouTube/Instagram/TikTok/Facebook adapters (mocked HTTP tests), approval gate and `auto_publish` task, signed public media endpoint, scheduler loop, metric tasks, retention cleanup.
- **Tests:** Adapter unit tests; scheduler with fake clock; idempotency tests.
- **Acceptance:** CF-AC-010, CF-AC-011, CF-AC-016.

## Phase 8 — Frontend

- **Objective:** Complete UI.
- **Requirements:** CF-REQ-600–613, CF-REQ-659, CF-REQ-665, CF-REQ-752–753, CF-REQ-852, CF-NFR-040–041, CF-NFR-101, CF-NFR-113.
- **Dependencies:** API from Phases 3–7 (contract from [application-architecture](architecture/application-architecture.md#http-api)).
- **Outputs:** Pages, API client with generated types, SSE hook, design system, static serving by backend.
- **Tests:** Vitest component tests; Playwright E2E-6, E2E-7, E2E-8, E2E-9, E2E-10.
- **Acceptance:** CF-AC-013, CF-AC-014.

## Phase 9 — Integration

- **Objective:** Full journeys end-to-end; opt-in live smoke tests.
- **Requirements:** CF-REQ-700–703, all E2E journeys in [21-testing.md](21-testing.md#critical-e2e-journeys).
- **Dependencies:** Phases 1–8.
- **Outputs:** E2E-1 … E2E-10 green; live smoke results recorded honestly (pass / not run / failed with reason).
- **Acceptance:** CF-AC-015, CF-AC-017, CF-AC-018.

## Phase 10 — Final validation

- **Objective:** Prove v1.0.0 is complete.
- **Requirements:** everything; [24-acceptance-criteria.md](24-acceptance-criteria.md).
- **Outputs:** Validation report (`.github/prompts/validate-release.prompt.md`): quality-gate output, coverage baseline, traceability report, benchmark report (CF-NFR-030) with derived v1.0 performance targets and proposed coverage thresholds for owner approval, reviewer report, list of unverified integrations.
- **Acceptance:** CF-AC-001 … CF-AC-024 all pass; no blocking reviewer findings.
