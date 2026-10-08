# ClipFactory

ClipFactory is a private, single-user application that autonomously produces vertical news **Clips**: it researches recent news, selects a Story, grounds it in independent Sources and verified Claims, writes a script, plans and sources visuals, generates narration and captions, composes a 720×1280 Clip with FFmpeg, evaluates it, revises it when needed, publishes approved Clips to the enabled platforms, and tracks post-publication metrics.

> **Status:** v1.0.0 implementation in progress. The production workflow, scheduler, live Run events, evaluation and retries, approval, YouTube/Instagram/Facebook publishing, analytics, settings, and dashboard are implemented and tested with fakes or mocked HTTP. TikTok publishing is deferred. Live provider and platform integrations have not been verified end to end, and not every v1.0 acceptance criterion is complete.

## Documentation

| Start here | |
| --- | --- |
| [doc/specifications/README.md](doc/specifications/README.md) | Canonical specification: structure, reading order, source-of-truth rules |
| [doc/specifications/00-project-overview.md](doc/specifications/00-project-overview.md) | Purpose, pipeline, scope |
| [doc/specifications/architecture/README.md](doc/specifications/architecture/README.md) | Architecture and PlantUML diagrams |
| [doc/specifications/decisions/README.md](doc/specifications/decisions/README.md) | Architecture Decision Records |
| [doc/specifications/24-acceptance-criteria.md](doc/specifications/24-acceptance-criteria.md) | Definition of "v1.0.0 complete" |
| [doc/specifications/25-roadmap.md](doc/specifications/25-roadmap.md) | Implementation phases |
| [doc/specifications/26-open-decisions-and-conflicts.md](doc/specifications/26-open-decisions-and-conflicts.md) | Open decisions awaiting the owner |
| [doc/setup/platform-credentials.md](doc/setup/platform-credentials.md) | Provider and platform credential setup (`.env.example`) |
| [AGENTS.md](AGENTS.md) | Engineering contract for agents and contributors |

## Planned technology

Python 3.13+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Dragonfly, Docker Compose, LangGraph, httpx, FFmpeg · local pinned HyperFrames Node package and optional isolated Manim group for typed graphics · React, TypeScript, Vite, Tailwind CSS · Ruff, Pyright, pytest, ESLint, Prettier, Vitest, Playwright, GitHub Actions.

## Validating the documentation

```bash
python3 scripts/check_docs.py
```

## Running locally

The backend source lives under `backend/`. From the repository root, install
with `uv sync --locked`, configure a local `.env` from `.env.example`, and
build the frontend with `cd frontend && npm install && npm run build`.
The root runtime includes Manim and local Wan dependencies automatically
(Cairo/Pango build prerequisites are in the graphics setup guide).
From the repository root, use:

```bash
uv run clipfactory setup   # start PostgreSQL/Dragonfly, migrate, seed defaults
uv run clipfactory doctor  # read-only, redacted dependency diagnostics
uv run clipfactory         # native one-process/one-worker API and scheduler
```

Compose manages only pinned PostgreSQL and Dragonfly services; the backend, FFmpeg/FFprobe and local graphics renderers remain native. `setup` creates `DATA_DIR` if missing. `PUBLIC_MEDIA_DIR` is optional: startup and setup do not access or create it, and `doctor` reports an unavailable share as a warning. Local production and signed media serving use `DATA_DIR`. `doctor` exits 1 if any required check fails, and invalid configuration is reported by setting name without printing its value. The dashboard is served at `http://127.0.0.1:8000/`, and the health endpoint is `/api/health`. The `clipfactory db upgrade` and `clipfactory serve` commands remain available for targeted development use.

Native Wan is limited to two generation starts per Run by default. Change
**Wan Max Generations Per Run** under **Settings / Environment** (0 disables
new Wan calls). Failed/stopped starts count, and Retry/Continue retain usage.
Existing Wan Assets remain reusable. Additional Visuals use suitable grounded
HyperFrames/Manim alternatives or refined free-media searches; unresolved
media remains an explicit failure, never a placeholder.

Run the backend checks with `make backend-check` and the documentation link/traceability checks with `make docs-check`. See [provider setup](doc/setup/platform-credentials.md) before configuring live integrations.

The root runtime installs native Wan and Manim without group flags.
When generation is permitted by
the Content Profile and shot strategy, Wan can supply video for a missing
image or video shot. Missing model weights download automatically on first
use into `DATA_DIR/models/wan`, outside Git. Configure the model and device
via [generation settings](doc/specifications/18-configuration.md#provider-settings-and-credentials).
Local GPU generation has not been verified live; first use needs network,
disk space and sufficient RAM/VRAM and can be slow.

For the specified local HyperFrames/Manim graphics setup, dependencies and
validation expectations are documented in
[local graphics renderer setup](doc/setup/local-graphics-rendering.md).
All five graphics templates were exercised with synthetic local fixtures;
this is not live Story or complete Run validation.

## License

[MIT](LICENSE)
