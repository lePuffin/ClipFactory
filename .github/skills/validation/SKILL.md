---
name: validation
description: "ClipFactory validation gate. Use before declaring any task, phase or release complete: runs backend, frontend and documentation checks, verifies traceability, and produces an honest validation report."
---
# Validation skill

Canonical gate: [CF-NFR-153](../../../doc/specifications/21-testing.md#cf-nfr-153--quality-gate-commands).

## Commands

Run only for parts that exist; report skipped parts explicitly.

```bash
# documentation (always)
python3 scripts/check_docs.py

# backend
cd backend
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest

# frontend
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
```

Once the root `Makefile` exists: `make check`.

## Also verify

- [ ] Traceability report: no `Test`-method requirement in scope lacks a tagged test.
- [ ] No new prohibited dependency (architecture tests pass).
- [ ] No secrets in diffs (`.env` untracked).
- [ ] Documentation updated for behaviour changes.
- [ ] Integrations: state for each provider whether it was tested with fakes,
      mocked HTTP, or verified live.

## Report format

```
## Validation report
| Check | Command | Result |
|---|---|---|
| Docs | python3 scripts/check_docs.py | PASS / FAIL (n problems) |
| … | … | … |
Coverage: backend x% branch, frontend y% lines
Requirements in scope: … (implemented/verified)
Not verified: …
```

Never write PASS for a command you did not run.
