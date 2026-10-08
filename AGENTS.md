# AGENTS.md — ClipFactory Engineering Contract

Binding rules for every AI agent and human contributor. Keep this file short;
details live in [doc/specifications/](doc/specifications/README.md).

## Project purpose

ClipFactory is a private, single-user application that researches recent
news, grounds one Story in independent Sources and verified Claims, writes a
script, plans and sources visuals, narrates, captions, composes a vertical
**Clip** (default 720×1280, 30 FPS, 60–90 s), evaluates it, revises it with
bounded targeted retries, publishes approved Clips to the platforms enabled
in the Content Profile, and tracks metrics. Overview:
[00-project-overview.md](doc/specifications/00-project-overview.md).

**Current state:** documentation baseline v1.0.0 (draft for owner review). No
application code exists yet. The implementation roadmap is
[25-roadmap.md](doc/specifications/25-roadmap.md).

## Terminology

- The produced video is a **Clip**. Never use "short(s)", "reel(s)" or "TikTok video" as product terms. <!-- terminology:allow -->
- YouTube, Instagram, TikTok, Facebook are **platforms**.
- Use the glossary: [glossary.md](doc/specifications/glossary.md) (Story,
  Source, Claim, Story Package, Asset, Run, Content Profile, Publication,
  Metric Snapshot, Provider, Evaluation, Retry, Stage, …).

## Source-of-truth hierarchy

1. Approved requirements (`CF-REQ-*`, `CF-NFR-*`)
2. Approved architecture ([architecture/](doc/specifications/architecture/README.md))
3. Approved ADRs ([decisions/](doc/specifications/decisions/README.md))
4. Tests
5. Implementation
6. Informal assumptions and comments

If artefacts conflict, **do not silently choose**. Record the conflict in
[26-open-decisions-and-conflicts.md](doc/specifications/26-open-decisions-and-conflicts.md),
update the appropriate specification or ADR (or ask the owner), then implement.

## Architecture principles

- Simplicity: one native backend process, PostgreSQL as the durable source of
  truth, narrowly scoped Dragonfly operational state, FFmpeg for final media
  assembly/probing, and local filesystem. HyperFrames and Manim are limited to
  the typed graphics authoring requirement (CF-REQ-263–265). Every dependency
  needs a concrete requirement.
- Layers: `domain` (pure) ← `ports` ← feature packages (use cases) ←
  `workflow` / `api`; `infrastructure` implements ports. Rules:
  [application-architecture.md](doc/specifications/architecture/application-architecture.md#dependency-rules).
- Provider isolation: external services only behind ports (`LLMProvider`,
  `NewsSource`, `MediaSourceProvider`, `ImageProvider`, `VideoProvider`,
  `TTSProvider`, `TranscriptionProvider`, `Publisher`, `StorageProvider`). No
  vendor names in domain/application code.
- Deterministic work (validation, media, timing, scoring, routing, retries,
  scheduling) is code, never an LLM. LLMs do language and judgement through
  single structured-output calls; no agent loops or LLM tool use at runtime.
- Evidence before narrative: Story → Sources → Claims → Script.
- Nothing is published unless the Clip is `approved`.
- LangGraph is confined to `workflow/`; workflow state holds IDs only.

## Prohibited unless a new approved ADR justifies it

Microservices, Kubernetes, service meshes, Celery, RQ, Temporal, Kafka,
RabbitMQ, Redis, KeyDB, vector databases, a second durable database,
additional agent frameworks, JEV, OpenShorts or OpenMontage as dependencies,
Black/isort/Flake8, abstractions without a current consumer, empty
directories created to match a diagram. Dragonfly is permitted only for the
rolling LLM RPM/circuit state approved by ADR-016.

## Implementation discipline

- Read the relevant specification sections and ADRs before coding; inspect
  existing code before changing it.
- Implement requirements as written. Do not invent requirements; if something
  is missing, raise it (Open Decision) instead of guessing.
- Small modules, explicit dependencies, typed code, clear errors.
- Keep changes scoped to the task. Update documentation in the same change
  when behaviour changes.
- Never claim an integration works unless it was exercised; state exactly
  what was verified (fake, mocked HTTP, live).
- Never commit secrets. Credentials come from environment variables only.

## Testing requirements

- Tests are executable requirements. Never weaken, skip or delete a test to
  make code pass.
- Tag tests with requirement IDs (`@pytest.mark.req("CF-REQ-401")`; test
  titles in Vitest/Playwright).
- Normal test runs use fakes; no network or credentials. Live tests only with
  `LIVE_TESTS=1`.
- Strategy and coverage policy: [21-testing.md](doc/specifications/21-testing.md).

## Validation commands

```bash
# backend (from backend/)
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

# frontend (from frontend/)
npm run lint
npm run typecheck
npm run test
npm run build

# documentation (from repository root)
python3 scripts/check_docs.py

# everything (once the Makefile exists, Phase 1)
make check
```

A task is not complete until the applicable commands pass. Report failures
honestly.

## Handling ambiguity

1. Search the specification (topic doc, glossary, ADRs, open decisions).
2. If an Open Decision has a provisional choice, use it behind its boundary.
3. If still ambiguous, and the choice is reversible and local, choose the
   simplest option consistent with the principles and record it (ADR or OD
   note). If it changes behaviour, scope or architecture, stop and ask.

## Changing requirements

Use [.github/prompts/update-specification.prompt.md](.github/prompts/update-specification.prompt.md):
edit the requirement in its topic document → update
[traceability.md](doc/specifications/traceability.md) and acceptance criteria →
add/supersede an ADR if architectural → update tests → implement → run
`python3 scripts/check_docs.py`. Requirement IDs are never renumbered or reused.

## Agents

Custom agents live in [.github/agents/](.github/agents/): `clipfactory`
(orchestrator), `architect`, `backend`, `frontend`, `qa`, `reviewer`
(read-only). Skills in [.github/skills/](.github/skills/), prompts in
[.github/prompts/](.github/prompts/).
