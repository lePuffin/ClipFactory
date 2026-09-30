# ClipFactory --- Baseline Knowledge for GitHub Copilot

## Purpose

This document is the complete project context that must be given to
GitHub Copilot/Luna before it creates the baseline documentation and
repository structure for ClipFactory.

The Copilot agent does **not** have access to the prior ChatGPT
conversation. Treat this document as the authoritative initial project
brief.

The immediate goal is **not implementation**.

The immediate goal is to create a high-quality, editable **v1.0.0
documentation/specification baseline** directly in the repository. The
human owner will review, correct, extend, and approve those documents
before asking an agent to perform the one-shot implementation.

Do not implement the application yet unless explicitly requested.

------------------------------------------------------------------------

# 1. Project identity

## Name

**ClipFactory**

Use the name `ClipFactory` consistently throughout the repository.

Use **clip** as the canonical term for the final produced video.

Do not use "short", "shorts", "reel", or "TikTok" as generic names for
the product output.

YouTube, Instagram, and TikTok are publishing platforms only.

## Goal

ClipFactory is an autonomous content-production application that:

1.  researches recent news;
2.  identifies a relevant story;
3.  gathers and verifies source material;
4.  builds a structured Story Package;
5.  writes a script;
6.  plans visuals;
7.  finds or generates appropriate media assets;
8.  generates narration;
9.  generates captions;
10. composes the final vertical clip;
11. evaluates the result;
12. retries/revises when necessary;
13. publishes approved clips;
14. collects post-publication metrics.

The initial use case is automated news content, but the architecture
must remain configurable enough to support other content categories
later.

The initial system is intended for one private user.

------------------------------------------------------------------------

# 2. Current project direction

ClipFactory has been inspired by projects such as OpenMontage and
OpenShorts.

These projects are **references and sources of ideas**, not
architectural dependencies.

Do not introduce OpenMontage, OpenShorts, JEV, System One, or similar
frameworks into the project merely because they exist.

Use external projects only when they solve a concrete problem and the
corresponding dependency is explicitly justified.

Avoid technology for technology's sake.

The architecture should be simple, explicit, testable, maintainable, and
production-quality.

------------------------------------------------------------------------

# 3. Immediate objective: documentation baseline

The first agent task is to create a complete editable baseline around
version **v1.0.0**.

The agent should produce documentation and repository scaffolding, not
the full application implementation.

The documentation should be written so that a later implementation agent
can operate almost entirely from the repository without needing the
original ChatGPT conversation.

The baseline should contain at least:

``` text
AGENTS.md
README.md

.github/
  copilot-instructions.md
  agents/
  instructions/
  skills/
  prompts/
  workflows/

docs/
  requirements/
  architecture/
  implementation/
  glossary/
```

The exact structure may be improved if there is a strong reason, but do
not add unnecessary complexity.

------------------------------------------------------------------------

# 4. Engineering principles

These principles are mandatory unless a later ADR explicitly changes
them.

## 4.1 Simplicity

Prefer the simplest architecture that satisfies the requirements.

Do not add:

-   microservices;
-   Kubernetes;
-   distributed queues;
-   event buses;
-   vector databases;
-   service meshes;
-   unnecessary caching;
-   unnecessary agent frameworks;
-   unnecessary abstractions.

Every technology should have a concrete reason to exist.

## 4.2 Provider isolation

External services must be accessed through explicit provider/adaptor
interfaces.

Examples:

``` text
LLMProvider
TTSProvider
TranscriptionProvider
ImageProvider
VideoProvider
MediaSourceProvider
Publisher
StorageProvider
NewsSource
```

Domain/application logic must not depend directly on Google, OpenRouter,
ElevenLabs, a particular stock-media API, or a social-media API.

## 4.3 Domain independence

Domain logic should not depend on infrastructure details.

Keep responsibilities separated:

``` text
Domain
Application/use cases
Infrastructure/providers
API/UI
Workflow orchestration
```

Do not create generic abstractions without a real consumer.

## 4.4 Deterministic work should not use an LLM

Use normal code for:

-   file operations;
-   media validation;
-   duration checks;
-   resolution checks;
-   frame-rate checks;
-   audio/video presence;
-   caption bounds;
-   retries;
-   scheduling;
-   database operations;
-   API calls;
-   media composition;
-   transcoding;
-   metadata processing.

