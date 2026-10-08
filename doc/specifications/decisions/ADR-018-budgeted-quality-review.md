# ADR-018 — Budgeted quality review and owner-controlled publication

- **Status:** Accepted direction; owner authorized the quality plan and implementation on 2026-10-06. Numeric creative defaults remain Provisional until reference-set review.

## Context

Metadata matching and sparse final frames missed irrelevant imagery. Free-model quota exhaustion interrupted production. The owner permits paid writing/vision models within the existing money limits and selected human review first, automation later. A fifth initial call for batched candidate review was explicitly approved.

## Decision

- Extend the normal pipeline to five initial LLM tasks (four for Manual URL): ranking, Claim extraction, writing, batched candidate review, and final evaluation. Cached valid judgments can reduce calls. Keep eight total requests including all attempts/repairs/revisions; every paid call must pass request, capability and cost checks before dispatch.
- Preserve EUR 1 per Clip and EUR 30 per month limits, PostgreSQL durable accounting and Dragonfly-only operational RPM/circuit state. Verify current role-model prices/capabilities rather than treating free-tier assumptions or credential presence as proof of readiness.
- Review every final shot with bounded evidence; unresolved modality/quota/coverage remains pending, never approved from metadata alone in quality mode.
- Separate render validity, semantic/model evidence, owner decision and publication readiness. Bind reviews to exact version/hash. Retain failed Run history and reusable artifacts.
- Default rollout to explicit owner approval with indefinite hold; timeout publication is disabled. Automatic operation requires a versioned accepted benchmark and explicit opt-in, never bypassing factual/licensing/security gates.
- This supersedes the four-task topology only, not the deployment/storage choices of ADR-016. Existing accepted operations architecture remains unchanged.

## Consequences

Quality review costs and request counts must be visible and enforced. A valid video can still be pending approval. Saved-package rerenders need selective invalidation and durable review evidence, not temporary scripts or artificial successful Runs.

## Alternatives Considered

- Metadata-only selection and five evenly spaced frames: insufficient evidence for ambiguous identities and unsampled shots.
- Unlimited model iteration: violates cost and bounded-call constraints.
- Automatic timeout approval during rollout: contradicts the owner's human-review decision.
