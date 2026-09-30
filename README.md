# ClipFactory

ClipFactory is a private, single-user application that autonomously produces
vertical news **Clips**: it researches recent news, selects a Story, grounds
it in independent Sources and verified Claims, writes a script, plans and
sources visuals, generates narration and captions, composes a 720×1280 Clip
with FFmpeg, evaluates it, revises it when needed, publishes approved Clips to
YouTube, Instagram, TikTok and Facebook, and tracks post-publication metrics.

> **Status:** v1.0.0 documentation baseline (draft for owner review).
> The application has not been implemented yet.

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

Python 3.13+, uv, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL,
LangGraph, httpx, FFmpeg · React, TypeScript, Vite, Tailwind CSS · Ruff,
Pyright, pytest, ESLint, Prettier, Vitest, Playwright, GitHub Actions.

## Validating the documentation

```bash
python3 scripts/check_docs.py
```

## License

[MIT](LICENSE)