Use LLMs for tasks where language/reasoning is actually needed:

-   story selection;
-   summarisation;
-   claim extraction;
-   script generation;
-   visual planning;
-   semantic evaluation;
-   similar editorial decisions.

## 4.5 Tests are executable requirements

Do not weaken or delete tests merely to make an implementation pass.

Do not claim functionality is implemented unless it has been verified.

------------------------------------------------------------------------

# 5. Initial technical stack

## Backend

Use:

-   Python 3.13+
-   `uv`
-   FastAPI
-   Pydantic v2
-   SQLAlchemy 2
-   Alembic
-   PostgreSQL
-   LangGraph
-   httpx
-   FFmpeg

Development/testing:

-   pytest
-   pytest-asyncio
-   pytest-cov
-   Ruff
-   Pyright
-   pre-commit
-   GitHub Actions

Use Ruff for formatting and linting.

Do not add Black, isort, Flake8, or other overlapping tools without an
explicit architectural reason.

Recommended Python commands:

``` bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

The exact project commands should be documented and centralised where
practical.

## Frontend

Use:

-   TypeScript
-   React
-   Vite
-   Tailwind CSS

Quality tooling:

-   ESLint
-   Prettier
-   Vitest
-   Playwright

Expected validation:

``` bash
npm run lint
npm run typecheck
npm run test
npm run build
```

## Database

PostgreSQL is the persistent store for:

-   application state;
-   workflow/run state;
-   domain metadata;
-   source metadata;
-   story metadata;
-   asset metadata;
-   publication metadata;
-   analytics snapshots;
-   configuration.

Use SQLAlchemy 2 and Alembic.

## Storage

v1.0 uses a **local filesystem** for actual media files.

Create a `StorageProvider` abstraction so that object storage can be
added later without changing domain/application logic.

Do not introduce cloud object storage in v1.0 unless explicitly
required.

## Workflow

Use **LangGraph** as the workflow/state-machine engine.

LangGraph is not the application's general architecture.

The rest of the application should not become coupled to LangGraph
concepts unnecessarily.

The workflow must be:

-   stateful;
-   retryable;
-   observable;
-   resumable where practical;
-   bounded by a maximum retry count.

A maximum of approximately 3 retries is a reasonable initial default,
but make this configurable.

## Scheduling

The default automatic schedule is:

``` text
05:00 daily
```

There must also be a **Run Now** action.

Do not introduce Celery, RQ, Temporal, Kafka, RabbitMQ, or another
distributed job system in v1.0 unless an explicit requirement
demonstrates the need.

------------------------------------------------------------------------

# 6. User interface

The application should provide a modern dark-theme web UI.

Core areas:

-   Dashboard
-   Current production/workflow status
-   Published clips
-   Analytics
-   Estimated monetary return
-   Assets library
-   Settings
-   Content Profile
-   Run Now
-   Manual news URL input

The UI should show workflow progress in a useful way.

Use REST for normal operations and SSE or WebSocket for live workflow
status.

Do not overengineer the real-time layer.

------------------------------------------------------------------------

# 7. Content Profiles

The application must use a **Content Profile** to describe editorial
configuration.

v1.0 should support one active profile, but the domain model should not
make multiple profiles impossible later.

A Content Profile can define:

-   language;
-   category;
-   topics;
-   excluded topics;
-   geography/coverage;
-   markets;
-   voice;
-   target duration;
-   visual style;
-   publishing platforms;
-   schedule.

Supported category examples:

-   general news;
-   technology;
-   AI;
-   finance;
-   business;
-   science;
-   gaming;
-   sports;
-   entertainment;
-   politics.

The default profile is intended for global news with English narration,
but this must remain configurable.

------------------------------------------------------------------------

# 8. Clip requirements

## Duration

The operational target is:

``` text
minimum: 60 seconds
target: 60 seconds
maximum: 90 seconds
```

The reason is the current TikTok monetisation-oriented use case.

However, do **not** hardcode "TikTok monetisation" into the core
business logic.

Duration must be a configurable Content Profile requirement.

The architecture should allow the limits to change without rewriting the
pipeline.

Examples:

``` text
58s -> fail
63s -> pass
74s -> pass
89s -> pass
92s -> fail
```

## Video format

Default v1.0 output:

``` text
Aspect ratio: 9:16
Resolution: 720p vertical
Dimensions: 720 x 1280
Frame rate: 30 FPS
```

720p is intentional. The target environment is mobile consumption, where
the expected perceptual difference from 1080p is not worth the
additional processing/storage cost for this project.

Keep output parameters configurable where sensible.

------------------------------------------------------------------------

# 9. Research pipeline

The system researches **latest relevant news**.

The initial approach should not retrieve hundreds of articles.

Large batches will contain duplicated reporting, rewrites, syndicated
copies, and low-value sources.

Use a relatively small set of high-quality candidate sources.

A sensible initial range is approximately:

``` text
10–20 high-quality articles
```

The exact value should be configurable.

The system should:

1.  fetch recent candidate articles;
2.  evaluate source quality;
3.  deduplicate/cluster articles covering the same underlying story;
4.  identify distinct story candidates;
5.  score/select a story;
6.  gather additional sources for the selected story.

The system should reason about **stories**, not simply count articles.

Example:

``` text
Reuters -> story A
AP -> story A
BBC -> story A
CNN -> story A
Blog -> copy of Reuters

