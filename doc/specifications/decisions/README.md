# Architecture Decision Records

Format: Status · Context · Decision · Consequences · Alternatives considered.
Statuses: `Proposed` (baseline, awaiting owner approval), `Accepted`,
`Superseded by ADR-###`. A superseding ADR must be created to change a
decision; do not edit an accepted decision's substance.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-001](ADR-001-python-and-uv.md) | Python 3.13 and uv for the backend | Proposed |
| [ADR-002](ADR-002-fastapi.md) | FastAPI for HTTP API, SSE and static UI | Proposed |
| [ADR-003](ADR-003-postgresql.md) | PostgreSQL as the only database | Proposed |
| [ADR-004](ADR-004-langgraph-workflow.md) | LangGraph as the workflow engine, kept at the edge | Proposed |
| [ADR-005](ADR-005-provider-adapters.md) | Ports and adapters for all external capabilities | Proposed |
| [ADR-006](ADR-006-local-filesystem-storage.md) | Local filesystem media storage behind `StorageProvider` | Proposed |
| [ADR-007](ADR-007-720p-mobile-first-output.md) | 720×1280, 30 FPS mobile-first output | Proposed |
| [ADR-008](ADR-008-evaluation-and-targeted-retry.md) | Two-layer evaluation and targeted, bounded retry | Proposed |
| [ADR-009](ADR-009-single-user-v1.md) | Single-user, single-profile v1.0 | Proposed |
| [ADR-010](ADR-010-simple-scheduler.md) | In-process, PostgreSQL-backed scheduler | Proposed |
| [ADR-011](ADR-011-asset-reuse-and-provenance.md) | Reusable Assets with mandatory provenance | Proposed |
| [ADR-012](ADR-012-provider-independent-tts.md) | Provider-independent TTS (Google first) | Proposed |
| [ADR-013](ADR-013-provider-independent-media-generation.md) | Provider-independent media generation; deterministic motion | Proposed |
| [ADR-014](ADR-014-source-grounded-story-claim-model.md) | Source-grounded Story / Source / Claim model | Proposed |
| [ADR-015](ADR-015-llm-request-governance.md) | LLM request governance in-process and in PostgreSQL (no Dragonfly) | Proposed |

New ADR: copy the structure of an existing one, take the next number, add it
to this table, and reference it from the affected specification sections.
