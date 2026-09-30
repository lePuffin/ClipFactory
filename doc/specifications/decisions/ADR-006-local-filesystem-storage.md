# ADR-006 — Local filesystem media storage behind StorageProvider

- **Status:** Proposed

## Context

Media files (Assets, Clips, intermediates) are large and processed by FFmpeg,
which needs local file paths. The system runs on one host.

## Decision

Store media on the local filesystem under `DATA_DIR` using the
layout in [storage-architecture](../architecture/storage-architecture.md),
accessed only through `StorageProvider` (`LocalStorageProvider` in v1.0).
Asset files are content-addressed by SHA-256. Metadata lives in PostgreSQL.

## Consequences

- Simple, fast, no cloud costs; backups = database dump + directory copy.
- Media is not publicly reachable; platforms requiring a public URL (Instagram, Facebook) need a separate decision (OD-009).
- An object-storage adapter can be added later without changing use cases.

## Alternatives considered

- S3-compatible object storage now: adds infrastructure and credentials with no v1.0 requirement.
- Storing media in PostgreSQL: poor fit for large binary files and FFmpeg processing.