= one story with multiple sources
```

The research architecture must support source ranking and deduplication.

------------------------------------------------------------------------

# 10. Sources and factual grounding

A selected story requires:

``` text
minimum: 1 source
preferred standard: 3 independent sources
```

One strong source can be sufficient when additional independent
reporting is unavailable.

Three independent sources is the normal quality target.

The architecture must distinguish:

-   article count;
-   independent sources;
-   duplicated/syndicated reporting.

Claims should be linked to supporting source evidence where practical.

Example conceptual model:

``` text
Story
 ├── Source: Reuters
 ├── Source: AP
 ├── Source: BBC
 │
 ├── Claim 1
 │    ├── Reuters
 │    └── AP
 │
 ├── Claim 2
 │    └── BBC
 │
 └── Claim 3
      ├── Reuters
      └── BBC
```

This provides a basis for factual evaluation.

Politics is a supported category, but the same architecture must remain
factual, source-grounded, and attribution-aware.

------------------------------------------------------------------------

# 11. External media

The system may use free/licensed external media sources for:

-   B-roll;
-   photographs;
-   illustrations;
-   maps;
-   other visual assets.

There are free sources used by projects such as OpenMontage, but
ClipFactory should not depend on OpenMontage.

Create a provider abstraction such as:

``` text
MediaSourceProvider
```

A returned media asset should retain provenance information such as:

``` text
url
source
author
license
attribution
media_type
dimensions
duration
```

Licensing/provenance is important.

The system must be able to determine where an asset came from.

------------------------------------------------------------------------

# 12. Asset management and reuse

Assets are first-class domain objects.

An Asset can represent:

-   image;
-   video/B-roll;
-   generated image;
-   generated video;
-   audio;
-   graphic;
-   chart;
-   map;
-   other reusable media.

Assets should retain metadata such as:

``` text
file
type
description
tags
subjects
source
license
attribution
generated_by
quality_score
created_at
usage_count
```

The Asset Manager should:

1.  search existing assets;
2.  reuse suitable assets;
3.  generate/fetch missing assets;
4.  store successful assets for future reuse.

The system should prefer reuse where appropriate.

A high-quality asset generated for one clip should potentially be
reusable months later.

------------------------------------------------------------------------

# 13. LLM architecture

Use a provider abstraction:

``` text
LLMProvider
```

Initial provider:

``` text
OpenAI-compatible provider
    -> OpenRouter initially
