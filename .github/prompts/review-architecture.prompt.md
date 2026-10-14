---
description: "Critically review ClipFactory architecture and specification for consistency, simplicity, and implementability (read-only)."
agent: "reviewer"
argument-hint: "Optional focus, e.g. 'workflow and retry' or 'whole baseline'"
---
Review the ClipFactory architecture and specification. Focus: **${input:focus:whole baseline}**.

Use the [specification-review skill](../skills/specification-review/SKILL.md) and the
[architecture skill](../skills/architecture/SKILL.md). Read
[architecture/README.md](../../doc/specifications/architecture/README.md), the ADRs
and the requirements in scope.

Check in particular:
- Architecture satisfies every in-scope requirement; no requirement lacks a component.
- Diagrams match the text (stages, packages, flows).
- Provider boundaries are complete and nothing vendor-specific leaks into domain/application.
- No prohibited technology or unnecessary abstraction.
- Stage names, event types, issue codes and config keys are consistent across documents.
- Open decisions are real decisions with provisional choices.
- A future agent could implement from these documents without the original brief.

Run `python3 scripts/check_docs.py`. Do not modify files. Output in the
reviewer's format with blocking and non-blocking findings.
