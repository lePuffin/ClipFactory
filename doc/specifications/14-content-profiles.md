# 14 — Content Profiles

A Content Profile is the editorial and production configuration of
ClipFactory. Entity and value objects: [04-domain-model.md](04-domain-model.md#contentprofile).
Defaults: [18-configuration.md](18-configuration.md#content-profile-defaults).
Decision: [ADR-009](decisions/ADR-009-single-user-v1.md).

## Fields and how they are used

| Field | Used by (specification document) |
| --- | --- |
| language | Script, narration, captions, metadata, transcription hint (06, 09) |
| category | Story eligibility and selection prompt (05) |
| topics / excluded_topics | Candidate filtering and scoring (05) |
| geography / markets | Selection prompt, NewsSource feed filtering where supported (05) |
| voice | TTS voice and planning words-per-minute (09, 06) |
| duration | Script budget, gates, validation (06, 09, 11) |
| output | Composition and validation (10, 11) |
| visual_style | Visual plan prompt, caption style preset, generation permission (07, 08, 09) |
| platforms | Publishing targets (12) |
| schedule | Daily Run time (16) |
| research | Candidate limits and source thresholds (05) |
| music | Music selection and mix (09) |

## Requirements

### CF-REQ-550 — Single active profile

- **Description:** Exactly one Content Profile shall be active in v1.0. The
  owner may store multiple uniquely named profiles in the existing ID-keyed
  table, without migrating Runs. Names contain 1–160 characters after
  trimming surrounding whitespace and cannot be blank. Stored ID, name, activation and update
  time are authoritative over those fields in submitted profile JSON.
- **Behaviour:** `GET /api/content-profiles` returns `{"items": [{"id", "name",
  "is_active", "updated_at", "profile": ContentProfile}]}`. Creation via
  `POST /api/content-profiles` accepts `{name, profile, activate: false}` and
  returns the item with 201 and a new ID. `PUT /api/content-profiles/{id}`
  accepts optional `name` and/or `profile` and returns the item.
  `POST /api/content-profiles/{id}/activate` activates that item and atomically
  deactivates others. `DELETE /api/content-profiles/{id}` returns 204 for an
  inactive profile; deleting the active profile returns 409 with error code
  `active_profile_delete_forbidden`. Missing IDs return 404 `profile_not_found`;
  duplicate names return 409 `profile_name_conflict`, using the standard error
  envelope. Existing `GET/PUT /api/content-profile` continue to read/replace
  the active profile; edits and activation never alter existing Run snapshots.
  Deleting an inactive profile physically removes its row. Prior Runs retain
  their immutable `profile_snapshot`; their nullable `profile_id` reference
  becomes null through `ON DELETE SET NULL` (owner-approved retention decision,
  2026-10-11). No hidden tombstone is stored. Profile fields and the single-active
  unique index need no migration; this Run foreign-key change does.
- **Acceptance:**
  - Activating profile B deactivates profile A in the same transaction.
  - Every Run retains the complete profile snapshot it used; when that saved
    profile is deleted, only its live reference becomes null.
  - Creating an inactive profile leaves the active profile unchanged; activating
    it makes both row metadata and nested profile JSON agree.
  - Duplicate names, missing IDs and active deletion return the codes above
    without changing stored profiles.

### CF-REQ-551 — Profile validation

- **Description:** Profile updates shall be validated: BCP 47 language,
  known category, `0 < min ≤ target ≤ max` seconds, output 9:16 with even
  dimensions and 24 ≤ fps ≤ 60, valid IANA timezone and `HH:MM` time,
  platforms from the supported set, `1 ≤ min_sources ≤ preferred_independent_sources`,
  `1 ≤ max_candidate_articles ≤ 50`.
- **Behaviour:** Both named-profile creation/replacement and active-profile
  replacement validate ContentProfile values. Invalid profile JSON returns 422
  `{"error": {"code": "profile_validation_failed", "message":
  "Content Profile validation failed", "details": {"errors": [...]}}}`; invalid
  updates leave persisted values unchanged.
- **Acceptance:**
  - `min_seconds = 90, max_seconds = 60` is rejected with a field error.
  - `timezone = "Mars/Base"` is rejected.

### CF-REQ-552 — Configurable duration policy

- **Description:** Duration limits shall be read only from the active
  profile snapshot; no platform-specific or monetisation rule is hard-coded.
- **Acceptance:**
  - With a 30/35/45 s profile, the script budget, narration gate and Clip validation all use 30/35/45 (one test per consumer).
  - Domain and application code contain no platform names in duration logic (reviewer checklist item).
- **Related:** CF-REQ-401, CF-REQ-155

### CF-REQ-553 — Supported categories

- **Description:** The category enum shall contain `general`, `technology`,
  `ai`, `finance`, `business`, `science`, `gaming`, `sports`, `entertainment`,
  `politics`. All categories use the same source-grounded pipeline; no
  category bypasses grounding or evaluation.
- **Acceptance:**
  - A `politics` profile Run with fakes executes the same stages and gates as `general`.

### CF-REQ-554 — Language independence

- **Description:** Language shall flow from the profile into prompts, TTS,
  transcription and metadata; no English-only assumption exists in code paths
  other than defaults.
- **Acceptance:**
  - A fake end-to-end Run with `language = "es"` passes `es` to TTS and transcription fakes.

### CF-REQ-555 — Profile snapshot per Run

- **Description:** A Run shall use the profile snapshot taken at Run start;
  edits during a Run do not affect it.
- **Acceptance:**
  - Editing duration limits mid-Run does not change that Run's validation limits.
- **Related:** CF-REQ-653

### CF-REQ-556 — Versioned news style and quality policy

- **Description:** A Content Profile snapshot shall reference its news-style template/version, platform presentation targets, sensitivity policy and quality/review settings.
- **Behaviour:** Style controls beat/shot intent, overlay hierarchy, motion restraint, sound policy and optional invitations, not factual truth. Changes affect subsequent Runs/revisions only. All four platforms are design targets; publication requires explicitly enabled platforms, credentials and approved exact files. Default duration/resolution and financial limits are unchanged. Branding assets require owner approval; use the provisional neutral template until then.
- **Acceptance:** A template change cannot alter an in-progress snapshot; disabled invitations/SFX do not remove mandatory attribution; style selection never silently enables publication platforms.
- **Related:** CF-REQ-163–165, CF-REQ-261–262, CF-REQ-324, CF-REQ-555
