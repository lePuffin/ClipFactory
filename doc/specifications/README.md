# ClipFactory Specifications

**Baseline:** v1.0.0 (draft for owner review)
**Status:** Partial application exists; v1.0 acceptance is not complete. Owner-authorized news-explainer quality extension started 2026-10-06; typed local graphics direction was authorized 2026-10-08. New requirement/acceptance definitions are not evidence of implemented or validated features.

This directory is the **canonical specification** of ClipFactory. Everything a
future implementation agent needs to build v1.0.0 lives here. Nothing outside
`doc/specifications/` is normative, except that the agent environment
(`AGENTS.md`, `.github/`) must stay consistent with it.

## Source-of-truth hierarchy

When two artefacts disagree, the higher one wins:

1. Approved requirements (`CF-REQ-*`, `CF-NFR-*`) — documents `02`–`21`
2. Approved architecture — [architecture/](architecture/README.md)
3. Approved ADRs — [decisions/](decisions/README.md)
4. Tests
5. Implementation
6. Informal assumptions and comments

A conflict must never be resolved silently. Record it in
[26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md),
update the losing artefact (or raise an Open Decision), then implement.

## Reading order

| Order | Document | Purpose |
| --- | --- | --- |
| 1 | [00-project-overview.md](00-project-overview.md) | What ClipFactory is, the pipeline, scope |
| 2 | [glossary.md](glossary.md) | Canonical terminology (mandatory) |
| 3 | [01-requirements.md](01-requirements.md) | Requirement format, ID ranges, conventions |
| 4 | [04-domain-model.md](04-domain-model.md) | Canonical entities, fields, invariants, state machines |
| 5 | [architecture/README.md](architecture/README.md) | Architecture overview and diagrams |
| 6 | Topic specifications `05`–`20` | Functional requirements by pipeline area |
| 7 | [03-non-functional-requirements.md](03-non-functional-requirements.md), [19-security.md](19-security.md), [21-testing.md](21-testing.md) | Non-functional requirements |
| 8 | [22-development-workflow.md](22-development-workflow.md), [23-deployment.md](23-deployment.md) | How to build, validate and run |
| 9 | [24-acceptance-criteria.md](24-acceptance-criteria.md), [traceability.md](traceability.md) | Definition of "v1.0.0 complete" |
| 10 | [25-roadmap.md](25-roadmap.md) | Phased plan for the future implementation session |
| 11 | [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md) | Everything intentionally undecided or conflicting |

## Document map

| File | Content | Canonical for |
| --- | --- | --- |
| [00-project-overview.md](00-project-overview.md) | Purpose, scope, pipeline, non-goals | Scope and non-goals |
| [01-requirements.md](01-requirements.md) | Requirement conventions | ID scheme and requirement format |
| [02-functional-requirements.md](02-functional-requirements.md) | Map of `CF-REQ` blocks to documents and pipeline stages | Nothing (map only) |
| [03-non-functional-requirements.md](03-non-functional-requirements.md) | General NFRs (`CF-NFR-001`–`099`) | General quality attributes and constraints |
| [04-domain-model.md](04-domain-model.md) | Entities and value objects | Domain model |
| [05-research-and-source-grounding.md](05-research-and-source-grounding.md) | Research, dedup, clustering, selection, sources, claims | Research and grounding |
| [06-story-and-script.md](06-story-and-script.md) | Story Package, script, social metadata | Script and Story Package |
| [07-asset-management.md](07-asset-management.md) | Asset library, reuse, provenance, acquisition | Assets |
| [08-visual-production.md](08-visual-production.md) | Visual plan, typed graphics, local rendering, motion | Visual planning and graphics routing |
| [09-audio-and-tts.md](09-audio-and-tts.md) | TTS, transcription, captions, music | Audio and captions |
| [10-composition.md](10-composition.md) | FFmpeg composition and output format | Composition |
| [11-evaluation-and-retry.md](11-evaluation-and-retry.md) | Validation, semantic evaluation, targeted retry | Evaluation and retry |
| [12-publishing.md](12-publishing.md) | Publisher abstraction and platform adapters | Publishing |
| [13-analytics.md](13-analytics.md) | Metric Snapshots, estimated revenue | Analytics |
| [14-content-profiles.md](14-content-profiles.md) | Content Profile | Editorial configuration |
| [15-ui-and-dashboard.md](15-ui-and-dashboard.md) | Web UI | UI |
| [16-scheduling-and-runs.md](16-scheduling-and-runs.md) | Runs, workflow execution, scheduler | Runs and workflow behaviour |
| [17-manual-input.md](17-manual-input.md) | Manual news URL | Manual input |
| [18-configuration.md](18-configuration.md) | Settings, environment variables, defaults | Configuration keys and defaults |
| [19-security.md](19-security.md) | Security requirements | Security |
| [20-observability.md](20-observability.md) | Run events, logs | Observability |
| [21-testing.md](21-testing.md) | Test strategy and quality gates | Testing |
| [22-development-workflow.md](22-development-workflow.md) | Repo layout, tooling, commands, CI | Development workflow |
| [23-deployment.md](23-deployment.md) | Runtime environment | Deployment |
| [24-acceptance-criteria.md](24-acceptance-criteria.md) | v1.0.0 completion checklist | Definition of done |
| [25-roadmap.md](25-roadmap.md) | Implementation phases | Implementation order |
| [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md) | Open decisions, known conflicts | Open decisions |
| [glossary.md](glossary.md) | Terms | Terminology |
| [traceability.md](traceability.md) | Requirement → component → verification | Traceability |
| [architecture/](architecture/README.md) | Architecture and PlantUML diagrams | Architecture |
| [decisions/](decisions/README.md) | ADR-001 … ADR-019 | Decisions |

## Rules for maintaining these documents

- **One canonical home per fact.** Other documents link to it instead of
  restating it. Configuration defaults are canonical in
  [18-configuration.md](18-configuration.md); entity fields in
  [04-domain-model.md](04-domain-model.md).
- **Requirement IDs are stable.** Never renumber or reuse an ID. Retired
  requirements keep their ID with status `Retired`.
- **No silent requirement changes.** Changing behaviour means changing the
  requirement first, then [traceability.md](traceability.md), then tests, then code.
- **"Open Decision" not "TBD".** Anything intentionally undecided is an
  `OD-###` entry in [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md).
- **Terminology.** Use [glossary.md](glossary.md) terms. The produced video is
  always a **Clip**.
- **Validate.** Run `python3 scripts/check_docs.py` after editing (see
  [22-development-workflow.md](22-development-workflow.md#documentation-validation)).
