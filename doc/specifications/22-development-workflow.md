# 22 — Development Workflow

How the repository is organised, built, validated and changed.
Agent-specific rules: [AGENTS.md](../../AGENTS.md).

## Repository layout (target for v1.0.0)

Directories are created when they receive their first real file; do not
create empty directories to match this tree.

```text
ClipFactory/
├── AGENTS.md                      # engineering contract for agents
├── README.md
├── LICENSE
├── Makefile                       # root task runner (make check, make dev, …)
├── .pre-commit-config.yaml
├── .env.example                   # placeholders only
├── .github/
│   ├── copilot-instructions.md
│   ├── agents/  instructions/  skills/  prompts/
│   └── workflows/ci.yml
├── doc/specifications/            # canonical specification (this tree)
├── doc/setup/                     # owner setup guides (credentials), non-normative
├── scripts/
│   ├── check_docs.py              # documentation validation (exists now)
│   └── check_traceability.py      # requirement ↔ test report (Phase 1)
├── backend/
│   ├── pyproject.toml             # uv project, Ruff, Pyright, pytest config
│   ├── uv.lock
│   ├── alembic.ini
│   ├── src/clipfactory/
│   │   ├── domain/                # entities, value objects, rules (pure)
│   │   ├── ports/                 # provider + repository protocols
│   │   ├── research/              # use cases: research … claims
│   │   ├── planning/              # story package, script, visual plan
│   │   ├── assets/                # asset manager
│   │   ├── production/            # narration, transcription, captions
│   │   ├── composition/           # composition spec, FFmpeg command building
│   │   ├── evaluation/            # gates, validators, semantic evaluator, retry planner
│   │   ├── publishing/
│   │   ├── analytics/
│   │   ├── workflow/              # LangGraph graph, run service, scheduler
│   │   ├── api/                   # FastAPI routers, schemas, SSE
│   │   ├── infrastructure/        # db, migrations, storage, media runner, providers, settings, logging
│   │   ├── prompts/               # versioned LLM prompt templates
│   │   ├── bootstrap.py           # composition root
│   │   └── cli.py                 # `clipfactory` CLI
│   └── tests/{unit,contract,integration,e2e,live,fixtures}/
└── frontend/
    ├── package.json, package-lock.json, vite.config.ts, tsconfig.json
    ├── src/{api,components,features,pages,hooks,types}/
    └── tests/e2e/
```

The package responsibilities are specified in
[architecture/application-architecture.md](architecture/application-architecture.md#backend-packages).

**Deviation from the project brief:** the brief sketched `pyproject.toml` and
`package.json` at the repository root. This baseline places them in `backend/`
and `frontend/` so each toolchain runs from its own directory with no
cross-tool configuration; the root `Makefile` provides one entry point. See
[26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md#known-conflicts).

## Prerequisites

- Python 3.13+ and `uv`
- Node.js 22 LTS and npm
- PostgreSQL 16+ installed natively (e.g. `sudo apt install postgresql` in WSL2)
- FFmpeg 6+ with `libx264`, `libass` and `aac` (`ffmpeg -hide_banner -buildconf`)
- Optional: GPU + CUDA for faster Whisper

## Commands

| Purpose | Command |
| --- | --- |
| Install backend | `cd backend && uv sync --locked --all-groups` |
| Install frontend | `cd frontend && npm ci` |
| DB migrate | `cd backend && uv run alembic upgrade head` |
| Run backend (dev) | `cd backend && uv run clipfactory serve --reload` |
| Run frontend (dev) | `cd frontend && npm run dev` (proxies `/api` to the backend) |
| Demo with fakes | `APP_ENV=development` and all provider selections set to `fake` |
| All checks | `make check` |
| Backend checks | `make backend-check` |
| Frontend checks | `make frontend-check` |
| Docs check | `make docs-check` or `python3 scripts/check_docs.py` |
| E2E (fakes) | `make e2e` — starts PostgreSQL, backend with all providers `fake`, runs Playwright (created in Phase 1, used by CI) |
| Pre-commit | `pre-commit install` then automatic; `pre-commit run --all-files` |

Quality gate commands are canonical in [21-testing.md](21-testing.md#cf-nfr-153--quality-gate-commands).

## Tooling decisions

| Concern | Tool | Notes |
| --- | --- | --- |
| Python env/deps | uv | [ADR-001](decisions/ADR-001-python-and-uv.md) |
| Lint + format (Python) | Ruff | No Black/isort/Flake8. Rule sets: `E,F,W,I,B,UP,S,SIM,RUF,ASYNC,PT` |
| Types (Python) | Pyright | CF-NFR-022 |
| Tests (Python) | pytest, pytest-asyncio, pytest-cov | |
| Lint (TS) | ESLint (typescript-eslint, react-hooks) | Rule forbidding `dangerouslySetInnerHTML` |
| Format (TS) | Prettier | |
| Tests (TS) | Vitest + Testing Library; Playwright for E2E | |
| Hooks | pre-commit | Runs Ruff, Prettier, docs check, trailing whitespace, large-file guard |

## Documentation validation

`scripts/check_docs.py` (Python standard library only) verifies:

1. Every relative Markdown link in `doc/`, `.github/`, `AGENTS.md` and
   `README.md` resolves to an existing file (and heading anchor where given).
2. Every `CF-REQ`/`CF-NFR` ID is defined exactly once and every referenced
   ID is defined.
3. Every defined ID appears in [traceability.md](traceability.md).
4. Every referenced `OD-###` exists in
   [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md), and every
   `ADR-###` reference has a file in [decisions/](decisions/README.md).
5. Prohibited product terminology does not appear outside explicitly allowed
   lines (marked `terminology:allow`).

## Change workflow

1. Read the relevant specification and ADRs before changing code.
2. If behaviour changes, update the specification first
   (`.github/prompts/update-specification.prompt.md`).
3. Write or update tests tagged with requirement IDs.
4. Implement.
5. Run `make check`.
6. Commit with a Conventional Commit message referencing IDs, e.g.
   `feat(evaluation): targeted retry routing (CF-REQ-410)`.

Branches: `main` (release), `dev` (integration), short-lived feature branches.

## Continuous integration

`.github/workflows/ci.yml` runs on pushes and pull requests:

| Job | Runs when | Steps |
| --- | --- | --- |
| `docs` | always | `python3 scripts/check_docs.py` |
| `backend` | `backend/pyproject.toml` exists | PostgreSQL 16 service; install FFmpeg; `uv sync --locked`; Ruff check; Ruff format check; Pyright; `alembic upgrade head`; pytest with coverage |
| `frontend` | `frontend/package.json` exists | `npm ci`; lint; typecheck; test; build |
| `e2e` | both exist | Build frontend; start backend with fakes; Playwright |

Jobs for not-yet-existing parts are skipped rather than failing so the
documentation baseline passes CI before Phase 1.

## Definition of done (per change)

- Specification, traceability and tests updated together.
- `make check` passes locally; CI green.
- No prohibited technology; no provider coupling outside adapters.
- No unverified claims about integrations in docs, commits or summaries.
