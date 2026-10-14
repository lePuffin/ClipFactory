---
name: testing
description: "ClipFactory testing procedure. Use when choosing a test level, writing pytest/Vitest/Playwright tests, building fakes or media fixtures, tagging tests with requirement IDs, testing FFmpeg output, SSE, scheduler with fake clock, or checking coverage and traceability."
---
# Testing skill

Canonical: [21-testing.md](../../../doc/specifications/21-testing.md).

## Choose the level

| What you test | Level | Notes |
|---|---|---|
| Pure rule (duration bounds, scoring, routing, caption layout, command builder) | Unit | Table-driven, boundary values |
| A port implementation | Contract | Shared suite in `backend/tests/contract/`, run for fake + real adapter |
| Adapter HTTP mapping | Unit with mocked HTTP (`httpx.MockTransport`) | Never real network |
| Repository, migration, SQL constraint | Integration | PostgreSQL; isolate state per test |
| FFmpeg rendering/probing | Integration | Small generated fixtures; assert probe values |
| API endpoint / SSE | Integration | FastAPI test client / async client |
| Workflow path | Integration/E2E with all fakes | Assert event sequence and final state |
| UI component | Vitest + Testing Library | |
| User journey | Playwright against app with fakes | E2E-1 … E2E-10 |

## Patterns

- Tag: `@pytest.mark.req("CF-REQ-###")` (multiple allowed). Vitest/Playwright: ID first in title.
- Fake clock for scheduler, retention, backoff (`Retry-After`) — no real sleeping.
- Fake LLM: scripted responses per task; inject invalid JSON / transient / permanent errors to test CF-REQ-758 and CF-NFR-010.
- Fake TTS: duration = words × 60 / wpm so duration gates are testable exactly.
- Media fixtures: generate with FFmpeg (`testsrc2`, `sine`, `anullsrc`); keep total ≤ 20 MB; document in `backend/tests/fixtures/README.md`.
- Assert exact issue codes, failure codes and event types from the spec.

## Coverage

- Required categories and policy in [21-testing.md](../../../doc/specifications/21-testing.md#required-test-categories): unit, integration, pipeline, LLM contract, rendering, failure/recovery. Mark tests with the category marker.
- Coverage is reported but no threshold is enforced until Phase 10 ([CF-NFR-152](../../../doc/specifications/21-testing.md#cf-nfr-152--coverage-policy)). Never write assertion-free tests to raise numbers.
- Requirement coverage beats line coverage: run `scripts/check_traceability.py` (after Phase 1) to list untested IDs.

## Never

- Skip/xfail/delete a failing test to get green.
- Depend on test order, wall-clock time, network or credentials.
