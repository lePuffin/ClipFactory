# ClipFactory

### Autonomous AI News Anchor & Short-Form Video Production Engine

[![CI](https://github.com/lePuffin/ClipFactory/actions/workflows/ci.yml/badge.svg)](https://github.com/lePuffin/ClipFactory/actions/workflows/ci.yml)
![Python 3.13+](https://img.shields.io/badge/python-3.13+-3776ab.svg?style=flat&logo=python&logoColor=white)
![TypeScript 5.8](https://img.shields.io/badge/typescript-5.8-3178c6.svg?style=flat&logo=typescript&logoColor=white)
![React 19](https://img.shields.io/badge/react-19-61dafb.svg?style=flat&logo=react&logoColor=black)
![FFmpeg](https://img.shields.io/badge/media-FFmpeg%20%7C%20Faster--Whisper-007808.svg?logo=ffmpeg&logoColor=white)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ClipFactory is a production-grade autonomous content engine that converts verified global news and sports reporting into broadcast-quality vertical video (9:16 vertical Clips, 720×1280, 30 FPS). Built for hands-free daily publication to **YouTube Shorts**, **Instagram Reels**, **TikTok**, and **Facebook Reels**, ClipFactory enforces strict journalistic grounding—extracting primary sources, cross-verifying factual claims, and eliminating generative hallucinations before any script or media is produced.

---

## Key Highlights

- **Journalistic Evidence Grounding:** Discovers and clusters articles via RSS feeds, scores candidates against active editorial profiles, cross-references independent primary sources, and freezes verified claims with verbatim citations.
- **Autonomous Agent Personas:** Production is orchestrated by specialized agent personas—**Scout** (Research), **Sage** (Fact Grounding), **Scribe** (Script & Story), **Pixel** (Visual Assets), **Echo** (Voice & Audio), **Frame** (FFmpeg Composition), **Guard** (Quality Review & Retries), and **Relay** (Omnichannel Publishing)—with live telemetry streamed over Server-Sent Events (SSE).
- **Multi-Profile Scheduling:** Add, edit, enable or remove daily Run times from Content Profile. Each profile supports multiple times in the backend host's local timezone and an optional account credential prefix for separate publishing accounts.
- **Manual Dispatch:** Select a saved Content Profile on Overview before starting Run Now or Manual URL; manual selection does not change automatic schedules.
- **Hybrid Multi-Modal Media Pipeline:** Combines a local deduplicated media library, high-resolution open stock (Pexels, Pixabay, Unsplash, Wikimedia Commons), Wan 2.1 local video diffusion, HyperFrames programmatic infographics, and Manim animations.
- **Deterministic Broadcast Assembly:** Word-level subtitle timing via `faster-whisper`, speech synthesis via Google Cloud TTS (Chirp 3 HD), dynamic audio ducking, branded outro stings, and automated EU AI Act Article 50 disclosure overlays rendered via FFmpeg.
- **Automated Omnichannel Publishing & Analytics:** Automated dispatch across YouTube, Instagram, TikTok, and Facebook, backed by a 30-day analytics tracking lifecycle and real-time monetization milestone monitoring.
- **Automated Validation Gates & Targeted Retries:** Multi-layer evaluation covering audio/video technical gates, narrative pacing, and semantic claim fidelity with automated bounded revisions.

---

## Production Pipeline

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Inter, Segoe UI, sans-serif", "fontSize": "16px", "lineColor": "#64748b", "edgeLabelBackground": "#f1f5f9"}, "flowchart": {"curve": "monotoneY", "htmlLabels": true, "wrappingWidth": 640, "padding": 24, "rankSpacing": 32, "useMaxWidth": true}}}%%
flowchart TD
    feeds(["RSS & News Feeds"])
    research["`**01 · SCOUT & SAGE**
Cluster Stories · Verify independent Sources · Extract Claims`"]
    planning["`**02 · SCRIBE & PIXEL**
Grounded scripts · Visual planning · Media sourcing & generation`"]
    production["`**03 · ECHO & FRAME**
Chirp 3 HD narration · Faster-Whisper captions · FFmpeg assembly`"]
    evaluation["`**04 · GUARD**
Technical media gates · Semantic alignment · Bounded retries`"]
    publishing["`**05 · RELAY**
YouTube Shorts · Instagram Reels · TikTok · Facebook Reels`"]
    analytics["`**06 · ANALYTICS & GOALS**
30-day Metric Snapshots · Monetization progress tracking`"]

    feeds --> research --> planning --> production --> evaluation
    evaluation -->|Approved Clip| publishing --> analytics

    classDef source fill:#f1f5f9,stroke:#cbd5e1,color:#334155,stroke-width:1px;
    classDef stage fill:#0f172a,stroke:#334155,color:#f8fafc,stroke-width:1px;
    classDef gate fill:#ecfdf5,stroke:#10b981,color:#065f46,stroke-width:2px;
    classDef outcome fill:#eff6ff,stroke:#3b82f6,color:#1e40af,stroke-width:1px;
    class feeds source;
    class research,planning,production,publishing stage;
    class evaluation gate;
    class analytics outcome;
```

---

## Architecture & Design Principles

ClipFactory is designed with strict separation of concerns using **Hexagonal Architecture (Ports and Adapters)**:

- **Zero Vendor SDK Leakage:** All external services (LLMs, TTS, news feeds, media stock, publishers) are isolated behind abstract interfaces (`ports/`). Business logic and workflows never directly couple to third-party SDKs.
- **Durable State & Resilience:** PostgreSQL provides ACID guarantees for domain entities, editorial profiles, and LangGraph workflow checkpoints. In-memory state and rolling rate-limits are backed by Dragonfly.
- **Deterministic Workflows:** Media processing, audio analysis, scheduling, routing, and verification gates are implemented entirely in deterministic code—LLMs are used exclusively for structured semantic synthesis.
- **Production Operational Console:** High-performance React 19 single-page application featuring live agent state, media review, timeline scrubber, centralized scheduling, and monetization goal tracking.

---

## Prerequisites

- **Linux / WSL2** (Ubuntu 22.04+ recommended)
- **Python 3.13+** with **[uv](https://docs.astral.sh/uv/)**
- **Node.js 22+** and **npm**
- **Docker** with Compose v2 (for PostgreSQL and Dragonfly services)
- **FFmpeg 6+** and **FFprobe** (compiled with `libx264`, `aac`, and `libass`)
- **System Graphics Libraries** (for Cairo/Pango text rendering): `libcairo2-dev`, `libpango1.0-dev`, `pkg-config`
- *(Optional)* **NVIDIA GPU with CUDA 12+** for accelerated local Wan 2.1 video diffusion and Whisper transcription

---

## Quickstart

### 1. Environment Configuration

```bash
cp .env.example .env
```

Configure your local database paths, storage directories, and provider keys in `.env`. Providers default to test fakes when credentials are left empty, enabling complete offline execution.

### 2. Dependency Installation & Build

```bash
# Backend dependencies and virtualenv setup
uv sync --locked

# Frontend compilation and assets build
cd frontend && npm ci && npm run build && cd ..
```

### 3. Bootstrap & Verification

```bash
# Start Docker services (PostgreSQL & Dragonfly), run migrations, seed initial profiles
uv run clipfactory setup

# Run preflight system health checks (Database, Dragonfly, FFmpeg, directories)
uv run clipfactory doctor

# Launch native backend server and scheduler daemon
uv run clipfactory
```

The web dashboard is served at `http://127.0.0.1:8000/`. Health check endpoint: `http://127.0.0.1:8000/api/health`.

### CLI Utilities

- `uv run clipfactory branding branding/<profile-slug>`: Generate a profile's reusable outro image, voice and video from its two logos. The Profile page shows its folder. See [profile branding](branding/README.md).
- `uv run clipfactory wan-test`: Benchmark local Wan 2.1 video generation.
- `uv run clipfactory db upgrade`: Apply pending Alembic database migrations.
- `uv run clipfactory serve`: Run Uvicorn directly with development live-reload.

---

## Quality & Verification

Every component is rigorously tested across unit, contract, integration, and end-to-end suites:

```bash
# Backend linting, type-checking, and test suite
uv run ruff check backend/
uv run pyright backend/
uv run pytest backend/tests/unit/

# Frontend linting, type-checking, and Vitest suite
cd frontend && npm run lint && npm run typecheck && npm run test && cd ..

# Full validation gate across backend, frontend, and architecture documentation
make check
```

---

## Architecture Documentation

| Document | Purpose |
| --- | --- |
| [doc/specifications/README.md](doc/specifications/README.md) | Canonical system specification and reading order |
| [doc/specifications/00-project-overview.md](doc/specifications/00-project-overview.md) | Production pipeline, scope, and engineering principles |
| [doc/specifications/architecture/README.md](doc/specifications/architecture/README.md) | System, application, workflow, and container architecture |
| [doc/specifications/decisions/README.md](doc/specifications/decisions/README.md) | Architecture Decision Records (ADRs) |
| [doc/specifications/24-acceptance-criteria.md](doc/specifications/24-acceptance-criteria.md) | Quality assurance and v1.0.0 acceptance criteria |
| [doc/setup/platform-credentials.md](doc/setup/platform-credentials.md) | Provider credentials and API integration guide |
| [AGENTS.md](AGENTS.md) | Core engineering contract and architectural rules |

---

## License

This project is licensed under the terms of the [MIT License](LICENSE).
