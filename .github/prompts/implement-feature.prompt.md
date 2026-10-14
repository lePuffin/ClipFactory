---
description: "Implement a ClipFactory feature end-to-end from the specification (tests + code + validation)."
agent: "agent"
argument-hint: "Feature or area, e.g. 'caption layout' or 'publishing mode'"
---
Implement the ClipFactory feature: **${input:feature}**.

The specification in [doc/specifications/](../../doc/specifications/README.md) is the
source of truth. Follow [AGENTS.md](../../AGENTS.md) and the
[implementation skill](../skills/implementation/SKILL.md).

1. Identify every `CF-REQ`/`CF-NFR` ID that governs this feature (use
   [traceability.md](../../doc/specifications/traceability.md)); list them before coding.
2. Read their acceptance criteria, related architecture sections, ADRs and
   Open Decisions. If anything is missing or conflicting, stop and report it
   instead of guessing.
3. Inspect existing code and tests you will touch.
4. Write tests tagged with the IDs, then implement in the correct layer.
5. Run the [validation skill](../skills/validation/SKILL.md) commands for the parts changed.
6. Update traceability status only for IDs whose tagged tests pass.

Report: IDs covered, files changed, validation results (actual output), and
anything not verified.
