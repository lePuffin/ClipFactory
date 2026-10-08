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
- Successful external/generated Assets are stored reusable; content-addressed
  by SHA-256 to deduplicate.
- Assets without a known licence are never used.

## Consequences

- Library quality improves over time; external calls decrease.
- Attribution text flows into Publication descriptions (CF-REQ-161).
- Library curation (retire/quarantine) is needed via the UI.

## Alternatives considered

- Always fetch fresh media: repetitive cost, no provenance history.
- Embedding-based similarity with a vector DB: no demonstrated need (CF-NFR-002).
