# System Architecture

## Context

ClipFactory is used by one owner through a browser. It depends on external
services only through provider adapters.

| External system | Purpose | Port |
| --- | --- | --- |
| News feeds / news websites | Candidate articles and article text | `NewsSource`, safe HTTP client |
| OpenAI-compatible LLM endpoint (OpenRouter initially) | Clustering, selection ratings, claims, script, visual plan, evaluation | `LLMProvider` |
| Stock/free media APIs (Pexels, Pixabay, Unsplash, Wikimedia Commons) | Photos, B-roll | `MediaSourceProvider` |
| Image/video generation: local ComfyUI, local Wan (diffusers), Higgsfield cloud | Generated visuals | `ImageProvider`, `VideoProvider` |
| Google Text-to-Speech (initially) | Narration | `TTSProvider` |
| Local Whisper (in-process library) | Word timestamps | `TranscriptionProvider` |
| YouTube, Instagram, TikTok, Facebook APIs | Publishing, metrics | `Publisher` |
| Local filesystem | Media files | `StorageProvider` |

Diagram: [diagrams/system-context.puml](diagrams/system-context.puml).

## Containers

| Container | Technology | Responsibility |
| --- | --- | --- |
| Web UI | React SPA (static files served by the backend) | Dashboard, Runs, Clips, analytics, assets, profile, settings |
| Backend | Python process: FastAPI (API + SSE + static), workflow runner (LangGraph), scheduler loop, FFmpeg final-assembly/probe runner, scoped local HyperFrames/Manim renderer subprocesses, Whisper in worker thread | All application behaviour |
| Database | PostgreSQL 16 | Domain data, Run Events, settings, scheduled tasks, LangGraph checkpoints |
| Operational state | Dragonfly | Rolling LLM requests-per-minute window and circuit-breaker state only |
| Data directory | Local filesystem | Assets, Clips, work directories, OAuth token files |

Diagram: [diagrams/container-diagram.puml](diagrams/container-diagram.puml).

There is exactly one backend process with one Uvicorn worker (CF-NFR-001).
Background work (Runs, scheduled tasks) runs as asyncio tasks in that process;
blocking work is offloaded to subprocesses or threads (CF-NFR-012).

## Why this shape

- A single user and at most one active Run make distributed execution
  unnecessary ([ADR-009](../decisions/ADR-009-single-user-v1.md), [ADR-010](../decisions/ADR-010-simple-scheduler.md)).
- PostgreSQL provides durability for scheduled tasks and workflow checkpoints;
  Dragonfly holds only disposable LLM governance state
  ([ADR-016](../decisions/ADR-016-compose-postgresql-and-dragonfly.md)).
- LangGraph provides stateful, resumable orchestration without a separate
  workflow server ([ADR-004](../decisions/ADR-004-langgraph-workflow.md)).

## Prohibited technology

Unless a new approved ADR demonstrates a concrete requirement, the following
must not be introduced (CF-NFR-002):

| Prohibited | Use instead |
| --- | --- |
| Microservices, service meshes, Kubernetes | One backend process |
| Celery, RQ, Temporal, Kafka, RabbitMQ | In-process asyncio tasks + PostgreSQL-backed scheduled tasks |
| Redis, KeyDB, general-purpose caches | PostgreSQL; content-hash file caching on disk. Dragonfly is allowed only for ADR-016's rolling LLM RPM/circuit state |
| Vector databases, a second durable database | PostgreSQL full-text search |
| Additional agent frameworks (beyond LangGraph for the workflow graph) | Structured LLM calls invoked by use cases |
| JEV; OpenShorts or OpenMontage as dependencies | Own small modules; those projects are inspiration only |

## Quality attribute strategies

| Attribute | Strategy | Requirements |
| --- | --- | --- |
| Correctness of content | Claims with verified evidence; grounded script gate; semantic grounding evaluation | CF-REQ-112–117, CF-REQ-158, CF-REQ-406 |
| Reliability | Bounded call retries, bounded revision retries, checkpoints, idempotent publishing | CF-NFR-010, CF-REQ-411, CF-REQ-657, CF-REQ-455 |
| Diagnosability | Run Events, structured logs, LLM audit files | CF-REQ-850–855 |
| Replaceability | Ports and adapters, configuration-based selection | CF-NFR-020, CF-REQ-751 |
| Security | Loopback default, token, SSRF-safe client, safe subprocess, path safety | [19-security.md](../19-security.md) |
| Testability | Fakes for all ports, fake clock, deterministic components | [21-testing.md](../21-testing.md) |
