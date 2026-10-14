---
description: "Use when writing, editing or reviewing tests for ClipFactory: pytest unit/contract/integration/e2e tests, fakes, fixtures, Vitest and Playwright tests, coverage."
applyTo: "{backend/tests/**,frontend/src/**/*.test.{ts,tsx},frontend/tests/**}"
---
# Test rules

Canonical reference: [21-testing](../../doc/specifications/21-testing.md).

- Tests are executable requirements. Never weaken, skip, `xfail` or delete a
  test to make an implementation pass. If a requirement is wrong, change the
  specification first.
- Tag every behavioural test with its requirement ID:
  `@pytest.mark.req("CF-REQ-###")`; Vitest/Playwright titles start with the ID.
- Choose the right level: pure logic → unit; port behaviour → contract suite;
  PostgreSQL/FFmpeg/FastAPI → integration; user journey → E2E.
- Use the provided fakes and the fake `Clock`. No network, credentials or
  real sleeps > 1 s in default runs. Live tests go in `backend/tests/live/`
  and are skipped unless `LIVE_TESTS=1`.
- Assert behaviour and values (e.g. exact issue codes, durations, event
  order), not just "no exception".
- Boundary tests for every numeric rule (e.g. 59/60/90/91 s durations).
- Tests are independent and order-insensitive; integration tests isolate
  database state per test.
- Fixtures: small, licence-clean, documented in `backend/tests/fixtures/README.md`.
- Every fixed defect gets a regression test.
