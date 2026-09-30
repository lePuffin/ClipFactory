# Application Architecture

Diagram: [diagrams/component-diagram.puml](diagrams/component-diagram.puml).

## Backend packages

Package root: `backend/src/clipfactory/`.

| Package | Responsibility | Key contents |
| --- | --- | --- |
| `domain` | Entities, value objects, enums, pure domain services | See [domain-architecture](domain-architecture.md) |
| `ports` | Protocols for providers, repositories, clock, unit of work | `LLMProvider`, `NewsSource`, …, `RunRepository`, `Clock` |
| `research` | Use cases for stages `research` … `extract_claims`, `ingest_url` | Candidate discovery, extraction orchestration, dedup, clustering, selection, gathering, claims |
| `planning` | `build_story_package`, `write_script`, `plan_visuals`, script gate, social metadata | |
| `assets` | `select_assets`, asset manager, library search, media validation orchestration, title cards, music selection, import | |
| `production` | `generate_narration`, `transcribe_narration`, `build_captions`, alignment, caption layout | |
| `composition` | `compose_clip`: plan gate, `CompositionSpec` builder, FFmpeg command builder | |
| `evaluation` | Deterministic validators, semantic evaluator, routing, retry planner | |
| `publishing` | `publish` use case, `PublicationRequest` builder, metric task creation | |
| `analytics` | Metric collection use case, revenue estimation, aggregation queries | |
| `workflow` | LangGraph graph and nodes, Run runner, resume logic, scheduler loop, retention task | |
| `api` | FastAPI app, routers, request/response schemas, SSE, auth dependency, static files | |
| `infrastructure` | Settings, logging, DB (SQLAlchemy models, repositories, Alembic migrations), `LocalStorageProvider`, media runner (FFmpeg/FFprobe), safe HTTP client, provider adapters and fakes | |
| `prompts` | Versioned prompt templates (text files + version constant) | |
| `bootstrap.py` | Composition root: builds settings, adapters, repositories, use cases, graph, app | |
| `cli.py` | `clipfactory serve`, `clipfactory db upgrade`, `clipfactory run-now`, `clipfactory import-assets` | |

Feature packages (`research` … `analytics`) are the **application layer**.
Each exposes use-case classes with an `execute(...)` method taking IDs and
returning small result objects.

## Dependency rules

Enforced by architecture tests (CF-NFR-021):

| Package | May import |
| --- | --- |
| `domain` | Python standard library, Pydantic |
| `ports` | `domain` |
| feature packages | `domain`, `ports`, other feature packages' public use-case modules only when listed below |
| `workflow` | `domain`, `ports`, feature packages, `langgraph` |
| `api` | `domain`, `ports`, feature packages, `workflow` (runner interface), `fastapi` |
| `infrastructure` | anything except `api` and `workflow` |
| `bootstrap.py`, `cli.py` | everything |

Allowed feature-to-feature imports: `evaluation` → `production` (alignment
metrics), `publishing` → `analytics` (task creation). No other cross-feature
imports; shared logic belongs in `domain`.

Forbidden everywhere except `infrastructure`: `sqlalchemy`, `httpx`, vendor
SDKs, `subprocess`. Forbidden everywhere except `workflow` and `bootstrap`: `langgraph`.

## Use-case pattern

```text
workflow node ──► UseCase.execute(run_id, …)
                     ├─ repositories (ports) ─► load domain objects
                     ├─ providers (ports) ────► external capability
                     ├─ domain services ───────► decisions
                     ├─ repositories ─────────► persist results
                     └─ RunEventPublisher ────► events
```

Use cases do not know about LangGraph, HTTP or SQL. Nodes are thin adapters
that translate workflow state to use-case calls and results back to state.

## LLM usage model

- Every LLM task is **one structured-output call** (with bounded schema
  repair) made by a use case through `LLMProvider.generate_structured(task, messages, schema)`.
- There is no autonomous agent loop and no LLM tool-calling in the runtime
  pipeline. Code decides control flow; the LLM supplies language and judgement.
- LLM tasks in v1.0 — exactly four, one request each on the happy path
  (CF-REQ-666, [ADR-015](../decisions/ADR-015-llm-request-governance.md)):

| Task name | Stage | Output schema (summary) |
| --- | --- | --- |
| `rank_stories` | `select_story` | Merge of deterministic pre-groups; per candidate title, summary, relevance, newsworthiness, exclusion/novelty flags, rationale |
| `extract_claims` | `extract_claims` | Claims with kind, excerpts and Source IDs; contradictions; key-fact ranking; refined Story title/summary |
| `write_script` | `write_script` | Segments with text, claim IDs, attribution; social metadata text; visual plan draft (objective, asset requirement, motion, transition per segment) |
| `evaluate_clip` | `evaluate_clip` | Issues with codes, severity, evidence; scores; uses metadata plus up to 5 frames (CF-REQ-415) |

- Deterministic stages that previously could have used an LLM
  (`cluster_stories`, `ingest_url`, `plan_visuals`, `select_assets`, music
  selection) make no LLM request.

- Prompt templates live in `clipfactory/prompts/` with a version string; the
  version and model are recorded per call (CF-NFR-024).
- Untrusted text is placed in delimited data blocks (CF-NFR-108).

## Conceptual tools (internal capabilities)

ClipFactory does not use an agent "tool" framework. The capabilities that
other systems would expose as agent tools are ordinary modules called by
use cases:

