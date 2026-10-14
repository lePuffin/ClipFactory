---
description: "Implement one or more specific ClipFactory requirements by ID, with tagged tests and validation."
agent: "agent"
argument-hint: "Requirement IDs, e.g. CF-REQ-401 CF-REQ-402"
---
Implement requirement(s) **${input:ids}** exactly as specified.

1. Open each ID's definition (see [traceability.md](../../doc/specifications/traceability.md)
   for its document) and quote its acceptance criteria.
2. Check related IDs, architecture links, ADRs and
   [26-open-decisions-and-conflicts.md](../../doc/specifications/26-open-decisions-and-conflicts.md).
   Do not reinterpret the requirement; if it is ambiguous, stop and ask.
3. Write one or more tests per acceptance bullet, tagged
   `@pytest.mark.req("<ID>")` (or ID-prefixed Vitest/Playwright titles).
4. Implement following [AGENTS.md](../../AGENTS.md) layering and provider rules.
5. Run the relevant validation commands and `python3 scripts/check_docs.py`.
6. Update the traceability status for these IDs if and only if tests pass.

Report per ID: status, tests, files changed, validation output.
