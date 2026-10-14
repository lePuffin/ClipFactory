# Traceability Matrix

Links every requirement to the architecture component(s) that implement it,
its verification method, and the v1.0.0 acceptance scenario that covers it.
The future implementation agent uses this table to decide whether v1.0.0 is
complete ([24-acceptance-criteria.md](24-acceptance-criteria.md)).

## How to read and maintain

- **Component**: backend package under `backend/src/clipfactory/` (see
  [application-architecture](architecture/application-architecture.md#backend-packages)),
  `frontend`, or a repository-level mechanism.
- **Verification**: `Unit`, `Contract`, `Integration`, `E2E`, `Vitest`,
  `Playwright` are automated test levels ([21-testing.md](21-testing.md#test-levels)).
  `CI` = enforced by a CI step; `Review` = reviewer checklist;
  `Measurement` = measured and reported in Phase 10; `Manual` = manual
  procedure. Requirements with at least one automated test level must have a
  test tagged with the ID (CF-NFR-150).
- **Status**: `Not started` → `In progress` → `Implemented` (code + tagged
  tests pass) → `Verified` (acceptance scenario passed). Only the
  implementation agent changes status, and only after running the tests.
- Adding a requirement requires adding a row here; `scripts/check_docs.py`
  fails otherwise.

## Functional requirements

| ID | Title | Component | Verification | Acceptance | Status |
| --- | --- | --- | --- | --- | --- |
| [CF-REQ-100](05-research-and-source-grounding.md) | Profile-owned candidate discovery and research feed configuration | `research`, `domain`, `infrastructure.db`, `workflow` | Unit, Integration | CF-AC-001 | In progress |
| [CF-REQ-101](05-research-and-source-grounding.md) | Article retrieval and main-text extraction without shared site chrome | `research` | Unit, Integration | CF-AC-001 | In progress; regression fixtures and public ESPN extraction verified |
| [CF-REQ-102](05-research-and-source-grounding.md) | Exact duplicate removal | `research` | Unit, Integration | CF-AC-001 | Not started |
| [CF-REQ-103](05-research-and-source-grounding.md) | Source quality evaluation | `research` | Unit, Integration | CF-AC-001 | Not started |
| [CF-REQ-104](05-research-and-source-grounding.md) | Syndication and near-duplicate detection | `research` | Unit, Integration | CF-AC-001 | Not started |
| [CF-REQ-105](05-research-and-source-grounding.md) | Story clustering | `research` | Unit, Integration | CF-AC-002 | Not started |
| [CF-REQ-106](05-research-and-source-grounding.md) | Independent source counting | `research` | Unit, Integration | CF-AC-002 | Not started |
| [CF-REQ-107](05-research-and-source-grounding.md) | Story scoring and selection | `research` | Unit, Integration | CF-AC-002 | Not started |
| [CF-REQ-108](05-research-and-source-grounding.md) | Profile filters on independently classified Stories | `research` | Unit, Integration | CF-AC-002 | In progress |
| [CF-REQ-109](05-research-and-source-grounding.md) | Story novelty [Derived] | `research` | Unit, Integration | CF-AC-002 | Implemented; tagged unit tests (URL rule, completed-only 48 h window, prompt instruction) and SQLite repository test; live hosted Runs pending |
| [CF-REQ-110](05-research-and-source-grounding.md) | Additional source gathering | `research` | Unit, Integration | CF-AC-003 | Not started |
| [CF-REQ-111](05-research-and-source-grounding.md) | Minimum source requirement | `research` | Unit, Integration | CF-AC-002 | Not started |
| [CF-REQ-112](05-research-and-source-grounding.md) | Claim extraction with evidence | `research` | Unit, Integration | CF-AC-003 | In progress; tagged extraction tests pass, complete-fact prompt exercised in live Football Run 448a5795 |
| [CF-REQ-113](05-research-and-source-grounding.md) | Deterministic evidence verification | `research` | Unit, Integration | CF-AC-003 | Not started |
| [CF-REQ-114](05-research-and-source-grounding.md) | Support level | `research` | Unit, Integration | CF-AC-003 | Not started |
| [CF-REQ-115](05-research-and-source-grounding.md) | Claim acceptance | `research` | Unit, Integration | CF-AC-003 | Not started |
| [CF-REQ-116](05-research-and-source-grounding.md) | Per-segment attribution with at most one spoken mention per publisher | `research`, `planning` | Unit, Integration | CF-AC-003, CF-AC-004 | In progress |
| [CF-REQ-117](05-research-and-source-grounding.md) | Minimum grounded content and bounded thin-script fallback | `research`, `workflow`, `infrastructure.db` | Unit, Integration, Live | CF-AC-003 | Implemented; tagged fallback/SQLite tests verify shared durable limit and safeguards; live Run 44a5d760 replaced a thin Porro Story and completed with approved Clip a78de1bc; three consecutive fresh Football successes verified (560338fd, 44a5d760, 58c77635), all awaiting owner approval |
| [CF-REQ-118](05-research-and-source-grounding.md) | Research persistence | `research` | Unit, Integration | CF-AC-001 | Not started |
| [CF-REQ-150](06-story-and-script.md) | Story Package creation | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-151](06-story-and-script.md) | Key facts | `planning` | Unit, Integration | CF-AC-004 | In progress; tagged tests verify key-fact ranking does not cap extracted Claims |
| [CF-REQ-152](06-story-and-script.md) | Story Package versioning | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-153](06-story-and-script.md) | Grounded script generation | `planning` | Unit, Integration | CF-AC-004, CF-AC-033 | Not started |
| [CF-REQ-154](06-story-and-script.md) | Script language | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-155](06-story-and-script.md) | Duration budget | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-156](06-story-and-script.md) | Segment structure | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-157](06-story-and-script.md) | Hook | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-158](06-story-and-script.md) | Script gate, including repeated spoken attribution, paraphrased restatements, spoken calls to action, filler padding and headline fragments | `planning` | Unit, Integration | CF-AC-004 | In progress |
| [CF-REQ-159](06-story-and-script.md) | Indexed narration-only revision with accepted-Claim provenance, preserved attribution and explicit word bounds | `planning`, `workflow` | Unit, Integration | CF-AC-004 | In progress; fake-model convergence regressions verified, live convergence unverified |
| [CF-REQ-160](06-story-and-script.md) | Social metadata | `planning` | Unit, Integration | CF-AC-004 | Implemented (live pending) |
| [CF-REQ-161](06-story-and-script.md) | Attribution in metadata [Derived] | `planning` | Unit, Integration | CF-AC-004 | Implemented (live pending) |
| [CF-REQ-162](06-story-and-script.md) | Synthetic media disclosure flags [Derived] | `planning` | Unit, Integration | CF-AC-004 | Not started |
| [CF-REQ-163](06-story-and-script.md) | Narrative beats and editorial intent | `planning`, `evaluation` | Unit, Integration | CF-AC-026 | Not started |
| [CF-REQ-164](06-story-and-script.md) | Evidence-bound engagement | `planning`, `evaluation` | Unit, Review | CF-AC-026 | Not started |
| [CF-REQ-165](06-story-and-script.md) | Optional audience invitation | `planning` | Unit, Integration | CF-AC-026 | Not started |
| [CF-REQ-200](07-asset-management.md) | Saved Asset library and paginated listing | `assets`, `infrastructure.storage`, `api` | Unit, Integration | CF-AC-006 | In progress |
| [CF-REQ-201](07-asset-management.md) | Mandatory provenance | `assets` | Unit, Integration | CF-AC-006, CF-AC-033 | Not started |
| [CF-REQ-202](07-asset-management.md) | Content-addressed storage | `assets`, `infrastructure.storage` | Unit, Integration | CF-AC-006 | Not started |
| [CF-REQ-203](07-asset-management.md) | Attribution capture | `assets` | Unit, Integration | CF-AC-006 | Not started |
| [CF-REQ-204](07-asset-management.md) | Reuse first | `assets` | Unit, Integration | CF-AC-005 | Not started |
| [CF-REQ-205](07-asset-management.md) | Library matching | `assets` | Unit, Integration | CF-AC-005 | In progress |
| [CF-REQ-206](07-asset-management.md) | Reuse variety [Derived] | `assets` | Unit, Integration | CF-AC-005 | Not started |
| [CF-REQ-207](07-asset-management.md) | External media acquisition | `assets`, `infrastructure.providers.media` | Unit, Contract, Integration | CF-AC-006 | Not started |
| [CF-REQ-208](07-asset-management.md) | Media generation; cancellation-safe import, retained output, Wan fallback and cached model download | `assets`, `infrastructure.providers.media` | Unit, Contract, Integration | CF-AC-006 | In progress |
| [CF-REQ-209](07-asset-management.md) | Deterministic fallback card | `assets`, `workflow`, `evaluation`, `infrastructure.media` | Unit, Integration | CF-AC-006 | Implemented |
| [CF-REQ-210](07-asset-management.md) | Downloaded media validation | `assets`, `infrastructure.media` | Unit, Contract, Integration | CF-AC-006 | Not started |
| [CF-REQ-211](07-asset-management.md) | Store generated media for future reuse | `assets` | Unit, Integration | CF-AC-005 | In progress |
| [CF-REQ-212](07-asset-management.md) | Usage tracking | `assets` | Unit, Integration | CF-AC-005 | Not started |
| [CF-REQ-213](07-asset-management.md) | Asset status management | `assets` | Unit, Integration | CF-AC-005 | Not started |
| [CF-REQ-214](07-asset-management.md) | Run-scoped external inputs and working-file retention | `assets.retention`, `workflow.runner`, `workflow.production_stages`, `infrastructure.storage` | Unit, Integration | CF-AC-006 | In progress |
| [CF-REQ-215](07-asset-management.md) | Real people and generated media [Derived] | `assets`, `planning`, `evaluation` | Unit, Integration | CF-AC-006 | Not started |
| [CF-REQ-216](07-asset-management.md) | Manual asset import | `assets` | Unit, Integration | CF-AC-006 | Not started |
| [CF-REQ-217](07-asset-management.md) | ComfyUI workflow generation | `infrastructure.providers.generation` | Unit (mocked HTTP), Contract | CF-AC-006 | Not started |
| [CF-REQ-218](07-asset-management.md) | Bounded licensed media previews | `assets`, `infrastructure.providers.media` | Unit, Contract | CF-AC-029 | Not started |
| [CF-REQ-219](07-asset-management.md) | Batched visual-candidate review | `assets`, `ports`, `evaluation` | Unit, Contract, Integration | CF-AC-029 | Not started |
| [CF-REQ-220](07-asset-management.md) | Versioned reusable media judgments | `assets`, `infrastructure` | Unit, Integration | CF-AC-029 | Not started |
| [CF-REQ-250](08-visual-production.md) | Visual Plan generation | `planning` | Unit | CF-AC-005 | Not started |
| [CF-REQ-251](08-visual-production.md) | Asset requirements, including deterministic key_date conversion of calendar shots | `planning` | Unit | CF-AC-005, CF-AC-033 | Not started |
| [CF-REQ-252](08-visual-production.md) | Deterministic motion | `composition` | Unit | CF-AC-005 | Not started |
| [CF-REQ-253](08-visual-production.md) | Motion defaults | `planning` | Unit | CF-AC-005 | Not started |
| [CF-REQ-254](08-visual-production.md) | Transitions | `composition` | Unit | CF-AC-005 | Not started |
| [CF-REQ-255](08-visual-production.md) | Frame fitting | `composition`, `infrastructure`, `workflow` | Unit, Integration, Manual | CF-AC-005 | Implemented; face-safe cover refinement (2026-10-14), tagged render regressions and isolated Putellas/Yamal/Hayes comparisons verified; unchanged banner, bounded face size and source/version-bound framing; unavailable/ambiguous detection keeps standard fitting with warning |
| [CF-REQ-256](08-visual-production.md) | Timing reconciliation | `production` | Unit | CF-AC-005 | Implemented (`test_audio_captions.py`, `test_footage_continuation.py`, `test_production_block.py`) |
| [CF-REQ-257](08-visual-production.md) | Plan gate | `composition` | Unit | CF-AC-005 | Not started |
| [CF-REQ-258](08-visual-production.md) | Beat-aware Shot Intent | `planning`, `production` | Unit, Integration | CF-AC-027 | Not started |
| [CF-REQ-259](08-visual-production.md) | Grounded Editorial Overlays | `planning`, `composition` | Unit, Integration | CF-AC-027 | In progress; deterministic uppercase top-header rendering (owner revision 2026-10-14) covered by case-equivalent PNG regressions; secondary/context casing preserved |
| [CF-REQ-260](08-visual-production.md) | Verified identity and Shot Anchors | `assets`, `evaluation`, `composition` | Unit, Review | CF-AC-027 | In progress |
| [CF-REQ-261](08-visual-production.md) | Overlay layout and readable animation | `composition`, `evaluation` | Unit, Integration, Manual | CF-AC-027 | In progress |
| [CF-REQ-262](08-visual-production.md) | Purposeful deterministic motion and transitions | `planning`, `composition` | Unit, Integration | CF-AC-028 | Not started |
| [CF-REQ-263](08-visual-production.md) | Typed, grounded graphics drafts (statistic, comparison, timeline, key_date, function_plot, relationship_diagram) | `planning` | Unit, Integration | CF-AC-033 | In progress; tagged primary/fallback grounding rejection tests pass, field-specific rewrite feedback verified with fakes |
| [CF-REQ-264](08-visual-production.md) | Explicit graphics renderer routing | `assets`, `infrastructure.providers.generation` | Unit, Integration | CF-AC-033 | Not started |
| [CF-REQ-265](08-visual-production.md) | Safe local graphics render lifecycle with duplicate-shot rejection and bounded targeted replanning | `assets`, `infrastructure`, `workflow`, `api`, `frontend` | Unit, Integration, E2E | CF-AC-033 | In progress; duplicate handling verified with fakes, live rerender unverified |
| [CF-REQ-266](08-visual-production.md) | Per-Run Wan limit and grounded graphics/refined-search alternatives | `planning`, `assets`, `workflow`, `infrastructure`, `frontend` | Unit, Integration | CF-AC-034 | Implemented; fakes/SQLite/UI verified, live providers/PostgreSQL concurrency unverified |
| [CF-REQ-267](08-visual-production.md) | Native Wan reference recipe and isolated manual test | `planning`, `workflow`, `infrastructure`, `cli` | Unit, Integration, Manual | CF-AC-035 | Implemented; tagged tests, dry-run and production portrait import with mocked inference/real encoding verified; owner accepted live landscape reference at 25 steps (2026-10-08); live portrait quality unverified |
| [CF-REQ-268](08-visual-production.md) | Mentioned public figures shown on screen | `planning`, `assets`, `infrastructure`, `workflow` | Unit, Integration | CF-AC-036 | Implemented; tagged fake-provider tests plus live Wikidata portraits (Donald Trump, Karen Bass) attached to mention segments in hosted Run 95b4b7b4 |
| [CF-REQ-269](08-visual-production.md) | Persistent Claim-grounded buzz line (shown in the top context panel) | `planning`, `workflow` | Unit, Integration | CF-AC-036 | Implemented; banner superseded by top-panel display per owner request; buzz-line repair added; tagged tests, live verification pending |
| [CF-REQ-300](09-audio-and-tts.md) | Narration synthesis | `production`, `infrastructure.providers.tts` | Unit, Contract | CF-AC-007 | Not started |
| [CF-REQ-301](09-audio-and-tts.md) | Narration as Asset | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-302](09-audio-and-tts.md) | Narration cache | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-303](09-audio-and-tts.md) | Narration validation | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-304](09-audio-and-tts.md) | Narration duration gate | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-305](09-audio-and-tts.md) | TTS provider independence | `production`, `infrastructure.providers.tts` | Unit, Contract | CF-AC-007 | Not started |
| [CF-REQ-310](09-audio-and-tts.md) | Narration transcription with explicit-device selection and bounded automatic CPU fallback | `production`, `infrastructure.providers.transcription` | Unit, Contract | CF-AC-007 | In progress; device/error tests and cached-model CPU transcription verified, full decoder acceptance pending |
| [CF-REQ-311](09-audio-and-tts.md) | Alignment to script | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-312](09-audio-and-tts.md) | Caption cue layout | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-313](09-audio-and-tts.md) | Caption safe area | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-314](09-audio-and-tts.md) | Caption rendering | `production` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-320](09-audio-and-tts.md) | Royalty-free music selection | `assets` (music selection) | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-321](09-audio-and-tts.md) | Music mixing and ducking | `composition` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-322](09-audio-and-tts.md) | Local music library and manifest | `assets`, `cli`, `api` | Unit, Integration | CF-AC-007 | Not started |
| [CF-REQ-323](09-audio-and-tts.md) | Licensed sound-effect library | `assets`, `api`, `cli` | Unit, Integration | CF-AC-028 | In progress |
| [CF-REQ-324](09-audio-and-tts.md) | Timed Audio Cues and restrained sound design | `planning`, `production` | Unit, Integration | CF-AC-028 | In progress |
| [CF-REQ-325](09-audio-and-tts.md) | Intelligible final audio mix | `composition`, `evaluation` | Unit, Integration, Manual | CF-AC-028 | In progress |
| [CF-REQ-350](10-composition.md) | Composition specification | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-351](10-composition.md) | Encoding parameters | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-352](10-composition.md) | Output format | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-353](10-composition.md) | Safe FFmpeg execution | `composition`, `infrastructure.media` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-354](10-composition.md) | Clip timing | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-355](10-composition.md) | Segment rendering and transitions | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-356](10-composition.md) | Loudness | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-357](10-composition.md) | Reproducibility | `composition` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-358](10-composition.md) | Atomic output | `composition`, `infrastructure.media` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-359](10-composition.md) | Composition failures | `composition`, `infrastructure.media` | Unit, Integration | CF-AC-012 | Not started |
| [CF-REQ-360](10-composition.md) | Layered composition with profile-scoped wordmark and frozen ending preserved through continuation | `composition`, `production`, `workflow`, `infrastructure` | Unit, Integration | CF-AC-028, CF-AC-030 | In progress; continuation isolation and deleted-profile snapshots unit-tested |
| [CF-REQ-361](10-composition.md) | Saved-package preview and targeted rerender | `composition`, `assets`, `api`, `cli` | Unit, Integration, E2E | CF-AC-030 | In progress |
| [CF-REQ-362](10-composition.md) | Platform-safe presentation variants | `composition`, `publishing` | Unit, Integration | CF-AC-027 | Not started |
| [CF-REQ-400](11-evaluation-and-retry.md) | Evaluation result structure | `evaluation` | Unit, Integration, E2E | CF-AC-008 | In progress; tagged tests verify actionable unsupported-graphics field feedback without changing blocking issues |
| [CF-REQ-401](11-evaluation-and-retry.md) | Duration validation | `evaluation` | Unit, Integration, E2E | CF-AC-012 | Not started |
| [CF-REQ-402](11-evaluation-and-retry.md) | Technical media validation | `evaluation` | Unit, Integration, E2E | CF-AC-012 | Not started |
| [CF-REQ-403](11-evaluation-and-retry.md) | Asset and metadata validation | `evaluation` | Unit, Integration, E2E | CF-AC-012 | Not started |
| [CF-REQ-404](11-evaluation-and-retry.md) | Narration and timing validation | `evaluation` | Unit, Integration, E2E | CF-AC-012 | Not started |
| [CF-REQ-405](11-evaluation-and-retry.md) | Semantic evaluation | `evaluation` | Unit, Integration, E2E | CF-AC-008 | Implemented (opaque-rejection fallback unit-tested; live pending) |
| [CF-REQ-406](11-evaluation-and-retry.md) | Factual grounding evaluation | `evaluation` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-407](11-evaluation-and-retry.md) | Deterministic issue routing | `evaluation` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-408](11-evaluation-and-retry.md) | Scores are not the decision | `evaluation` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-409](11-evaluation-and-retry.md) | Evaluation persistence | `evaluation` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-410](11-evaluation-and-retry.md) | Targeted revision | `evaluation`, `workflow` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-411](11-evaluation-and-retry.md) | Bounded revision retries | `evaluation`, `workflow` | Unit, Integration, E2E | CF-AC-009 | Not started |
| [CF-REQ-412](11-evaluation-and-retry.md) | Artefact reuse on retry | `evaluation`, `workflow` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-413](11-evaluation-and-retry.md) | Failed results are never published | `evaluation`, `publishing` | Unit, Integration, E2E | CF-AC-009 | Not started |
| [CF-REQ-414](11-evaluation-and-retry.md) | Call retries are separate from revision retries | `evaluation`, `infrastructure.providers.resilience` | Unit, Integration, E2E | CF-AC-008 | Not started |
| [CF-REQ-415](11-evaluation-and-retry.md) | Visual frame sampling | `evaluation`, `infrastructure.media` | Unit, Integration | CF-AC-008 | Not started |
| [CF-REQ-416](11-evaluation-and-retry.md) | Complete bounded output review | `evaluation`, `composition` | Unit, Integration, Manual | CF-AC-031 | Not started |
| [CF-REQ-417](11-evaluation-and-retry.md) | Version-bound Quality Review | `evaluation`, `publishing` | Unit, Integration, E2E | CF-AC-031 | In progress |
| [CF-REQ-418](11-evaluation-and-retry.md) | Reference-set quality benchmark | `evaluation`, `publishing` | Integration, Review, Manual | CF-AC-031 | Not started |
| [CF-REQ-450](12-publishing.md) | Publish only approved Clips | `publishing` | Unit, Integration | CF-AC-009 | Implemented |
| [CF-REQ-451](12-publishing.md) | Platform-neutral PublicationRequest | `publishing`, `infrastructure.providers.publishing` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-452](12-publishing.md) | Publishing mode [Derived] | `publishing` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-453](12-publishing.md) | Synthetic media disclosure | `publishing`, `infrastructure.providers.publishing` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-454](12-publishing.md) | Independent platform publications | `publishing` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-455](12-publishing.md) | Idempotent publication | `publishing` | Unit, Integration | CF-AC-010 | Not started |
| [CF-REQ-456](12-publishing.md) | Publisher failures | `publishing`, `infrastructure.providers.publishing` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-457](12-publishing.md) | Publisher configuration checks before approval; concise Not Configured UI | `publishing`, `infrastructure.providers.publishing`, `frontend` | Unit, Integration, Vitest | CF-AC-010 | Implemented |
| [CF-REQ-458](12-publishing.md) | Metric collection scheduling | `publishing`, `analytics` | Unit, Integration | CF-AC-011 | Implemented |
| [CF-REQ-459](12-publishing.md) | Optional approval gate | `publishing`, `api` | Unit, Integration, E2E | CF-AC-010 | Implemented |
| [CF-REQ-460](12-publishing.md) | Auto-publish after timeout | `publishing`, `workflow.scheduler` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-461](12-publishing.md) | Signed public media URL for URL-pull platforms, incl. static share delivery | `publishing`, `api`, `infrastructure.providers.publishers` | Unit, Integration | CF-AC-010 | Implemented |
| [CF-REQ-462](12-publishing.md) | Manual publication retry | `publishing`, `api`, `infrastructure.db`, `frontend` | Unit, Component | CF-AC-010 | Implemented |
| [CF-REQ-500](13-analytics.md) | Metric collection | `analytics` | Unit, Integration | CF-AC-011 | Implemented |
| [CF-REQ-501](13-analytics.md) | Snapshot schedule | `analytics`, `workflow.scheduler` | Unit, Integration | CF-AC-011 | Not started |
| [CF-REQ-502](13-analytics.md) | Missing metrics are null | `analytics` | Unit, Integration | CF-AC-011 | Implemented |
| [CF-REQ-503](13-analytics.md) | Late and failed snapshots | `analytics`, `workflow.scheduler` | Unit, Integration | CF-AC-011 | Implemented |
| [CF-REQ-504](13-analytics.md) | Estimated revenue | `analytics` | Unit, Integration | CF-AC-011 | Implemented |
| [CF-REQ-505](13-analytics.md) | Analytics queries | `analytics` | Unit, Integration | CF-AC-011 | Not started |
| [CF-REQ-506](13-analytics.md) | Snapshot immutability | `analytics` | Unit, Integration | CF-AC-011 | Not started |
| [CF-REQ-507](13-analytics.md) | Capability-aware engagement metrics | `analytics`, `publishing`, `frontend` | Unit, Contract, Vitest | CF-AC-032 | Not started |
| [CF-REQ-508](13-analytics.md) | Versioned creative comparisons | `analytics`, `frontend` | Unit, Integration | CF-AC-032 | Not started |
| [CF-REQ-550](14-content-profiles.md) | Named profiles, multiple activation and scoped accounts | `domain`, `api`, `infrastructure.db`, `publishing`, `analytics` | Unit, Integration | CF-AC-014 | Implemented |
| [CF-REQ-551](14-content-profiles.md) | Profile validation | `domain`, `api` | Unit, Integration | CF-AC-014 | Implemented |
| [CF-REQ-552](14-content-profiles.md) | Configurable duration policy | `domain`, `planning`, `production`, `evaluation` | Unit, Review | CF-AC-014 | Not started |
| [CF-REQ-553](14-content-profiles.md) | Supported categories | `domain`, `api` | Unit, Integration | CF-AC-014 | Not started |
| [CF-REQ-554](14-content-profiles.md) | Language independence | `domain`, `planning`, `production` | Unit, Integration | CF-AC-014 | Not started |
| [CF-REQ-555](14-content-profiles.md) | Profile snapshot per Run | `domain`, `workflow` | Unit, Integration | CF-AC-014 | Not started |
| [CF-REQ-556](14-content-profiles.md) | Versioned news style and quality policy | `domain`, `planning`, `api` | Unit, Integration | CF-AC-027 | Not started |
| [CF-REQ-600](15-ui-and-dashboard.md) | Visual design | `frontend` | Vitest, Playwright | CF-AC-013 | Not started |
| [CF-REQ-601](15-ui-and-dashboard.md) | Overview with full-width Current Run and mood-bearing agent Personas | `frontend` | Vitest, Playwright | CF-AC-013 | In progress |
| [CF-REQ-602](15-ui-and-dashboard.md) | Live Run progress (Execution bar and stage bubble) | `frontend` | Vitest, Playwright | CF-AC-013, CF-AC-017 | In progress |
| [CF-REQ-603](15-ui-and-dashboard.md) | Analytics page | `frontend` | Vitest, Playwright | CF-AC-011 | Not started |
| [CF-REQ-604](15-ui-and-dashboard.md) | Run detail (elapsed time, Visual counts, LLM models, generation milestones, newest-first events without watchdog noise) | `frontend`, `api` | Vitest, Playwright | CF-AC-017 | In progress |
| [CF-REQ-605](15-ui-and-dashboard.md) | Asset library with inline media previews, storage locations and 20-per-page pagination | `frontend`, `api` | Vitest, Playwright | CF-AC-005 | In progress |
| [CF-REQ-606](15-ui-and-dashboard.md) | Initially collapsed Settings groups with retained drafts; no provider readiness or credential-status summaries | `frontend` | Vitest, Playwright | CF-AC-014 | In progress |
| [CF-REQ-607](15-ui-and-dashboard.md) | Content Profile editor with independent Research sources/policies and named-profile management | `frontend` | Vitest, Playwright | CF-AC-014 | In progress |
| [CF-REQ-608](15-ui-and-dashboard.md) | Run Now with explicit profile selection | `frontend`, `api` | Unit, Vitest, Playwright | CF-AC-013 | In progress |
| [CF-REQ-609](15-ui-and-dashboard.md) | Manual URL input | `frontend` | Vitest, Playwright | CF-AC-015 | Not started |
| [CF-REQ-610](15-ui-and-dashboard.md) | Clips page (previews with errors, publication-aware approval actions, corner delete icon, All/Published/Failed tabs) and filtered paginated API | `frontend`, `api`, `infrastructure.db` | Unit, Vitest, Playwright | CF-AC-013 | In progress |
| [CF-REQ-611](15-ui-and-dashboard.md) | Safe rendering of external text | `frontend` | Vitest, Playwright | CF-AC-018 | Not started |
| [CF-REQ-612](15-ui-and-dashboard.md) | Cost display (Overview budget uses two decimal places) | `frontend` | Vitest, Playwright | CF-AC-023 | In progress |
| [CF-REQ-613](15-ui-and-dashboard.md) | Approval of pending Clips, one-per-row Review Board and paginated queue API | `frontend`, `api` | Unit, Vitest, Playwright | CF-AC-010 | In progress |
| [CF-REQ-614](15-ui-and-dashboard.md) | Storyboard and version-bound quality review UI | `frontend`, `api` | Vitest, Playwright, Integration | CF-AC-030–031 | In progress |
| [CF-REQ-650](16-scheduling-and-runs.md) | Run triggers | `workflow` | Unit, Integration, E2E | CF-AC-016 | Not started |
| [CF-REQ-651](16-scheduling-and-runs.md) | Independent local daily schedule rules | `workflow.scheduler`, `api`, `frontend` | Unit, Integration, E2E | CF-AC-016 | Implemented |
| [CF-REQ-652](16-scheduling-and-runs.md) | Single active Run | `workflow`, `infrastructure.db` | Unit, Integration, E2E | CF-AC-016 | Not started |
| [CF-REQ-653](16-scheduling-and-runs.md) | Run snapshot | `workflow` | Unit, Integration, E2E | CF-AC-016 | Not started |
| [CF-REQ-654](16-scheduling-and-runs.md) | Stage execution | `workflow` | Unit, Integration, E2E | CF-AC-016 | Not started |
| [CF-REQ-655](16-scheduling-and-runs.md) | Run failure | `workflow` | Unit, Integration, E2E | CF-AC-009, CF-AC-033 | Not started |
| [CF-REQ-656](16-scheduling-and-runs.md) | Stage timeout with internal generation watchdog renewal | `workflow`, `infrastructure.graphics` | Unit, Integration, E2E | CF-AC-016, CF-AC-033 | In progress |
| [CF-REQ-657](16-scheduling-and-runs.md) | Resumption, owner continuation resetting revision allowance with retained history, and explicit Stop | `workflow`, `api`, `frontend` | Unit, Integration, E2E | CF-AC-016 | In progress |
| [CF-REQ-658](16-scheduling-and-runs.md) | Lean workflow state | `workflow` | Unit | CF-AC-016 | Not started |
| [CF-REQ-659](16-scheduling-and-runs.md) | Run APIs | `api`, `workflow` | Unit, Integration, E2E | CF-AC-016 | Not started |
| [CF-REQ-660](16-scheduling-and-runs.md) | Scheduler can be disabled | `workflow.scheduler` | Unit, Integration | CF-AC-016 | Not started |
| [CF-REQ-661](16-scheduling-and-runs.md) | Cost recording | `infrastructure.providers.resilience`, `domain` | Unit, Integration | CF-AC-023 | Not started |
| [CF-REQ-662](16-scheduling-and-runs.md) | Per-Clip cost limit | `domain`, `infrastructure.providers.resilience` | Unit, Integration | CF-AC-023 | Not started |
| [CF-REQ-663](16-scheduling-and-runs.md) | Monthly cost limit | `domain`, `workflow.scheduler`, `api` | Unit, Integration | CF-AC-023 | Not started |
| [CF-REQ-664](16-scheduling-and-runs.md) | Degrade before failing | `assets`, `workflow` | Unit, Integration, E2E | CF-AC-023 | Not started |
| [CF-REQ-665](16-scheduling-and-runs.md) | Cost visibility API | `api` | Integration | CF-AC-023 | Not started |
| [CF-REQ-666](16-scheduling-and-runs.md) | LLM requests per Clip | `workflow`, LLM governance wrapper | Unit, Integration, E2E | CF-AC-024 | Not started |
| [CF-REQ-667](16-scheduling-and-runs.md) | Requests-per-minute limiter | LLM governance wrapper | Unit, Integration | CF-AC-024 | Implemented; tagged fake-clock/accounting tests and isolated live Dragonfly Lua tests verify rolling account ceiling, adaptive endpoint/model pacing, restart state and fail-closed behaviour; no live LLM calls |
| [CF-REQ-668](16-scheduling-and-runs.md) | Daily request budget | LLM governance wrapper, `workflow`, `api` | Unit, Integration | CF-AC-024 | Not started |
| [CF-REQ-669](16-scheduling-and-runs.md) | Persistent usage accounting | LLM governance wrapper, `infrastructure.db`, `api` | Integration | CF-AC-024 | Not started |
| [CF-REQ-670](16-scheduling-and-runs.md) | Bounded, non-blind LLM retries | LLM governance wrapper | Unit, isolated live probes | CF-AC-024 | Implemented; tagged tests verify cooldowns, cancellation, governance, permanent-error rejection, AtlasCloud's single opaque retry and the free router's configured retry bound; live Runs confirm unpredictable upstream failures remain possible |
| [CF-REQ-671](16-scheduling-and-runs.md) | Circuit breaker and exhaustion handling | LLM governance wrapper, `api` | Unit, Integration | CF-AC-024 | Not started |
| [CF-REQ-700](17-manual-input.md) | Manual URL submission | `api`, `infrastructure.http` | Unit, Integration, E2E | CF-AC-015 | Not started |
| [CF-REQ-701](17-manual-input.md) | URL ingestion | `research` (`ingest_url`) | Unit, Integration, E2E | CF-AC-015 | Implemented |
| [CF-REQ-702](17-manual-input.md) | Same pipeline after ingestion | `workflow` | Unit, Integration, E2E, Review | CF-AC-015 | Implemented |
| [CF-REQ-703](17-manual-input.md) | Profile rules for user-selected Stories | `research` | Unit, Integration | CF-AC-015 | Implemented |
| [CF-REQ-750](18-configuration.md) | Validated configuration at startup | `infrastructure.settings`, `bootstrap` | Unit, Integration | CF-AC-014, CF-AC-033 | Not started |
| [CF-REQ-751](18-configuration.md) | Provider selection by configuration | `bootstrap`, `assets` | Unit, Integration | CF-AC-020, CF-AC-033 | Not started |
| [CF-REQ-752](18-configuration.md) | Editable application settings | `infrastructure.settings`, `api` | Unit, Integration | CF-AC-014 | Implemented |
| [CF-REQ-753](18-configuration.md) | Credential status without disclosure | `infrastructure.settings`, `api` | Unit, Integration | CF-AC-014 | Implemented |
| [CF-REQ-754](18-configuration.md) | Seeded defaults | `infrastructure.db` | Integration | CF-AC-014 | Not started |
| [CF-REQ-755](18-configuration.md) | Local dependency setup [Derived] | `cli`, Docker Compose | Integration, Manual | CF-AC-025 | Not started |
| [CF-REQ-756](18-configuration.md) | Operational diagnostics with optional public-storage warnings [Derived] | `cli`, `infrastructure` | Unit, Integration | CF-AC-025, CF-AC-033 | In progress |
| [CF-REQ-757](18-configuration.md) | Root native launch with Wan/Manim; optional public storage [Derived] | `cli`, `bootstrap` | Unit, Integration, Manual | CF-AC-025 | In progress |
| [CF-REQ-758](18-configuration.md) | Structured LLM output validation with independent role transports | `infrastructure.providers`, `workflow.llm_activity` | Unit, mocked HTTP; synthetic live Dots evaluations validated, actual payload intermittently rejected or invalid JSON | CF-AC-003, CF-AC-024 | Implemented; non-strict whole-response JSON fences validated in tests, not verified on a live fenced answer |
| [CF-REQ-759](18-configuration.md) | Environment values, including output modes and Wan FPS/steps, editable for new/continued Runs | `api`, `infrastructure.settings_validation`, `workflow.runner` | Unit, UI | CF-AC-024 | Implemented |
| [CF-REQ-760](18-configuration.md) | Local graphics renderer runtime settings | `api`, `infrastructure.settings_validation`, `workflow.runner` | Unit, Integration | CF-AC-033 | Not started |
| [CF-REQ-850](20-observability.md) | Persisted Run Events | `workflow`, `infrastructure.db` | Unit, Integration | CF-AC-017 | Not started |
| [CF-REQ-851](20-observability.md) | Structured logs | `infrastructure.logging` | Unit, Integration | CF-AC-017 | Not started |
| [CF-REQ-852](20-observability.md) | Live event stream | `api` (SSE) | Unit, Integration | CF-AC-013 | Not started |
| [CF-REQ-853](20-observability.md) | Provider call telemetry | `infrastructure.providers`, `workflow` | Unit, Integration | CF-AC-017 | Not started |
| [CF-REQ-854](20-observability.md) | Stage timing | `workflow`, `api` | Unit, Integration | CF-AC-017 | Not started |
| [CF-REQ-855](20-observability.md) | LLM exchange audit | `infrastructure.providers`, `infrastructure.storage` | Unit, Integration | CF-AC-017 | Not started |
| [CF-REQ-856](20-observability.md) | Health endpoint | `api`, `infrastructure` | Unit, Integration | CF-AC-017 | Not started |

