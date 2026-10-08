# 00 — Project Overview

## Purpose

ClipFactory is a private, single-user application that autonomously produces
and publishes vertical news **Clips**. Every day (and on demand) it
researches recent news, selects one Story, grounds that Story in independent
Sources and extracted Claims, writes a source-grounded script, plans and
sources visuals, generates narration and captions, composes a vertical video,
evaluates it, revises it when necessary, publishes approved Clips to the
platforms enabled in the active Content Profile, and collects
post-publication metrics.

The initial editorial use case is global news narrated in English. Category,
language, geography, duration and platforms are Content Profile settings, not
code ([14-content-profiles.md](14-content-profiles.md)).

## Intended user

One private owner operating one deployment. There are no tenants, roles, or
public sign-up ([ADR-009](decisions/ADR-009-single-user-v1.md)).

## Canonical pipeline

The pipeline below is normative. Stage names are canonical and are used in
Run Events, workflow node names, UI progress, and Evaluation issue routing
(see [16-scheduling-and-runs.md](16-scheduling-and-runs.md#stages) for the
stage table).

```text
Scheduler (05:00 daily) / Run Now / Manual URL
        │
        ▼
    research ──────────────── (manual URL: ingest_url replaces research + clustering)
        │
        ▼
    cluster_stories          deduplicate articles, group into Story candidates
        │
        ▼
    select_story             score candidates, select one Story
        │
        ▼
    gather_sources           add independent Sources for the selected Story
        │
        ▼
    extract_claims           Claims + verbatim evidence per Source
        │
        ▼
    build_story_package      Story + Sources + Claims + key facts
        │
        ▼
    write_script             grounded script (script gate)
        │
        ▼
    plan_visuals             Visual Plan per segment
        │
        ▼
    select_assets            media: reuse/acquire/permitted Wan
                             infographic: HyperFrames
                             scientific: Manim
        ▼
    generate_narration       TTSProvider → narration audio
        │
        ▼
    transcribe_narration     TranscriptionProvider → word timestamps
        │
        ▼
    build_captions           deterministic caption layout
        │
        ▼
    compose_clip             FFmpeg → Clip (720×1280, 30 FPS)
        │
        ▼
    validate_clip            deterministic validation
        │
        ▼
    evaluate_clip            semantic (LLM) evaluation
        │
   ┌────┴─────┐
  FAIL       PASS
   │          │
   ▼          ▼
 plan_retry  publish        Publisher per enabled platform
 (targeted)   │
   │          ▼
   └─► re-enter affected stage      schedule metric collection → Metric Snapshots
```

## In scope for v1.0.0

- Daily scheduled Run at 05:00 Europe/Lisbon (configurable) plus Run Now and Manual URL runs.
- Research of 10–20 recent high-quality candidate articles (configurable),
  deduplication, Story clustering, Story selection, additional Source gathering.
- Claims with verbatim evidence and support levels; scripts restricted to
  accepted Claims.
- Asset library with provenance, search-before-acquire reuse, external media
  sources, optional image/video generation, typed local infographic and
  mathematical/scientific graphics, royalty-free music.
- TTS narration, transcription-aligned captions, deterministic motion and
  transitions, FFmpeg composition.
- Deterministic validation + semantic evaluation producing actionable issues;
  bounded, targeted retry.
- Publishing through `Publisher` adapters for YouTube, Instagram, TikTok and Facebook; publishing mode `disabled` / `dry_run` / `live`.
- Metric Snapshots at 1 h, 6 h, 24 h, 48 h, 7 d, 30 d; estimated revenue.
- Dark-theme web UI: dashboard, live Run progress, Runs, Clips, analytics,
  asset library, Content Profile, settings, Run Now, Manual URL.
- One active Content Profile.

## Explicit non-goals for v1.0.0

- Multi-user accounts, roles, tenants.
- More than one active Content Profile at a time (the model must not prevent it later).
- AI music generation.
- Distributed execution: no microservices, Kubernetes, Celery, RQ, Temporal,
  Kafka, RabbitMQ, Redis, KeyDB or service meshes. Dragonfly is limited to
  rolling LLM RPM/circuit state and does not enable distributed execution (see
  [architecture/system-architecture.md](architecture/system-architecture.md#prohibited-technology)).
- Vector databases or more than one durable database.
- Cloud object storage (the `StorageProvider` boundary allows it later).
- A generic agent framework in the runtime pipeline. LLM steps are single
  structured-output calls orchestrated by the workflow
  ([architecture/application-architecture.md](architecture/application-architecture.md#llm-usage-model)).
- Dependencies on OpenMontage, OpenShorts, JEV, or System One. These projects
  were inspiration only.
- Clipping long-form videos into highlights (a previous product idea; see
  [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md#known-conflicts)).

## Default output

| Property | Default | Canonical source |
| --- | --- | --- |
| Duration | min 60 s, target 70 s, max 90 s (inclusive) | [14-content-profiles.md](14-content-profiles.md), [10-composition.md](10-composition.md) |
| Aspect ratio | 9:16 | [10-composition.md](10-composition.md) |
| Resolution | 720 × 1280 | [ADR-007](decisions/ADR-007-720p-mobile-first-output.md) |
| Frame rate | 30 FPS constant | [10-composition.md](10-composition.md) |
| Container | MP4, H.264 video, AAC audio | [10-composition.md](10-composition.md) |

## Technology baseline

Python 3.13+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL,
Dragonfly, Docker Compose, LangGraph, httpx, FFmpeg; React + TypeScript + Vite + Tailwind CSS. Tooling:
Ruff, Pyright, pytest (+asyncio, cov), pre-commit, ESLint, Prettier, Vitest,
Playwright, GitHub Actions. Rationale lives in the ADRs
([decisions/README.md](decisions/README.md)).

## Design philosophy

A serious small production system that one experienced engineer can
understand, run, debug and extend. Prefer clear interfaces, small modules,
explicit dependencies, strong tests, simple workflows, good error handling,
useful observability and documented decisions over large abstractions,
agent proliferation, distributed infrastructure and premature scalability.