```

The architecture must permit:

-   OpenRouter;
-   OpenAI;
-   local models;
-   other OpenAI-compatible endpoints;

without changing domain/application logic.

Do not hardcode a specific model name into the domain.

Model selection belongs in configuration/provider settings.

------------------------------------------------------------------------

# 14. Image/video generation architecture

Do not lock ClipFactory to a single image or video-generation service.

Use abstractions such as:

``` text
ImageProvider
VideoProvider
MediaSourceProvider
```

Possible future implementations include:

-   external free providers;
-   local models;
-   generated images;
-   generated video;
-   stock media.

The workflow should not care which provider generated an asset.

------------------------------------------------------------------------

# 15. TTS architecture

The initial TTS provider is **Google**.

However, TTS must be provider-independent.

Use:

``` text
TTSProvider
```

Potential implementations:

``` text
GoogleTTSProvider
ElevenLabsTTSProvider
LocalTTSProvider
```

The pipeline must not directly depend on Google.

The goal is to make switching providers inexpensive.

------------------------------------------------------------------------

# 16. Transcription and captions

The conceptual pipeline is:

``` text
Script
  ↓
TTSProvider
  ↓
Audio
  ↓
TranscriptionProvider
  ↓
Word timestamps
  ↓
Captions
```

Whisper/local transcription is a sensible initial implementation.

Use a provider abstraction:

``` text
TranscriptionProvider
```

Captions are generated from timestamped narration.

Caption generation and layout should be deterministic where possible.

The evaluator must be able to detect captions that exceed safe visual
bounds.

------------------------------------------------------------------------

# 17. Script and Story Package

The selected story should be transformed into a structured **Story
Package**.

It should contain enough information for the production pipeline to
operate without repeatedly rediscovering the story.

Conceptually:

``` text
Story Package
 ├── story
 ├── sources
 ├── claims
 ├── key facts
 ├── script
 ├── visual plan
 ├── asset requirements
 └── social metadata
```

The script must be grounded in source evidence.

The system should avoid inventing facts that are not supported by the
gathered sources.

------------------------------------------------------------------------

# 18. Visual planning

The system should produce a visual plan before composition.

A visual plan should identify, for each relevant segment:

-   narration context;
-   visual objective;
-   required asset;
-   preferred asset type;
-   source/reuse/generation preference;
-   duration;
-   transition/motion requirements.

Simple deterministic motion such as:

-   slow zoom;
-   pan;
-   crop;
-   Ken Burns;
-   transitions;

should be implemented without requiring AI generation.

AI should generate content when necessary, not basic motion.

------------------------------------------------------------------------

# 19. Audio/video composition

Final composition should be deterministic and reproducible.

FFmpeg is the baseline media-processing tool.

The composer should combine:

-   visual assets;
-   narration;
-   music where used;
-   captions;
-   transitions;
-   timing.

The output must satisfy:

``` text
9:16
720 x 1280
30 FPS
60–90 seconds by default
valid video stream
valid audio stream
```

All final media should be validated before publication.

------------------------------------------------------------------------

# 20. Music

Use a royalty-free music library.

There is no requirement to generate music with AI.

Music should be represented as an asset/provider concern, not hardcoded
into the workflow.

The implementation should leave room for future music
providers/libraries.

------------------------------------------------------------------------

# 21. Evaluation

Evaluation is a core part of the pipeline.

A clip must **not** be published simply because composition succeeded.

Use two categories of evaluation.

## Deterministic evaluation

Examples:

-   duration;
-   resolution;
-   aspect ratio;
-   frame rate;
-   audio presence;
-   video presence;
-   media corruption;
-   missing assets;
-   caption bounds;
-   narration duration;
-   invalid metadata.

## Semantic/LLM evaluation

Examples:

-   factual consistency;
-   source grounding;
-   script quality;
-   hook quality;
-   visual relevance;
-   narration quality;
-   pacing;
-   caption quality;
-   overall editorial quality.

The evaluator should return **actionable issues**, not merely a score.

Conceptually:

``` text
Evaluation
 ├── passed
 ├── issues[]
 ├── warnings[]
 ├── actions[]
 └── metrics
```

Examples:

``` text
Issue:
    narration is 7 seconds longer than visual plan

Action:
    shorten script or extend visual segment
```

or:

``` text
Issue:
    claim is not sufficiently supported

Action:
    remove claim or obtain additional source
```

------------------------------------------------------------------------

# 22. Retry/revision

If evaluation fails, the workflow may retry/revise.

Good assets should be reused rather than regenerated unnecessarily.

Example:

``` text
Attempt 1
   ↓
Evaluation FAIL
   ↓
