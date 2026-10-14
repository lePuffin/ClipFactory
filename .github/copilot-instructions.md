# ClipFactory — Repository Instructions for Copilot

Read [AGENTS.md](../AGENTS.md) first; it is the binding engineering contract.
The canonical specification is [doc/specifications/](../doc/specifications/README.md).

## Before changing anything

1. Identify the requirement IDs involved (search `doc/specifications/` for the
   behaviour; see [traceability.md](../doc/specifications/traceability.md)).
2. Read those requirements, the related architecture section and ADRs.
3. Inspect the existing code and tests you will touch. Follow existing patterns.
4. Check [26-open-decisions-and-conflicts.md](../doc/specifications/26-open-decisions-and-conflicts.md)
   for open decisions affecting the task.

## While implementing

- Respect the layering and dependency rules
  ([application-architecture.md](../doc/specifications/architecture/application-architecture.md#dependency-rules)).
- Keep providers isolated behind ports; never import vendor SDKs or `httpx`
  outside `infrastructure/`.
- Use normal code for deterministic work; LLMs only for language/judgement via
  structured output.
- Do not add abstractions, layers or dependencies without a current consumer
  and a concrete requirement. Never introduce prohibited technology (see AGENTS.md).
- Use canonical terms (**Clip**, Story, Source, Claim, Story Package, Asset,
  Run, Content Profile, Publication, Metric Snapshot, Evaluation, Retry).
- Configuration keys and defaults come from
  [18-configuration.md](../doc/specifications/18-configuration.md); do not hard-code them.

## Tests and validation

- Write or update tests tagged with requirement IDs. Never weaken or delete
  tests to make code pass.
- Run the validation commands in AGENTS.md for the parts you changed; report
  the actual results.

## Documentation

- If behaviour changes, update the specification first, then traceability,
  then tests, then code. Never silently change a requirement.
- Run `python3 scripts/check_docs.py` after editing documentation.

## Honesty

- Never claim an integration works unless it was executed. Distinguish
  "tested with fakes", "tested with mocked HTTP" and "verified live".
- If blocked, say what is blocking and what was tried.
