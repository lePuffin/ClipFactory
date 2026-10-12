# ADR-011 — Reusable Assets with mandatory provenance

- **Status:** Proposed

## Context

Daily Clips repeatedly need similar visuals (institutions, places, generic
topics). Acquiring or generating media costs time and money, and licensing
obligations (attribution) must be honoured.

## Decision

- Assets are first-class domain objects stored in a library with metadata
  (description, tags, subjects, quality, usage) and mandatory `Provenance`
  (origin, provider, licence, source URL, author, attribution, generation info).
- `select_assets` searches the library first (PostgreSQL full-text + tags,
  deterministic match score), then external providers, then permitted generation. Owner revision (2026-10-07, CF-REQ-209): unavailable suitable media enters bounded reselection and owner review, not an automatic plain-colour title card. Explicit saved-content revisions may still render photo-backed cards; original outputs remain immutable.
- Owner revision (2026-10-11, CF-REQ-200/211/214): generated/rendered Assets
  remain saved and reusable; external provider downloads are non-reusable,
  Run-scoped inputs removed at production end. Retired metadata preserves
  attribution and stock history. Legacy files are not bulk-deleted. Content
  addressing still deduplicates metadata by SHA-256.
- Assets without a known licence are never used.

## Consequences

- Generated library quality improves over time; external inputs are downloaded
  per Run rather than retained for cross-Run reuse.
- Attribution text flows into Publication descriptions (CF-REQ-161).
- Library curation (retire/quarantine) is needed via the UI.

## Alternatives considered

- Always fetch fresh media: repetitive cost, no provenance history.
- Embedding-based similarity with a vector DB: no demonstrated need (CF-NFR-002).
