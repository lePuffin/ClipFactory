---
description: "Validate that ClipFactory v1.0.0 is complete: run every quality gate and check every acceptance scenario (Phase 10)."
agent: "clipfactory"
---
Perform the ClipFactory v1.0.0 release validation (Phase 10 of
[25-roadmap.md](../../doc/specifications/25-roadmap.md#phase-10--final-validation)).

1. Run the full [validation skill](../skills/validation/SKILL.md) (backend,
   frontend, docs, `make check`), including Playwright E2E-1 … E2E-10.
2. Run `scripts/check_traceability.py`; list every requirement with an
   automated verification method lacking a tagged passing test.
3. Walk through [24-acceptance-criteria.md](../../doc/specifications/24-acceptance-criteria.md)
   CF-AC-001 … CF-AC-024; for each, state PASS / FAIL / NOT RUN with evidence
   (test names, command output, measurement).
4. Run `clipfactory benchmark` per CF-NFR-030 on the production host; propose
   v1.0 performance targets and coverage thresholds from the measurements for
   owner approval (do not invent them); record CF-NFR-040 accessibility results.
5. List each provider adapter with status: verified live / mocked HTTP only / fake only.
6. Delegate a final review to the `reviewer` agent and include its verdict.
7. Update [traceability.md](../../doc/specifications/traceability.md) statuses to
   `Verified` only where evidence exists.

v1.0.0 is complete only if every scenario passes and the reviewer has no
blocking findings. Otherwise, report exactly what remains.
