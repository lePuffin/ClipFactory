---
name: specification-review
description: "Review ClipFactory specifications for completeness, testability, consistency and traceability. Use when reviewing or approving the doc/specifications baseline, after editing requirements, or before starting an implementation phase (Phase 0)."
---
# Specification review skill

Scope: `doc/specifications/**`, `AGENTS.md`, `.github/**`.

## Automated checks

```bash
python3 scripts/check_docs.py
```

Checks links/anchors, ID definitions/references, traceability coverage,
OD/ADR/AC references and prohibited terminology. It does not judge content —
the checklist below does.

## Checklist

**Completeness**
- [ ] Every pipeline stage in [00-project-overview.md](../../../doc/specifications/00-project-overview.md#canonical-pipeline) has requirements ([02 map](../../../doc/specifications/02-functional-requirements.md#pipeline-coverage)).
- [ ] Every requirement has acceptance criteria with concrete values.
- [ ] Every acceptance scenario in [24](../../../doc/specifications/24-acceptance-criteria.md) references requirements that exist.

**Testability**
- [ ] No vague words ("fast", "robust", "user-friendly") without a metric or an OD.
- [ ] Failure behaviour specified (codes, events).

**Consistency**
- [ ] Config keys/defaults in requirements match [18-configuration.md](../../../doc/specifications/18-configuration.md).
- [ ] Entity fields match [04-domain-model.md](../../../doc/specifications/04-domain-model.md).
- [ ] Stage names, event types, issue codes identical across 11, 16, 20, architecture and diagrams.
- [ ] Diagrams match the text.
- [ ] Terminology follows the glossary.

**Architecture guardrails**
- [ ] No prohibited technology introduced; providers only via ports.
- [ ] No LLM use for deterministic work.

**Honesty**
- [ ] Unknowns are ODs with provisional choices; no fake certainty; no claims of verified integrations.
- [ ] `[Derived]` requirements are marked for owner review.

## Output

Findings list (blocking / non-blocking) with file + ID + suggested fix, and
the `check_docs.py` result. Do not edit files while reviewing unless asked.
