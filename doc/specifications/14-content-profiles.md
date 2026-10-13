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
| schedules | Independent daily rules in backend host local time (16); empty disables scheduling |
| env_prefix | Account credential scope for publishing and metric collection (12, 13) |
| research | Candidate limits and source thresholds (05) |
| music | Music selection and mix (09) |

## Requirements

### CF-REQ-550 — Saved content profiles and independent multi-profile scheduling

- **Description:** Content Profiles shall support saving named profiles, multiple
  concurrent active profiles, and independent scheduled execution times per profile
  (owner-approved extension, 2026-10-13). The owner may store multiple uniquely named
  profiles in the ID-keyed table. Names contain 1–160 characters after trimming
  surrounding whitespace and cannot be blank. Stored ID, name, activation status and
  update time are authoritative over those fields in submitted profile JSON.
- **Behaviour:** `GET /api/content-profiles` returns `{"items": [{"id", "name",
  "is_active", "updated_at", "profile": ContentProfile}]}`. Creation via
  `POST /api/content-profiles` accepts `{name, profile, activate: false}` and
  returns the item with 201 and a new ID. `PUT /api/content-profiles/{id}`
  accepts optional `name` and/or `profile` and returns the item.
  `POST /api/content-profiles/{id}/activate` activates that item.
  `POST /api/content-profiles/{id}/deactivate` deactivates that item.
  `POST /api/content-profiles/{id}/toggle-active` accepts `{"is_active": bool}`.
  `PUT /api/content-profiles/{id}/schedule` updates schedule settings and reconciles tasks.
  `GET /api/schedules` returns centralized execution schedule records for all profiles.
  `POST /api/content-profiles/{id}/schedules` adds a rule; `PUT/DELETE
  /api/content-profiles/{id}/schedules/{rule_id}` edits/removes one rule.
  Unknown rule IDs return 404 `rule_not_found` without changing other rules.
  Optional `env_prefix` selects account environment variables, for example
  `FOOTBALL_INSTAGRAM_ACCESS_TOKEN`. When set, only that scope's credentials
  and OAuth files may be used; missing credentials fail as `not_configured`,
  never falling back to another account. Unset prefixes preserve global
  credentials. Publication retries and metrics use the original Run snapshot.
  `DELETE /api/content-profiles/{id}` returns 204 for an inactive profile; deleting an
  active profile returns 409 with error code `active_profile_delete_forbidden`. Missing IDs
  return 404 `profile_not_found`; duplicate names return 409 `profile_name_conflict`,
  using the standard error envelope. Existing `GET/PUT /api/content-profile` continue to
  read/replace the active profile for backward compatibility; edits and activation never
  alter existing Run snapshots. Prior Runs retain their immutable `profile_snapshot`;
  their nullable `profile_id` reference becomes null through `ON DELETE SET NULL`.
  Creation also provisions the stable readable branding folder described
  in CF-REQ-360; rename/deletion retain that folder and historical inputs.
  `branding_folder` is server-assigned and cannot be changed by submitted
  profile JSON; copying a profile allocates a separate folder.
- **Acceptance:**
  - Multiple active profiles may be stored concurrently with index `ix_content_profile_is_active`.
  - Daily scheduler reconciles independent pending tasks for each active profile.
  - Every Run retains the complete profile snapshot it used; when that saved
    profile is deleted, only its live reference becomes null.
  - Creating an inactive profile leaves the active profiles unchanged.
  - Duplicate names, missing IDs and active deletion return the codes above
    without changing stored profiles.
  - Scoped credentials work without global credentials and cannot publish to
    global accounts when incomplete. Scoped values in the process environment
    override values in the configured environment files; values are never
    returned by profile endpoints.

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
  Schedule rules require valid 24-hour `HH:MM` times and unique rule IDs.
  Account prefixes are normalized to uppercase and must match
  `[A-Z][A-Z0-9_]{0,63}`; an empty prefix is unset.
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
