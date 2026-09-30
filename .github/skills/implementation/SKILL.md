---
name: implementation
description: "Step-by-step procedure for implementing a ClipFactory requirement or feature from the specification: locate requirements, read acceptance criteria, write tagged tests, implement within the layers, validate, update traceability."
argument-hint: "Requirement IDs (e.g. CF-REQ-401) or feature name"
---
# Implementation skill

## Procedure

1. **Scope.** List the requirement IDs. Find them via
   [traceability.md](../../../doc/specifications/traceability.md) (ID → document → component).
2. **Read.** For each ID: description, behaviour, failure, acceptance,
   related IDs. Read linked architecture sections and ADRs. Check
   [26-open-decisions-and-conflicts.md](../../../doc/specifications/26-open-decisions-and-conflicts.md).
3. **Check prerequisites.** Entities in [04-domain-model.md](../../../doc/specifications/04-domain-model.md),
   config keys in [18-configuration.md](../../../doc/specifications/18-configuration.md),
   ports in [provider-architecture.md](../../../doc/specifications/architecture/provider-architecture.md).
   Missing? Stop and route to the architect.
4. **Inspect code.** Find existing modules/tests to extend; follow patterns.
5. **Tests first.** Turn each acceptance bullet into a test tagged with the
   ID. Include boundaries and failure paths. Use fakes and the fake clock.
6. **Implement.** Smallest change that passes, in the correct layer
   ([architecture skill](../architecture/SKILL.md)). Deterministic logic in
   code; LLM only through `generate_structured` with a versioned prompt.
7. **Events and errors.** Emit the specified Run Events; use specified error
   and issue codes verbatim.
8. **Validate.** Run the [validation skill](../validation/SKILL.md) for the parts changed.
9. **Traceability.** Set status `Implemented` only for IDs whose tagged tests pass.
10. **Report.** IDs done, files changed, command results, unverified items.

## Red flags — stop and ask

- The requirement contradicts another requirement, ADR or existing tests.
- You need a new dependency, table, port or configuration key not in the spec.
- The only way to pass is to change or skip a test.
