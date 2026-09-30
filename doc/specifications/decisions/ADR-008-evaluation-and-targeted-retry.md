# ADR-008 — Two-layer evaluation and targeted, bounded retry

- **Status:** Proposed

## Context

Autonomous publishing requires confidence that a Clip is technically valid
and editorially acceptable. Rerunning the whole pipeline on every failure
wastes money and time and discards good work.

## Decision

- Evaluation has stage gates, deterministic validation (code) and semantic
  evaluation (one structured LLM call). A Clip is approved iff there are no
  blocking issues; LLM scores are metrics only.
- Issues carry codes; a fixed code table maps codes to a target stage and
  Action type ([11-evaluation-and-retry.md](../11-evaluation-and-retry.md#issue-routing-table-canonical)).
- On failure the workflow re-enters the earliest affected stage, passing
  Actions as instructions, reusing unchanged artefacts via content hashes.
- Revision retries are bounded (`workflow.max_revision_retries`, default 3);
  provider call retries are separate.
- Only approved Clips can be published.

## Consequences

- Predictable, testable retry behaviour; each routing row has a test.
- The semantic evaluator must use known issue codes (schema-enforced).
- Some quality problems may exhaust retries and fail the Run — by design.

## Alternatives considered

- Single LLM score threshold: opaque, not actionable, brittle.
- Full pipeline rerun on failure: wasteful, changes good parts.
- LLM-decided routing: non-deterministic and hard to test.
