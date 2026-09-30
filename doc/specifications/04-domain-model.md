# 04 — Domain Model

Canonical definition of ClipFactory's entities, value objects, invariants and
state machines. Architecture view: [architecture/domain-architecture.md](architecture/domain-architecture.md).
Diagram: [architecture/diagrams/domain-model.puml](architecture/diagrams/domain-model.puml).
Decision: [ADR-014](decisions/ADR-014-source-grounded-story-claim-model.md).

Types are logical. `id` fields are UUIDs. Timestamps are timezone-aware UTC.
Durations are seconds as decimals. Fields marked `?` are nullable. Field names
here are the canonical names for code, database columns and API schemas
unless an API document says otherwise.

## Modelling rules

- The domain layer contains no I/O, no framework imports (FastAPI,
  SQLAlchemy, LangGraph, httpx) and no provider-specific names.
- Entities are created only when they have identity and lifecycle. Everything
  else is a value object embedded in its owner.
- "Provider" is **not** a persisted entity. Providers are configured adapters;
  the domain records only a provider *name* string in provenance and events
  (see [Provider](#provider-not-an-entity)).
- Cross-aggregate references are by ID.

## Aggregates overview

| Aggregate root | Owns | Lifecycle |
| --- | --- | --- |
| `ContentProfile` | `DurationPolicy`, `OutputSpec`, `VoiceSpec`, `Schedule`, `ResearchPolicy`, `MusicPolicy` | Edited by the user |
| `Run` | `RunEvent`s, attempts | One workflow execution |
| `Source` | — | Retrieved once, shared by Stories (dedup by canonical URL) |
| `Story` | `StorySource` links, `Claim`s | Candidate → selected / rejected |
| `StoryPackage` | `Script`, `VisualPlan`, `SocialMetadata` versions | One per selected Story per Run |
| `Asset` | `Provenance` | Library item, reused across Runs |
| `Clip` | `NarrationTrack`, `CaptionTrack`, `AssetUsage`s, `Evaluation`s | One per Attempt |
| `Publication` | — | One per (approved Clip, platform) |
| `MetricSnapshot` | `EstimatedRevenue` | Collected on schedule |

## ContentProfile

Canonical requirements: [14-content-profiles.md](14-content-profiles.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| name | str | Unique |
| is_active | bool | Exactly one active profile in v1.0 |
| language | str | BCP 47 tag, e.g. `en` |
| category | enum `ContentCategory` | `general`, `technology`, `ai`, `finance`, `business`, `science`, `gaming`, `sports`, `entertainment`, `politics` |
| topics | list[str] | Topics to prefer |
| excluded_topics | list[str] | Topics to reject |
| geography | list[str] | Coverage regions; `["global"]` for global |
| markets | list[str] | Audience markets (ISO 3166-1 alpha-2 codes or `global`) |
| voice | `VoiceSpec` | |
| duration | `DurationPolicy` | |
| output | `OutputSpec` | |
| visual_style | `VisualStyle` | |
| platforms | list[enum `Platform`] | `youtube`, `instagram`, `tiktok`, `facebook`; may be empty |
| schedule | `Schedule` | |
| research | `ResearchPolicy` | |
| music | `MusicPolicy` | |
| generation | `GenerationPolicy` | Ordered generation providers |
| updated_at | datetime | |

Value objects:

- **DurationPolicy** `{min_seconds, target_seconds, max_seconds}` —
  invariant `0 < min ≤ target ≤ max`. Bounds are inclusive.
- **OutputSpec** `{width, height, fps}` — defaults 720, 1280, 30; invariant
  `width/height == 9/16` for v1.0 (the ratio itself is a constant of v1.0,
  not user-editable).
- **VoiceSpec** `{provider_voice_id: str, speaking_rate: float, words_per_minute: int}`
  — `provider_voice_id` is an opaque string interpreted only by the configured
  `TTSProvider`; `words_per_minute` is the planning estimate.
- **VisualStyle** `{description: str, caption_style: str, motion_intensity: enum(low|medium|high), allow_generated_media: bool}`.
- **Schedule** `{enabled: bool, local_time: "HH:MM", timezone: IANA name}`.
- **ResearchPolicy** `{max_candidate_articles, min_sources, preferred_independent_sources, max_article_age_hours, allowed_publishers?, blocked_publishers}`.
- **MusicPolicy** `{enabled: bool, mood_tags: list[str], energy: enum(low|medium|high)?, ducked_level_db: float, unducked_level_db: float}` — levels relative to normalised narration (CF-REQ-321).
- **GenerationPolicy** `{image_providers: list[str], video_providers: list[str]}` —
  provider names in order of preference; names must be among the providers
  enabled in the environment ([18-configuration.md](18-configuration.md)).

## Run

Canonical requirements: [16-scheduling-and-runs.md](16-scheduling-and-runs.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| trigger | enum `RunTrigger` | `scheduled`, `run_now`, `manual_url` |
| manual_url | str? | Required iff `trigger = manual_url` |
| profile_id | UUID | |
| profile_snapshot | JSON | Immutable copy of the profile at Run start |
| status | enum `RunStatus` | see state machine |
| outcome | enum `RunOutcome`? | Set when `status = completed` |
| current_stage | enum `Stage`? | |
| attempt | int | Current Attempt number, starts at 1 |
| revision_retries_used | int | ≤ configured maximum |
| selected_story_id | UUID? | |
| story_package_id | UUID? | |
| approved_clip_id | UUID? | |
| failure_stage | enum `Stage`? | Set when `status = failed` |
| failure_code | str? | Machine-readable, e.g. `no_suitable_story` |
| failure_message | str? | Human-readable, actionable |
| cost_total | Decimal | Sum of `CostEntry.amount` for the Run, in `budget.currency` |
| created_at, started_at?, finished_at? | datetime | |

`RunStatus` state machine:

```text
queued ──► running ──► completed
              │
              ├──► failed
              │
  (process restart while running) ──► running (resumed) | failed(interrupted)
```

`RunOutcome` (only when `completed`):

| Value | Meaning |
| --- | --- |
| `published` | Approved Clip published to every enabled platform |
| `partially_published` | Approved Clip; at least one but not all publications succeeded |
| `not_published` | Approved Clip; publishing mode not `live`, no platforms enabled, all publications failed, or the owner rejected publication |
| `awaiting_approval` | Approved Clip; `publishing.approval_required` is on and the owner has not yet decided. Replaced by one of the values above when the approval is resolved (CF-REQ-459, CF-REQ-460) |

A Run that never produces an approved Clip ends `failed`.

### CostEntry

Append-only record of spend (CF-REQ-661).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| run_id | UUID | |
| clip_id | UUID? | Clip candidate the spend belongs to, if any |
| provider | str | Provider name |
| operation | str | Price-table key, e.g. `higgsfield_video` |
| quantity | Decimal | Units (tokens, characters, seconds, images) |
| amount | Decimal | In `budget.currency` |
| basis | enum `CostBasis` | `reported` (provider-reported) or `estimated` (price table) |
| created_at | datetime | |

### RunEvent

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| run_id | UUID | |
| sequence | int | Strictly increasing per Run, starting at 1 |
| type | enum `RunEventType` | Canonical list in [20-observability.md](20-observability.md#run-event-types) |
| stage | enum `Stage`? | |
| attempt | int | |
| level | enum `info`, `warning`, `error` | |
| message | str | Human-readable |
| payload | JSON | Structured, secret-free |
| created_at | datetime | |

`Stage` enum values are listed in [16-scheduling-and-runs.md](16-scheduling-and-runs.md#stages).

## Source

Canonical requirements: [05-research-and-source-grounding.md](05-research-and-source-grounding.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| url | str | As retrieved |
| canonical_url | str | Normalised; unique |
| publisher | str | Publishing outlet name/domain |
| origin_publisher | str | Equals `publisher` unless syndicated |
| title | str | |
| author | str? | |
| published_at | datetime? | |
| retrieved_at | datetime | |
| language | str? | |
| text | str | Extracted plain text (sanitised) |
| text_hash | str | SHA-256 of normalised text |
| quality_tier | enum `SourceQualityTier` | `high`, `standard`, `low`, `blocked` |
| syndication_of | UUID? | Source this is a copy of |
| news_source_provider | str | Name of the `NewsSource` that returned it, or `manual_url` |

## Story

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| run_id | UUID | Run that discovered it |
| status | enum `StoryStatus` | `candidate`, `selected`, `rejected` |
| title | str | |
| summary | str | |
| category | `ContentCategory` | |
| selection_score | float? | Deterministic weighted score (see 05) |
| score_breakdown | JSON? | Per-criterion scores |
| selection_rationale | str? | |
| rejection_reason | str? | |
| sources | list[`StorySource`] | |
| claims | list[`Claim`] | |

**StorySource** `{source_id, role: enum(candidate|evidence), is_independent: bool}`.

Derived (computed, not stored): `article_count`, `independent_source_count`
(distinct `origin_publisher` values among non-syndicated `evidence` Sources).

Invariant: a Story with `status = selected` has `independent_source_count ≥ min_sources`.

## Claim

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| story_id | UUID | |
| text | str | Single assertion |
| kind | enum `ClaimKind` | `fact`, `figure`, `quote`, `statement_attributed` |
| evidence | list[`Evidence`] | |
| support_level | enum `SupportLevel` | `corroborated`, `single_source`, `unsupported` (derived from valid evidence) |
| status | enum `ClaimStatus` | `accepted`, `rejected` |
| rejection_reason | str? | |

**Evidence** `{source_id, excerpt: str, verified: bool}` — `verified` is true
only if `excerpt` occurs in the Source text after whitespace/quote
normalisation (deterministic check).

Invariants:

- `support_level` is computed from `verified` evidence and Source independence.
- A Claim with `support_level = unsupported` cannot be `accepted`.

## StoryPackage

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| run_id | UUID | |
| story_id | UUID | |
| key_fact_claim_ids | list[UUID] | Subset of accepted Claims |
| script | `Script`? | Current version |
| visual_plan | `VisualPlan`? | Current version |
| social_metadata | `SocialMetadata`? | |
| version | int | Incremented whenever script, plan or metadata changes |
| created_at, updated_at | datetime | |

Previous versions of Script and Visual Plan are retained (audit of revisions).

### Script (value object, versioned)

`{version, language, hook_segment_index: 0, segments: list[ScriptSegment], word_count, estimated_duration_seconds, llm_model, prompt_version}`

**ScriptSegment** `{index, text, claim_ids: list[UUID], attribution: str?, estimated_duration_seconds}`.

### VisualPlan (value object, versioned)

`{version, segments: list[VisualSegment]}`

**VisualSegment**

| Field | Type | Notes |
| --- | --- | --- |
| index | int | |
| script_segment_index | int | |
| narration_text | str | |
| objective | str | What the viewer should understand/see |
| requirement | `AssetRequirement` | |
| planned_duration_seconds | float | Estimated; replaced by timing from word timestamps |
| start_seconds?, end_seconds? | float | Set after transcription |
| motion | enum `Motion` | `none`, `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, `ken_burns` |
| transition_in | enum `Transition` | `cut`, `crossfade`, `fade_black`, `slide_left`, `slide_up` |
| selected_asset_id | UUID? | |
| selection_reason | str? | `reused`, `acquired`, `generated`, `fallback_card` |

**AssetRequirement** `{media_type: enum(image|video|any), category: AssetCategory, description, subjects: list[str], tags: list[str], strategy: enum(reuse_first|acquire_only|generate_allowed)}`.

### SocialMetadata

`{title, description, hashtags: list[str], source_attributions: list[str], asset_attributions: list[str], contains_synthetic_media: bool, synthetic_voice: bool}`.

## Asset

Canonical requirements: [07-asset-management.md](07-asset-management.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| media_type | enum `MediaType` | `image`, `video`, `audio` |
| category | enum `AssetCategory` | `photo`, `broll`, `illustration`, `graphic`, `chart`, `map`, `music`, `narration`, `title_card`, `other` |
| storage_key | str | Relative key in `StorageProvider` |
| sha256 | str | Unique among active Assets |
| mime_type | str | Detected from content, not from remote headers |
| size_bytes | int | |
| width?, height? | int | Images/video |
| duration_seconds? | float | Audio/video |
| fps? | float | Video |
| description | str | |
| tags | list[str] | Lower-case, normalised |
| subjects | list[str] | Named entities/topics depicted |
| provenance | `Provenance` | Mandatory |
| music | `MusicInfo`? | Required iff `category = music` |
| quality_score | float? | 0.0–1.0 |
| reusable | bool | `false` for narration and per-Clip renders |
| status | enum `AssetStatus` | `active`, `quarantined`, `retired` |
| usage_count | int | Count of `AssetUsage` in approved Clips |
| last_used_at? | datetime | |
| created_at | datetime | |

**Provenance**

| Field | Type | Notes |
| --- | --- | --- |
| origin | enum `AssetOrigin` | `external`, `generated`, `rendered`, `imported` |
| provider | str | Provider name, e.g. `pexels`, `google_tts`, `ffmpeg_title_card`, `manual_import` |
| source_url | str? | Page URL of the original |
| download_url | str? | |
| author | str? | |
| license | str | SPDX id or provider licence name; never empty |
| license_url | str? | |
| attribution_text | str? | Required when the licence requires attribution |
| attribution_required | bool | |
| generation | `GenerationInfo`? | Required when `origin = generated` |
| acquired_at | datetime | |

**GenerationInfo** `{provider, model, prompt, negative_prompt?, parameters: JSON, seed?}`.

**MusicInfo** `{title, artist, genre, mood: list[str], energy: enum(low|medium|high), bpm?: int, loopable: bool, allowed_platforms: list[Platform] | null}` —
`allowed_platforms = null` means no platform restriction; source, source URL,
licence and attribution live in `Provenance`; duration in `Asset.duration_seconds`
(CF-REQ-322).

Invariants:

- `license` is non-empty; Assets with unknown licence are not stored as `active`.
- `origin = generated` ⇒ `generation` present.
- `attribution_required` ⇒ `attribution_text` present.

## Clip

Canonical requirements: [10-composition.md](10-composition.md), [11-evaluation-and-retry.md](11-evaluation-and-retry.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| run_id | UUID | |
| story_package_id | UUID | |
| story_package_version | int | |
| attempt | int | |
| status | enum `ClipStatus` | `rendered`, `rejected`, `approved` |
| storage_key | str | |
| sha256 | str | |
| duration_seconds | float | Measured by probe |
| width, height | int | Measured |
| fps | float | Measured |
| video_codec, audio_codec | str | Measured |
| size_bytes | int | |
| narration | `NarrationTrack` | |
| captions | `CaptionTrack` | |
| music_asset_id | UUID? | |
| asset_usages | list[`AssetUsage`] | |
| composition_spec_hash | str | Hash of the deterministic composition specification |
| created_at | datetime | |

- **NarrationTrack** `{asset_id, duration_seconds, tts_provider, voice_id, text_hash, word_timings: list[WordTiming]}`
- **WordTiming** `{word, start_seconds, end_seconds, script_segment_index}`
- **CaptionTrack** `{cues: list[CaptionCue], font, font_size_px, layout: {horizontal_margin_pct, max_text_width_pct, bottom_margin_pct}}`
- **CaptionCue** `{index, start_seconds, end_seconds, lines: list[str], box: {x, y, width, height}}`
- **AssetUsage** `{asset_id, visual_segment_index, start_seconds, end_seconds}`

`ClipStatus` transitions: `rendered → approved` (Evaluation passed) or
`rendered → rejected`. Only `approved` Clips may be published. At most one
approved Clip per Run.

## Evaluation

Canonical requirements: [11-evaluation-and-retry.md](11-evaluation-and-retry.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| clip_id | UUID? | Null for stage-gate evaluations before a Clip exists |
| run_id | UUID | |
| attempt | int | |
| layer | enum `EvaluationLayer` | `stage_gate`, `deterministic`, `semantic` |
| passed | bool | `true` iff no `blocking` issues |
| issues | list[`Issue`] | Blocking findings |
| warnings | list[`Issue`] | Non-blocking findings |
| actions | list[`Action`] | Corrective actions derived from issues |
| metrics | JSON | Measured values and scores |
| evaluator | str | `deterministic` or LLM model identifier |
| created_at | datetime | |

- **Issue** `{code, severity: blocking|warning, stage: Stage, message, evidence: JSON, refs: {claim_ids?, segment_indexes?, asset_ids?}}`
- **Action** `{type: ActionType, target_stage: Stage, instructions: str, refs}`
- `ActionType`: `gather_more_sources`, `remove_claim`, `revise_script`,
  `replan_visuals`, `reselect_asset`, `regenerate_narration`, `recompose`,
  `abort` — exactly the action types used by the routing table in
  [11-evaluation-and-retry.md](11-evaluation-and-retry.md#issue-routing-table-canonical).

## Publication

Canonical requirements: [12-publishing.md](12-publishing.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| clip_id | UUID | Must reference an `approved` Clip |
| platform | `Platform` | |
| status | enum `PublicationStatus` | `awaiting_approval`, `pending`, `publishing`, `published`, `failed`, `dry_run`, `rejected` (owner rejected) |
| mode | `PublishingMode` | `dry_run` or `live` at the time of publication |
| request | JSON | Serialised `PublicationRequest` (no secrets) |
| platform_post_id? | str | |
| platform_url? | str | |
| error_code?, error_message? | str | |
| call_retries | int | |
| approved_by? | enum `owner`, `auto_timeout` | Only when the approval gate was used |
| published_at? | datetime | |

Unique constraint: (`clip_id`, `platform`).

**PublicationRequest** (value object): `{clip_id, clip_path_key, title, description, hashtags, source_attributions, asset_attributions, language, contains_synthetic_media, synthetic_voice, scheduled_at?}`.

**PublicationResult** (value object): `{status, platform_post_id?, platform_url?, error_code?, error_message?, transient: bool}`.

## MetricSnapshot

Canonical requirements: [13-analytics.md](13-analytics.md).

| Field | Type | Notes |
| --- | --- | --- |
| id | UUID | |
| publication_id | UUID | |
| platform | `Platform` | Denormalised for queries |
| offset_label | str | `1h`, `6h`, `24h`, `48h`, `7d`, `30d`, or `manual` |
| scheduled_for | datetime | |
| captured_at | datetime | |
| views? | int | Null = not available (never fabricated as 0) |
| likes?, comments?, shares? | int | |
| watch_time_seconds? | float | Total |
| average_retention_ratio? | float | 0.0–1.0 |
| followers_delta? | int | |
| estimated_revenue? | `EstimatedRevenue` | |
| raw | JSON | Provider response excerpt for audit (no secrets) |

**EstimatedRevenue** `{amount: Decimal, currency: ISO 4217, basis: enum(platform_reported_estimate|rpm_estimate), rpm_used?: Decimal}`.
Unique constraint: (`publication_id`, `offset_label`).

## Provider (not an entity)

A Provider is an adapter implementing a port defined in the application
layer ([architecture/provider-architecture.md](architecture/provider-architecture.md)).
Provider selection and non-secret settings live in configuration
([18-configuration.md](18-configuration.md)); credentials live in environment
variables ([19-security.md](19-security.md)). The domain stores only provider
names (strings) inside `Provenance`, `NarrationTrack`, `Evaluation.evaluator`,
`Source.news_source_provider` and Run Event payloads.

## Scheduled task (infrastructure record)

Not a domain entity, listed here because it is persisted:
`ScheduledTask {id, kind: enum(daily_run|metric_snapshot|retention_cleanup|auto_publish), due_at, payload, status: pending|running|done|failed|cancelled, attempts, last_error?}`.
See [architecture/workflow-architecture.md](architecture/workflow-architecture.md#scheduler).

## LLM request record (infrastructure record)

Persistent usage accounting for LLM rate limits (CF-REQ-669):
`LLMRequest {id, run_id?, task, provider, model, attempt_kind: enum(initial|schema_repair|call_retry), started_at, finished_at?, outcome: enum(success|rate_limited|transient_error|permanent_error|refused_by_limiter), http_status?, prompt_tokens?, completion_tokens?, cost_reported?, rate_limit_headers: JSON}`.
Daily and per-minute usage are computed from these rows.