identify problems
   ↓
revise affected stage
   ↓
Attempt 2
   ↓
Evaluation
```

Do not blindly rerun the complete pipeline.

Retries should be targeted when possible.

There should be a maximum retry count.

A failed final result must never be published.

------------------------------------------------------------------------

# 23. Publishing

Publishing should use adapters/providers.

Conceptually:

``` text
Publisher
 ├── YouTubePublisher
 ├── InstagramPublisher
 └── TikTokPublisher
```

The core workflow should work with a generic:

``` text
PublicationRequest
```

rather than platform-specific API calls.

A Content Profile determines which platforms are active.

The same base clip/caption/metadata should be adapted to
platform-specific requirements through the publisher adapter.

------------------------------------------------------------------------

# 24. Analytics

The application should track post-publication metrics.

A `MetricSnapshot` should contain at least conceptually:

``` text
timestamp
views
likes
comments
shares
watch_time
retention
followers_delta
estimated_revenue
platform
publication
```

Initial snapshot timings:

``` text
1 hour
6 hours
24 hours
48 hours
7 days
30 days
```

These timings should be configurable.

Revenue should be labelled **estimated revenue** where it is not
directly reported by the platform.

Do not present estimates as guaranteed income.

------------------------------------------------------------------------

# 25. Core domain entities

The baseline should consider at least these domain entities:

``` text
Run
Story
Source
Claim
Script
Asset
StoryPackage
Clip
Evaluation
Publication
MetricSnapshot
ContentProfile
Provider
```

The agent may refine the model if requirements justify it.

Do not create entities merely because a concept has a noun.

------------------------------------------------------------------------

# 26. Run and workflow observability

A Run represents one complete pipeline execution.

Runs should make it possible to answer:

> Why did today's clip fail?

Persist meaningful workflow events such as:

``` text
run_started
research_completed
story_selected
sources_collected
claims_extracted
script_generated
visual_plan_generated
assets_selected
assets_generated
audio_generated
captions_generated
composition_completed
evaluation_completed
retry_started
publication_started
publication_completed
run_completed
run_failed
```

Do not introduce a huge observability platform in v1.0.

Structured logging plus persisted run events is sufficient initially.

------------------------------------------------------------------------

# 27. Manual URL workflow

The UI should allow the user to manually provide a news URL.

The system should then be able to:

1.  ingest the URL;
2.  retrieve/parse the source;
3.  build a story context;
4.  continue through the normal production pipeline.

This should reuse the same Story/Source/StoryPackage architecture rather
than creating a second production pipeline.

------------------------------------------------------------------------

# 28. Repository architecture

A reasonable baseline structure is:

``` text
clipfactory/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── package.json
├── Makefile
├── .pre-commit-config.yaml
│
├── .github/
│   ├── copilot-instructions.md
│   ├── agents/
│   │   ├── architect.agent.md
│   │   ├── backend.agent.md
│   │   ├── frontend.agent.md
│   │   ├── qa.agent.md
│   │   ├── reviewer.agent.md
│   │   └── clipfactory.agent.md
│   ├── instructions/
│   │   ├── python.instructions.md
│   │   ├── frontend.instructions.md
│   │   ├── tests.instructions.md
│   │   └── documentation.instructions.md
│   ├── skills/
│   │   ├── implementation/SKILL.md
│   │   ├── testing/SKILL.md
│   │   ├── architecture/SKILL.md
│   │   ├── debugging/SKILL.md
│   │   └── validation/SKILL.md
│   ├── prompts/
│   │   ├── implement-feature.prompt.md
│   │   ├── review.prompt.md
│   │   └── validate-baseline.prompt.md
│   └── workflows/
│       └── ci.yml
│
├── docs/
│   ├── requirements/
│   ├── architecture/
│   ├── implementation/
│   └── glossary/
│
├── backend/
│   ├── src/
│   │   └── clipfactory/
│   │       ├── domain/
│   │       ├── api/
│   │       ├── research/
│   │       ├── planning/
│   │       ├── assets/
│   │       ├── production/
│   │       ├── composition/
│   │       ├── evaluation/
│   │       ├── publishing/
│   │       ├── analytics/
│   │       ├── workflow/
│   │       └── infrastructure/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
│
└── frontend/
    ├── src/
    │   ├── components/
    │   ├── pages/
    │   ├── features/
    │   ├── api/
    │   ├── hooks/
    │   └── types/
    └── tests/
