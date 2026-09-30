# Architecture

Canonical architecture of ClipFactory v1.0.0. Requirements take precedence
over this section; this section takes precedence over ADRs' narrative where
they differ (ADRs record *why*, this records *what*).

| Document | Content | Diagrams |
| --- | --- | --- |
| [system-architecture.md](system-architecture.md) | Context, containers, principles, prohibited technology | [system-context](diagrams/system-context.puml), [container-diagram](diagrams/container-diagram.puml) |
| [domain-architecture.md](domain-architecture.md) | Aggregates, boundaries, invariants placement | [domain-model](diagrams/domain-model.puml) |
| [application-architecture.md](application-architecture.md) | Backend packages, dependency rules, use cases, LLM usage model, configuration, HTTP API, composition | [component-diagram](diagrams/component-diagram.puml) |
| [workflow-architecture.md](workflow-architecture.md) | LangGraph graph, state, checkpoints, retry routing, Run runner, scheduler | [production-workflow](diagrams/production-workflow.puml), [research-workflow](diagrams/research-workflow.puml), [evaluation-retry-flow](diagrams/evaluation-retry-flow.puml) |
| [provider-architecture.md](provider-architecture.md) | Ports, contracts, errors, initial adapters | [publishing-flow](diagrams/publishing-flow.puml) |
| [storage-architecture.md](storage-architecture.md) | PostgreSQL schema outline, `StorageProvider`, file layout | — |
| [frontend-architecture.md](frontend-architecture.md) | SPA structure, API client, SSE | — |
| [deployment-architecture.md](deployment-architecture.md) | Runtime topology | [deployment](diagrams/deployment.puml) |
| [observability-architecture.md](observability-architecture.md) | Run Events, logs, health | — |

## Architectural principles (binding)

1. **Simplicity first.** One process, one database, one media tool. Every
   technology needs a concrete requirement.
2. **Explicit boundaries.** Domain → application (use cases, ports) →
   infrastructure (adapters) → API/UI; workflow orchestration calls use cases.
3. **Provider isolation.** External capabilities only behind ports; no vendor
   names in domain or application code.
4. **Deterministic where possible.** Code for validation, media, timing,
   scoring, routing; LLMs only for language/judgement tasks.
5. **Evidence before narrative.** Story → Sources → Claims → Script.
6. **Evaluation gates publication.** Nothing unapproved is published.
7. **Observable Runs.** Every Run explains itself through persisted events.
8. **Incremental complexity.** Abstractions exist only with a current consumer.

## Rendering diagrams

Diagrams are PlantUML sources. Render locally with
`java -jar plantuml.jar doc/specifications/architecture/diagrams/*.puml` or
the VS Code PlantUML extension. Diagrams must be updated together with the
text they illustrate.
