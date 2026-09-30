---
description: "Change a ClipFactory requirement, architecture section or ADR safely and traceably."
agent: "architect"
argument-hint: "The behaviour change and why"
---
Update the ClipFactory specification for this change: **${input:change}**.

Follow [01-requirements.md § Changing requirements](../../doc/specifications/01-requirements.md#changing-requirements)
and [documentation.instructions.md](../instructions/documentation.instructions.md):

1. Find every affected requirement, configuration key, entity field, stage,
   event type, issue code, diagram and ADR (search the whole `doc/` tree).
2. State the current text, the proposed text, and the rationale. If the
   change conflicts with an accepted ADR, create a superseding ADR.
3. Edit the canonical location only; update references elsewhere. New IDs
   use the next free number in the document's block; never renumber.
4. Update [traceability.md](../../doc/specifications/traceability.md) and
   [24-acceptance-criteria.md](../../doc/specifications/24-acceptance-criteria.md).
5. Record resolved/new Open Decisions in
   [26-open-decisions-and-conflicts.md](../../doc/specifications/26-open-decisions-and-conflicts.md).
6. List tests that must change as a consequence (do not edit code here).
7. Run `python3 scripts/check_docs.py` and report the result.