## Non-functional requirements

| ID | Title | Component | Verification | Acceptance | Status |
| --- | --- | --- | --- | --- | --- |
| [CF-NFR-001](03-non-functional-requirements.md) | Single-host system | architecture tests, deployment | Unit (architecture), Review | CF-AC-020, CF-AC-033 | Not started |
| [CF-NFR-002](03-non-functional-requirements.md) | Prohibited technology | architecture tests | Unit (architecture) | CF-AC-020 | Not started |
| [CF-NFR-003](03-non-functional-requirements.md) | Technology baseline | whole repository | Review | CF-AC-020, CF-AC-033 | Not started |
| [CF-NFR-010](03-non-functional-requirements.md) | Bounded external calls | `infrastructure.providers.resilience` | Unit | CF-AC-021 | Not started |
| [CF-NFR-011](03-non-functional-requirements.md) | Bounded behaviour | `research`, `evaluation`, `workflow`, `infrastructure` | Unit | CF-AC-021 | Not started |
| [CF-NFR-012](03-non-functional-requirements.md) | Non-blocking server | `workflow`, `infrastructure.media`, `infrastructure.graphics` | Integration | CF-AC-021, CF-AC-033 | Not started |
| [CF-NFR-013](03-non-functional-requirements.md) | Data integrity | `infrastructure.db` | Integration | CF-AC-021 | Not started |
| [CF-NFR-020](03-non-functional-requirements.md) | Provider isolation | architecture tests | Unit (architecture) | CF-AC-020 | Not started |
| [CF-NFR-021](03-non-functional-requirements.md) | Layer dependencies | architecture tests | Unit (architecture) | CF-AC-020 | Not started |
| [CF-NFR-022](03-non-functional-requirements.md) | Static typing | whole repository (Pyright, tsc) | CI | CF-AC-020 | Not started |
| [CF-NFR-023](03-non-functional-requirements.md) | Deterministic components | `domain`, `research`, `production`, `composition`, `evaluation` | Unit | CF-AC-020 | Not started |
| [CF-NFR-024](03-non-functional-requirements.md) | Run reproducibility record | `workflow` | Integration | CF-AC-020 | Not started |
| [CF-NFR-030](03-non-functional-requirements.md) | Benchmark methodology | `cli` (benchmark), whole system | Integration, Measurement | CF-AC-021 | Not started |
| [CF-NFR-031](03-non-functional-requirements.md) | Fake-provider end-to-end duration is measured | CI | CI | CF-AC-021 | Not started |
| [CF-NFR-032](03-non-functional-requirements.md) | API responsiveness is measured | `cli` (benchmark) | Measurement | CF-AC-021 | Not started |
| [CF-NFR-033](03-non-functional-requirements.md) | Clip size is measured | `cli` (benchmark) | Measurement | CF-AC-021 | Not started |
| [CF-NFR-040](03-non-functional-requirements.md) | Accessibility and browsers | `frontend` | Playwright | CF-AC-021 | Not started |
| [CF-NFR-041](03-non-functional-requirements.md) | UI language [Derived] | `frontend` | Playwright | CF-AC-021 | Not started |
| [CF-NFR-050](03-non-functional-requirements.md) | Supported environments | CI | CI | CF-AC-021 | Not started |
| [CF-NFR-051](03-non-functional-requirements.md) | Backup and restore | deployment | Manual | CF-AC-022 | Not started |
| [CF-NFR-052](03-non-functional-requirements.md) | Cost visibility | `workflow`, `infrastructure.providers` | Integration | CF-AC-021 | Not started |
| [CF-NFR-100](19-security.md) | Trust model | whole system | Review | CF-AC-018 | Not started |
| [CF-NFR-101](19-security.md) | Network exposure and API token | `api`, `infrastructure.settings` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-102](19-security.md) | Safe process execution | `infrastructure.media`, `infrastructure.graphics` | Unit, Integration | CF-AC-018, CF-AC-033 | Not started |
| [CF-NFR-103](19-security.md) | SSRF-safe outbound HTTP | `infrastructure.http` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-104](19-security.md) | Size limits | `infrastructure.http`, `api` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-105](19-security.md) | Storage path safety | `infrastructure.storage` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-106](19-security.md) | Secret handling | `infrastructure.settings`, `infrastructure.logging` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-107](19-security.md) | Sanitisation of external text | `research`, `production`, `frontend` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-108](19-security.md) | Prompt-injection containment | `research`, `planning`, `evaluation` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-109](19-security.md) | Database access | `infrastructure.db` | CI (Ruff), Review | CF-AC-018 | Not started |
| [CF-NFR-110](19-security.md) | API input validation | `api` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-111](19-security.md) | Provider failure isolation | `infrastructure.providers` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-112](19-security.md) | Dependency integrity | CI | CI | CF-AC-018, CF-AC-033 | Not started |
| [CF-NFR-113](19-security.md) | Same-origin browser access | `api` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-114](19-security.md) | Signed public media URLs | `api`, `publishing` | Unit, Integration | CF-AC-018 | Not started |
| [CF-NFR-150](21-testing.md) | Mandatory tests for behaviour | whole repository | CI (`check_traceability.py`) | CF-AC-019 | Not started |
| [CF-NFR-151](21-testing.md) | Normal CI needs no external services | whole repository | CI | CF-AC-019 | Not started |
| [CF-NFR-152](21-testing.md) | Coverage policy | whole repository | CI | CF-AC-019 | Not started |
| [CF-NFR-153](21-testing.md) | Quality gate commands | whole repository | CI | CF-AC-019 | Not started |
| [CF-NFR-154](21-testing.md) | Test isolation and determinism | whole repository | CI | CF-AC-019 | Not started |
| [CF-NFR-155](21-testing.md) | Media fixtures | `backend/tests/fixtures` | Review | CF-AC-019 | Not started |
| [CF-NFR-156](21-testing.md) | Architecture tests | architecture tests | Unit (architecture) | CF-AC-019 | Not started |
| [CF-NFR-157](21-testing.md) | Regression tests for defects | whole repository | Review | CF-AC-019 | Not started |

## Acceptance scenario → E2E journey

| Acceptance | E2E journey ([21-testing.md](21-testing.md#critical-e2e-journeys)) |
| --- | --- |
| CF-AC-001 … CF-AC-004, CF-AC-006, CF-AC-007, CF-AC-010, CF-AC-012 | E2E-1 |
| CF-AC-005 | E2E-1, E2E-8 |
| CF-AC-008 | E2E-2 |
| CF-AC-009, CF-AC-017 | E2E-3 |
| CF-AC-011 | E2E-9 |
| CF-AC-013 | E2E-6 |
| CF-AC-014 | E2E-7 |
| CF-AC-015 | E2E-4 |
| CF-AC-016 | E2E-5 |
| CF-AC-018 … CF-AC-022 | Non-E2E (unit/integration/CI/review/measurement) |
| CF-AC-023 | E2E-10 |
| CF-AC-024 | E2E-1 (request count), failure/recovery tests |
| CF-AC-025 | Non-E2E (integration/manual) |
| CF-AC-033 | E2E-11 (real local renderers; not a live external-provider test) |
