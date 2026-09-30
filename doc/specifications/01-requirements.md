# 01 — Requirements Conventions

This document defines how requirements are written, identified and
maintained. It contains no requirements itself.

## Identifier scheme

| Prefix | Meaning | Where defined |
| --- | --- | --- |
| `CF-REQ-###` | Functional requirement | Topic documents `05`–`18`, `20` |
| `CF-NFR-###` | Non-functional requirement (quality, security, testing, constraints) | `03`, `19`, `21` |
| `CF-AC-###` | v1.0.0 acceptance scenario | [24-acceptance-criteria.md](24-acceptance-criteria.md) |
| `OD-###` | Open Decision | [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md) |
| `ADR-###` | Architecture Decision Record | [decisions/](decisions/README.md) |

IDs are allocated in blocks per document so that adding a requirement never
forces renumbering. Gaps are intentional.

| Block | Document |
| --- | --- |
| CF-REQ-100–149 | [05-research-and-source-grounding.md](05-research-and-source-grounding.md) |
| CF-REQ-150–199 | [06-story-and-script.md](06-story-and-script.md) |
| CF-REQ-200–249 | [07-asset-management.md](07-asset-management.md) |
| CF-REQ-250–299 | [08-visual-production.md](08-visual-production.md) |
| CF-REQ-300–349 | [09-audio-and-tts.md](09-audio-and-tts.md) |
| CF-REQ-350–399 | [10-composition.md](10-composition.md) |
| CF-REQ-400–449 | [11-evaluation-and-retry.md](11-evaluation-and-retry.md) |
| CF-REQ-450–499 | [12-publishing.md](12-publishing.md) |
| CF-REQ-500–549 | [13-analytics.md](13-analytics.md) |
| CF-REQ-550–599 | [14-content-profiles.md](14-content-profiles.md) |
| CF-REQ-600–649 | [15-ui-and-dashboard.md](15-ui-and-dashboard.md) |
| CF-REQ-650–699 | [16-scheduling-and-runs.md](16-scheduling-and-runs.md) |
| CF-REQ-700–749 | [17-manual-input.md](17-manual-input.md) |
| CF-REQ-750–799 | [18-configuration.md](18-configuration.md) |
| CF-REQ-850–899 | [20-observability.md](20-observability.md) |
| CF-NFR-001–099 | [03-non-functional-requirements.md](03-non-functional-requirements.md) |
| CF-NFR-100–149 | [19-security.md](19-security.md) |
| CF-NFR-150–199 | [21-testing.md](21-testing.md) |

Rules:

- An ID is defined exactly once, as a level-3 heading `### CF-REQ-### — Title`.
- IDs are never renumbered or reused. A removed requirement stays in place with
  `Status: Retired` and a reason.
- Every defined ID must appear in [traceability.md](traceability.md).
- `scripts/check_docs.py` enforces these rules.

## Requirement template

Fields not applicable to a requirement are omitted.

```markdown
### CF-REQ-### — Title

- **Description:** The system shall …
- **Rationale:** Why it exists.
- **Preconditions:** State required before the behaviour applies.
- **Inputs:** Data consumed.
- **Behaviour:** Expected behaviour, precise and testable.
- **Failure:** What happens when it cannot be satisfied.
- **Acceptance:**
  - Observable, verifiable criteria (examples with concrete values).
- **Related:** CF-REQ-…, [architecture link], ADR-…
```

## Wording

- **shall** — mandatory for v1.0.0.
- **should** — recommended; deviation must be justified in the implementation
  notes or an ADR.
- **may** — optional.
- Numeric defaults quoted in requirements refer to configuration keys whose
  canonical defaults are in [18-configuration.md](18-configuration.md). If a
  requirement and 18 disagree, that is a conflict to be recorded.

## Markers

- **[Derived]** — not literally in the project brief but necessary for a
  complete, safe or testable system. The owner should confirm or reject these
  during review.
- **Provisional** — a concrete value chosen so that implementation can proceed;
  linked to an `OD-###` that may change it.

## Status

The whole baseline is `Draft — v1.0.0 baseline for owner review`. Once the
owner approves, the status of this file line changes to `Approved` and the
source-of-truth hierarchy in [README.md](README.md) applies fully.

**Baseline status:** Draft — v1.0.0 baseline for owner review.

## Changing requirements

1. Edit the requirement in its topic document (never only in an index).
2. Update [traceability.md](traceability.md) and, if needed,
   [24-acceptance-criteria.md](24-acceptance-criteria.md).
3. If the change reverses an architectural choice, add or supersede an ADR.
4. Update tests, then implementation.
5. Run `python3 scripts/check_docs.py`.

Use the prompt `.github/prompts/update-specification.prompt.md` for this.
