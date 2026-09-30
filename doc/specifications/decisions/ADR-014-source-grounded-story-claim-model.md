# ADR-014 — Source-grounded Story / Source / Claim model

- **Status:** Proposed

## Context

News Clips must be factual and attribution-aware across all categories,
including politics. A `search → LLM summary → video` design cannot show why a
statement is in a script, cannot distinguish syndicated copies from
independent reporting, and invites fabricated facts.

## Decision

- Model `Story`, `Source` (with `origin_publisher` and syndication), and
  `Claim` with `Evidence` excerpts linked to Sources.
- Count Articles and independent Sources separately; minimum 1, preferred 3
  independent Sources (configurable).
- Verify evidence excerpts verbatim in code; compute support levels in code;
  reject unsupported Claims; require attribution for single-source and
  contested Claims.
- Scripts cite Claim IDs per segment; the script gate and semantic grounding
  evaluation enforce it.
- The Story Package is the single input for production stages.

## Consequences

- More LLM calls (claim extraction) and more data, but every scripted fact is traceable to Source text.
- Manual URL Runs reuse the same model (CF-REQ-702).

## Alternatives considered

- Summarise-then-script: simpler, ungrounded.
- Retrieval with embeddings: unnecessary for 10–20 articles; adds a vector store.
