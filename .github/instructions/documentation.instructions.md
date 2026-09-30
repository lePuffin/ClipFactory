---
description: "Use when writing or editing ClipFactory documentation, specifications, requirements, ADRs, glossary, traceability, PlantUML diagrams, or agent customization files."
applyTo: "{doc/**,AGENTS.md,README.md,.github/**/*.md}"
---
# Documentation rules

Canonical reference: [doc/specifications/README.md](../../doc/specifications/README.md),
[01-requirements](../../doc/specifications/01-requirements.md).

- All specifications live under `doc/specifications/`. Do not create a
  parallel `docs/` tree.
- One canonical home per fact; link instead of restating. Configuration
  defaults: `18-configuration.md`. Entity fields: `04-domain-model.md`.
- Requirements use the template and ID blocks in `01-requirements.md`;
  headings `### CF-REQ-### — Title`. Never renumber or reuse IDs.
- Every new requirement gets a row in `traceability.md` and, if it changes
  "done", an update to `24-acceptance-criteria.md`.
- Requirements must be testable: concrete values, observable acceptance criteria.
- Mark not-in-brief requirements `[Derived]`; unknowns are `OD-###` Open
  Decisions, never "TBD".
- Architectural reversals need a new ADR (Status, Context, Decision,
  Consequences, Alternatives considered).
- Diagrams are PlantUML in `architecture/diagrams/` and must match the text.
- Terminology: Clip, not platform-specific names; follow `glossary.md`.
- Do not describe unimplemented or unverified functionality as working.
- Run `python3 scripts/check_docs.py` before finishing.