```

This is a starting point, not a command to blindly create every
directory immediately.

The agent should avoid empty architectural layers that have no current
purpose.

------------------------------------------------------------------------

# 29. Recommended documentation set

The baseline should include requirements similar to:

``` text
docs/requirements/
  001-system-overview.md
  002-content-profiles.md
  003-research.md
  004-story-and-source-grounding.md
  005-assets.md
  006-production.md
  007-composition.md
  008-evaluation.md
  009-publishing.md
  010-analytics.md
  011-ui.md
  012-scheduling-and-runs.md
  013-manual-url-workflow.md
  014-security-and-configuration.md
  015-non-functional-requirements.md
```

Architecture:

``` text
docs/architecture/
  architecture.md
  domain-model.puml
  component-diagram.puml
  workflow.puml
  deployment.puml
```

Implementation:

``` text
docs/implementation/
  roadmap.md
  testing-strategy.md
  configuration.md
  development.md
  decisions/
```

ADR candidates:

``` text
ADR-001-python-and-uv.md
ADR-002-langgraph-workflow.md
ADR-003-postgresql-persistence.md
ADR-004-provider-adapters.md
ADR-005-asset-reuse.md
ADR-006-evaluation-and-retry.md
ADR-007-single-profile-v1.md
ADR-008-local-filesystem-storage.md
ADR-009-720p-mobile-first-output.md
ADR-010-simple-scheduler-v1.md
```

The agent may rename or consolidate these if that produces a clearer
baseline.

------------------------------------------------------------------------

# 30. Requirements format

Requirements should be uniquely identifiable.

Use IDs such as:

``` text
CF-REQ-001
CF-REQ-002
...
```

A requirement should preferably contain:

-   ID;
-   title;
-   description;
-   rationale where useful;
-   inputs;
-   preconditions;
-   expected behaviour;
-   failure behaviour;
-   acceptance criteria;
-   dependencies where relevant.

Example:

``` text
CF-REQ-XXX — Clip duration validation

Description:
The system shall reject clips outside the configured duration range.

Default:
60–90 seconds.