| Capability | Module | Nature |
| --- | --- | --- |
| Research tools (feed reading, article fetch/extract, dedup, similarity) | `research`, `infrastructure.http`, `infrastructure.providers.news` | Deterministic + `NewsSource` |
| Media search tools | `assets` + `MediaSourceProvider` adapters | Provider |
| Asset tools (library search, validation, import, title cards) | `assets`, `infrastructure.storage` | Deterministic |
| FFmpeg tools (probe, render segment, concat, mix, burn captions, decode check) | `composition`, `infrastructure.media` (runner) | Deterministic |
| Provider tools (LLM, TTS, transcription, generation, publishing) | `ports` + `infrastructure.providers.*` | Provider |
| Validation tools (gates, validators, routing) | `evaluation`, `planning`, `domain` | Deterministic |

## Configuration

- `infrastructure/settings.py` defines `EnvironmentSettings` (pydantic-settings)
  and `ApplicationSettings` (Pydantic models per section, stored in
  `app_settings`). Keys and defaults: [18-configuration.md](../18-configuration.md).
- The composition root reads settings once at startup; use cases receive the
  Run's settings snapshot, not global singletons.

## Composition

- `composition.spec` builds a `CompositionSpec` (pure).
- `composition.ffmpeg_commands` converts a spec into argument lists (pure,
  unit-tested for exact output).
- `infrastructure.media.runner` executes argument lists safely (CF-NFR-102)
  and parses FFprobe JSON.
- Rendering steps: per-segment render (fit mode + motion) → transitions/concat
  → narration normalisation + music mix → caption burn-in → final encode →
  atomic move (CF-REQ-350–358). Intermediates are cached by segment spec hash
  in the Run work directory (CF-REQ-412).

## HTTP API

Base path `/api`. JSON bodies; errors use
`{"error": {"code": str, "message": str, "details": object?}}`. Pagination
uses `limit` (≤ 100) and opaque `cursor`. OpenAPI is generated by FastAPI and
is the frontend type source.

| Method | Path | Purpose | Requirements |
| --- | --- | --- | --- |
| GET | `/health` | Health checks (unauthenticated) | CF-REQ-856 |
| POST | `/session` | Exchange API token for session cookie | CF-NFR-101 |
| POST | `/runs` | Run Now → 202 `{run_id}`; 409 if active | CF-REQ-659, CF-REQ-652 |
| POST | `/runs/manual-url` | `{url}` → 202 `{run_id}`; 409; 422 | CF-REQ-700 |
| GET | `/runs` | List Runs (filters: status, outcome, trigger) | CF-REQ-659 |
| GET | `/runs/active` | Active Run or 204 | CF-REQ-601 |
| GET | `/runs/{id}` | Run detail: stages, timings, Story candidates, Sources, Claims, Story Package versions, Evaluations, Clips, Publications, usage | CF-REQ-604 |
| GET | `/runs/{id}/events` | Events list (`after_sequence`) | CF-REQ-850 |
| GET | `/runs/{id}/events/stream` | SSE stream | CF-REQ-852 |
| GET | `/clips` | Approved Clips with publications and latest metrics | CF-REQ-610 |
| GET | `/clips/{id}` | Clip detail | CF-REQ-610 |
| GET | `/clips/{id}/media` | MP4 with HTTP range support | CF-REQ-610 |
| POST | `/clips/{id}/approval` | `{decision}` = `approve` or `reject`, for `awaiting_approval` Clips | CF-REQ-459 |
| GET | `/budget` | Month-to-date spend, limits, remaining | CF-REQ-665 |
| GET | `/llm/usage` | LLM requests today/last minute, remaining, per task, circuit state | CF-REQ-669, CF-REQ-671 |
| GET | `/runs/{id}/costs` | Cost entries of a Run | CF-REQ-665 |
| GET/HEAD | `/public/media/{token}` (outside `/api`, unauthenticated, signed) | Clip file for URL-pull platforms | CF-REQ-461, CF-NFR-114 |
| GET | `/analytics/summary` | Totals by platform for `period=7d | 30d | all` | CF-REQ-505 |
| GET | `/analytics/publications/{id}/snapshots` | Time series | CF-REQ-505 |
| GET | `/assets` | Search/filter Assets | CF-REQ-605 |
| GET | `/assets/{id}` | Asset detail with provenance and usages | CF-REQ-605 |
| GET | `/assets/{id}/file` | Asset file (range support) | CF-REQ-605 |
| PATCH | `/assets/{id}` | Edit tags, description, status | CF-REQ-213 |
| POST | `/assets/import` | Multipart upload with provenance | CF-REQ-216 |
| GET | `/content-profile` | Active profile | CF-REQ-607 |
| PUT | `/content-profile` | Replace active profile (validated) | CF-REQ-551 |
| GET | `/settings` | Application settings + provider status | CF-REQ-752, CF-REQ-753 |
| PUT | `/settings/{section}` | Update one section | CF-REQ-752 |
| GET | `/schedule` | Next scheduled Run time | CF-REQ-601 |

## Error model

| Error class | Layer | Mapped to |
| --- | --- | --- |
| `DomainError` (invariant violation) | domain | 422 in API; stage failure in workflow |
| `ProviderError(transient, code)` | infrastructure → application | Call retry if transient; else stage failure/issue |
| `StageFailure(code, message)` | application | Run `failed` with code |
| `ConflictError` | application | 409 |
| Unexpected exception | any | Run `failed` with `internal_error`; API 500 with generic message |
