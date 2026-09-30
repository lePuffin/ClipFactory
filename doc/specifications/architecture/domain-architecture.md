# Domain Architecture

Canonical field-level model: [04-domain-model.md](../04-domain-model.md).
Diagram: [diagrams/domain-model.puml](diagrams/domain-model.puml).

## Bounded areas

ClipFactory is small enough for **one** domain package, organised into
cohesive areas rather than separate bounded contexts with translation layers.

| Area | Aggregates / value objects | Owned rules |
| --- | --- | --- |
| Editorial configuration | `ContentProfile` + `DurationPolicy`, `OutputSpec`, `VoiceSpec`, `Schedule`, `ResearchPolicy`, `MusicPolicy` | Profile validation, duration bounds |
| Research & grounding | `Source`, `Story`, `StorySource`, `Claim`, `Evidence` | Independence counting, support levels, acceptance, evidence verification |
| Editorial production | `StoryPackage`, `Script`, `VisualPlan`, `SocialMetadata` | Versioning, word budget, script-gate rules, timing reconciliation |
| Media | `Asset`, `Provenance`, `GenerationInfo` | Provenance invariants, reuse eligibility |
| Output | `Clip`, `NarrationTrack`, `CaptionTrack`, `AssetUsage` | Approval state machine |
| Quality | `Evaluation`, `Issue`, `Action` | `passed` derivation, routing table |
| Distribution | `Publication`, `PublicationRequest`, `MetricSnapshot`, `EstimatedRevenue` | Approved-only publishing, idempotency, revenue basis |
| Execution | `Run`, `RunEvent`, `Stage` | Run status machine, event ordering |

## Placement of logic

| Kind of logic | Location | Example |
| --- | --- | --- |
| Invariants of one aggregate | Entity/value object methods and constructors | `Claim.accept()` refuses `unsupported` |
| Pure calculations over several objects | Domain services (pure functions) in `domain/` | `independent_source_count(story, sources)`, `word_budget(profile)`, `route_issues(issues)` |
| Orchestration with I/O | Application use cases in feature packages | `SelectStory.execute(run_id)` |
| Framework/vendor specifics | Infrastructure | SQLAlchemy mappings, HTTP adapters |

## Rules

- Domain objects are plain Python (dataclasses or Pydantic models without
  I/O). Using Pydantic in the domain is allowed for validation; SQLAlchemy is
  not (separate persistence models + mappers).
- Domain code receives time through a `Clock` argument, never `datetime.now()`.
- Enumerations (`Stage`, `RunEventType`, `IssueCode`, `ActionType`,
  `Platform`, …) are defined once in the domain and reused by API schemas.
- The issue routing table from [11-evaluation-and-retry.md](../11-evaluation-and-retry.md#issue-routing-table-canonical)
  is domain data (a constant mapping) with a unit test per row.
- "Provider" is not a domain entity; the domain stores provider names only.