Acceptance criteria:
- a 59-second clip fails;
- a 60-second clip passes;
- a 75-second clip passes;
- a 90-second clip passes;
- a 91-second clip fails;
- the limits are configurable;
- validation occurs before publication.
```

Requirements should be testable.

------------------------------------------------------------------------

# 31. Glossary

Create a glossary so terminology remains consistent.

At minimum:

``` text
ClipFactory
Clip
Story
Source
Claim
Story Package
Asset
Run
Content Profile
Publication
Metric Snapshot
Provider
Evaluation
Retry
```

Definitions:

-   **ClipFactory** --- the application.
-   **Clip** --- the final produced video.
-   **Story** --- the selected news/topic being covered.
-   **Source** --- an external information source supporting a story.
-   **Claim** --- a factual assertion extracted from source material.
-   **Story Package** --- structured information required to produce a
    clip.
-   **Asset** --- reusable image, video, audio, graphic, chart, map, or
    other media.
-   **Run** --- one execution of the production workflow.
-   **Content Profile** --- editorial and production configuration.
-   **Publication** --- publication of a clip to a platform.
-   **Metric Snapshot** --- metrics observed at a particular time.
-   **Provider** --- adapter for an external capability/service.
-   **Evaluation** --- automated quality analysis.
-   **Retry** --- a new attempt to correct an unsuccessful stage/result.

------------------------------------------------------------------------

# 32. Agent customization

The repository should be prepared for GitHub Copilot agent-driven
development.

Create:

## AGENTS.md

This is the concise top-level engineering contract.

It should explain:

-   project purpose;
-   source-of-truth hierarchy;
-   architecture rules;
-   testing requirements;
-   forbidden unnecessary technologies;
-   validation commands;
-   implementation discipline.

## copilot-instructions.md

Repository-wide instructions for Copilot.

## Path-specific instructions

At minimum:

``` text
python.instructions.md
frontend.instructions.md
tests.instructions.md
documentation.instructions.md
```

## Custom agents

Create:

### architect.agent.md

Responsible for:

-   architecture;
-   domain boundaries;
-   ADRs;
-   requirements interpretation.

Should not casually implement unrelated application code.

### backend.agent.md

Responsible for:

-   Python backend;
-   domain/application code;
-   providers;
-   persistence;
-   workflow.

### frontend.agent.md

Responsible for:

-   React;
-   TypeScript;
-   UI;
-   API integration.

### qa.agent.md

Responsible for:

-   tests;
-   test strategy;
-   coverage;
-   integration/e2e validation;
-   regression prevention.

### reviewer.agent.md

Read-only critical review.

It should identify:

-   requirement gaps;
-   architectural violations;
-   missing tests;
-   unnecessary complexity;
-   security issues;
-   incorrect provider coupling;
-   documentation/code inconsistencies.

It must not silently modify code while reviewing.

### clipfactory.agent.md

Main orchestrator.

It should coordinate the entire implementation process later.

------------------------------------------------------------------------

# 33. Skills

Create focused skills rather than one enormous skill.

Suggested:

``` text
implementation
testing
architecture
debugging
validation
```

Each skill should contain practical instructions and checklists.

Avoid duplicating the entire repository specification in every skill.

Skills should refer back to the canonical requirements and architecture
documents.

------------------------------------------------------------------------

# 34. Future one-shot implementation strategy

This is **not the current task**, but the documentation should prepare
for it.

The future implementation agent should work approximately in these
phases:

``` text
Phase 0 — Validate specification
Phase 1 — Project foundation
Phase 2 — Domain and persistence
Phase 3 — Core workflow
Phase 4 — Production pipeline
Phase 5 — Publishing and analytics
Phase 6 — Frontend
Phase 7 — Integration
Phase 8 — Full validation
Phase 9 — Final audit
```

After each phase:

``` text
tests
lint
format
typecheck
build where applicable
```

The agent should continue automatically unless genuinely blocked.

It must not declare completion without running validation.

------------------------------------------------------------------------

# 35. Testing strategy

Testing should exist at multiple levels.

## Unit tests

For:

-   domain rules;
-   duration validation;
-   source/claim relationships;
-   content profile validation;
-   workflow decisions;
-   asset selection;
-   provider contracts;
-   deterministic evaluators.

## Integration tests

For:

-   PostgreSQL;
-   repositories;
-   FastAPI;
-   provider adapters;
-   FFmpeg;
-   workflow persistence.

Use fakes/mocks where external APIs would make tests unreliable or
expensive.

## E2E tests

Cover critical user flows such as:

``` text
Run Now
research
story selection
production
evaluation
publication preparation
dashboard status
```

Do not require real external publishing credentials in normal CI.

------------------------------------------------------------------------

# 36. CI

GitHub Actions should enforce quality.

Backend CI should run:

``` bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Frontend CI should run:

``` bash
npm run lint
npm run typecheck
npm run test
npm run build
```

Coverage thresholds should be defined deliberately rather than chosen
arbitrarily.

A threshold around 85% branch coverage is a possible starting point, but
the documentation should treat the exact threshold as an editable
project decision.

------------------------------------------------------------------------

# 37. Configuration and secrets

Do not commit credentials.

External provider credentials must be supplied through
environment/configuration mechanisms.

Do not store secrets directly in PostgreSQL unless a later security
design explicitly requires encrypted secret storage.

Document required environment variables and safe development
configuration.

The UI should expose configuration settings that are appropriate for the
application, but credentials should not be unnecessarily exposed.

------------------------------------------------------------------------

# 38. Security baseline

Even though this is a private single-user application:

-   validate all external input;
-   validate URLs;
-   avoid arbitrary command execution;
-   safely invoke FFmpeg;
-   prevent path traversal;
-   validate downloaded media;
-   enforce file-size limits;
-   avoid trusting remote MIME types blindly;
-   do not expose credentials through logs;
-   sanitise external text before rendering;
-   use parameterised database operations;
-   isolate external provider failures.

Do not overbuild authentication for v1.0.

------------------------------------------------------------------------

# 39. Error handling

Provider failures must not crash the entire application without context.

Errors should be:

-   structured;
-   logged;
-   associated with a Run where relevant;
-   actionable;
-   distinguishable between transient and permanent failures where
    possible.

Retries should be bounded.

A failed provider call should not automatically trigger regeneration of
all previous successful work.

------------------------------------------------------------------------

# 40. Source-of-truth hierarchy

When implementation begins, use this priority:

``` text
1. Explicit approved requirements
2. Approved architecture
3. Approved ADRs
4. Tests
5. Implementation
6. Informal comments/assumptions
```

If code conflicts with an approved requirement, do not silently
reinterpret the requirement.

If requirements conflict with each other, document the conflict and
resolve it before implementation.

------------------------------------------------------------------------

# 41. What the agent must NOT do

Do not:

-   implement the entire application now;
-   invent requirements silently;
-   introduce JEV;
-   make OpenShorts a dependency;
-   make OpenMontage a dependency;
-   introduce microservices;
-   introduce Kubernetes;
-   introduce a distributed task queue without need;
-   add a vector database without a demonstrated use case;
-   add multiple databases without need;
-   hardcode Google TTS into the domain;
-   hardcode OpenRouter into the domain;
-   hardcode TikTok requirements into generic clip logic;
-   use LLMs for deterministic validation;
-   create abstractions with no current consumer;
-   create dozens of agents for cosmetic reasons;
-   create empty directories solely to match a diagram;
-   claim an integration works without verification;
-   weaken tests to make implementation pass.

------------------------------------------------------------------------

# 42. Expected result of the current task

After reading this document, the Copilot agent should create a
**documentation-first baseline** directly in the ClipFactory repository.

The result should include:

1.  project overview;
2.  glossary;
3.  numbered functional requirements;
4.  non-functional requirements;
5.  domain model;
6.  component architecture;
7.  workflow architecture;
8.  deployment architecture;
9.  PlantUML diagrams;
10. ADRs;
11. testing strategy;
12. implementation roadmap;
13. development instructions;
14. Copilot instructions;
15. custom agents;
16. reusable skills;
17. validation prompts;
18. CI baseline;
19. repository structure;
20. clear source-of-truth rules.

The documents must be internally consistent.

The agent should cross-reference requirements and architecture instead
of duplicating conflicting definitions.

The human owner will review these documents before any one-shot
implementation begins.

------------------------------------------------------------------------

# 43. Open decisions to document rather than silently invent

The following details are intentionally flexible and should be
represented as provider/configuration decisions rather than hardcoded
assumptions:

-   exact LLM model;
-   exact OpenRouter model configuration;
-   exact news providers;
-   exact external image/B-roll providers;
-   exact image-generation provider;
-   exact video-generation provider;
-   exact Google TTS API/library;
-   exact Whisper implementation;
-   exact publishing API credentials/configuration;
-   exact royalty-free music source;
-   exact analytics/revenue data availability;
-   exact deployment environment.

Where a concrete implementation choice is necessary for the baseline,
record it as an ADR or explicit provisional decision.

Do not pretend an external integration has been validated if it has not.

------------------------------------------------------------------------

# 44. Design philosophy

The project should feel like a serious small production system, not an
academic framework.

Prefer:

``` text
clear interfaces
small modules
explicit dependencies
strong tests
simple workflows
good error handling
useful observability
documented decisions
```

over:

``` text
large abstractions
agent proliferation
distributed infrastructure
complex event systems
premature scalability
framework-driven architecture
```

The intended result is a system that one experienced engineer can
understand, run, debug, and extend.

------------------------------------------------------------------------

# 45. Final instruction to the documentation agent

Before creating files:

1.  read this entire document;
2.  inspect the existing repository;
3.  preserve useful existing work if present;
4.  identify conflicts between existing files and this baseline;
5.  create/update the documentation structure;
6.  create requirements with stable IDs;
7.  create architecture diagrams;
8.  create ADRs for significant decisions;
9.  create Copilot agents/instructions/skills;
10. ensure all documents agree with each other;
11. run lightweight validation of documentation links/references if
    practical;
12. do **not** begin full application implementation.

The output of this phase is the **approved documentation baseline from
which the later one-shot implementation will be executed**.
