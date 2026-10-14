# 15 — UI and Dashboard

Single-page web application (React, TypeScript, Vite, Tailwind CSS) served by
the backend. Architecture: [architecture/frontend-architecture.md](architecture/frontend-architecture.md).
API contract: [architecture/application-architecture.md](architecture/application-architecture.md#http-api).

## Pages

| Route | Page | Purpose |
| --- | --- | --- |
| `/` | Overview | Current Run with agent personas, KPIs, budget, next scheduled Run |
| `/runs` | Runs | Run history with status/outcome filters |
| `/runs/:id` | Run detail | Timeline, Story, Sources, Claims, Script, Evaluations, Clip, failure reason |
| `/clips` | Clips | All / Published / Failed tabs, 20 Clips per page, preview, publications, latest metrics, approve / reject / delete actions |
| `/goals` | Goals | "Obtain Monetization" tracking qualification milestones, progress meters, and policy restrictions across YouTube, Facebook, Instagram, and TikTok |
| `/analytics` | Analytics | Per-platform metrics and estimated revenue over time |
| `/assets` | Asset library | Browse (20 per page), filter, preview, provenance, status, import |
| `/profile` | Content Profile | Select, save as new, edit, activate or delete saved profiles |
| `/settings` | Settings | Daily Run schedule, application settings, provider status, publishing mode, approval gate, budget limits and price table |

Global header: product name, current Run indicator, **Run Now** button,
**Manual URL** action.

## Requirements

### CF-REQ-600 — Visual design

- **Description:** The UI shall use a dark theme by default, a consistent
  Tailwind design system, and a responsive layout usable from 360 px width
  (mobile) to desktop.
- **Acceptance:**
  - Playwright screenshots at 390×844 and 1440×900 show no horizontal scrolling on any page.
- **Related:** CF-NFR-040

### CF-REQ-601 — Dashboard

- **Description:** The dashboard shall show: the active Run (stage, Attempt,
  elapsed time, latest message) or "idle"; the last 10 Runs with status and
  outcome; totals for the last 7 days (Clips approved, Publications, views,
  estimated revenue labelled "Estimated"); and the next scheduled Run time in
  the profile timezone.
- **Overview layout:** The Overview page does not show System Health,
  Publishing Gate or Recent Runs panels. The Current Run panel spans the full
  content width and presents each agent role as a **Persona**: a cartoonish
  human character, its name, and its role beneath it (Scout — research and
  discovery; Sage — Sources and Claims; Scribe — script and visual plan;
  Pixel — Asset selection; Echo — narration and captions; Frame —
  composition; Guard — validation and evaluation; Relay — publishing). Each
  Persona shows one of four moods derived from its stages in the current Run:
  **waiting** (eager), **working** (committed), **success** (happy) and
  **failure** (sad). The mood is expressed only through the character's face
  and pose; no mood word is shown. Directly beneath the role the Persona shows
  its state (Waiting, Working, Success or Failure). The eight Personas are
  compact and laid out as one row of eight on desktop widths, wrapping on
  narrow screens (owner request, 11 October). Personas are illustrative only;
  they do not imply autonomous agents at runtime.
- **Acceptance:**
  - With fixtures, each element renders the expected values (component tests).
  - A running stage puts its Persona in the working mood, finished stages
    show success, a failed stage shows failure, and untouched roles wait.

### CF-REQ-602 — Live Run progress

- **Description:** The UI shall display live Run progress through the SSE
  stream of Run Events. On Run detail, progress appears inside Execution as
  a stage-based loading bar, not a separate Live Progress panel. A text
  bubble anchored to the fill edge names the current stage; its state
  (pending / running / done / failed / skipped) and Attempt remain visible.
  Progress represents position in the canonical stage sequence for the
  trigger, not elapsed time; Retry re-entry can move it backwards. Queued
  Runs start at 0 %, completed Runs show 100 %, and failed Runs retain
  their stage position with failure styling.
- **Behaviour:** On disconnect the client reconnects with `Last-Event-ID` and
  receives missed events; no polling loop is required.
- **Refresh:** The dashboard's active Run (with live elapsed time and latest event message) and recent Runs refresh automatically; the Run detail page refreshes its record about every second until the Run is `completed` or `failed`.
- **Acceptance:**
  - An E2E test starting a fake Run sees stages advance to `publish` without page reload.
  - Reconnecting mid-Run shows no duplicated or missing events.
  - Run detail displays the bar within Execution, updates its fill and stage
    bubble from SSE, and keeps the bubble within the bar's width on mobile.
- **Related:** CF-REQ-852

### CF-REQ-603 — Analytics page

- **Description:** The analytics page shall show per-platform and total
  views, likes, comments, shares, watch time, retention and estimated revenue
  for 7 d / 30 d / all, and a time series per Publication. Estimated revenue
  is always labelled "Estimated revenue" with its basis; missing values show "n/a".
- **Acceptance:**
  - No UI string presents revenue without the word "Estimated".
- **Related:** CF-REQ-504, CF-REQ-505

### CF-REQ-604 — Run detail

- **Description:** The Run detail page shall answer "why did this Run fail
  or succeed": event timeline, Story candidates with scores and rejection
  reasons, Sources (article vs independent counts), Claims with support
  levels and evidence, Script versions, Visual Plan with selected Assets,
  every Evaluation with issues and actions per Attempt, Clip preview,
  Publications, and the failure stage/code/message.
- **Behaviour:** The Event Stream displays events in descending sequence
  order: newest first, with the first event at the bottom. Display ordering
  does not change the chronological event data used to derive progress.
  Previously persisted generation heartbeats are hidden from the Event
  Stream and its displayed count; meaningful generation milestones remain.
  Execution shows elapsed time from Run start (live until termination, then
  frozen) and the LLM model and evaluation model from the Run settings
  snapshot. Elapsed durations of at least one hour use hours, minutes and
  seconds (for example `1h 05m 09s`); shorter durations retain minutes/seconds.
  Missing values display "n/a".
  Execution also shows `Visuals` as the one-based current Visual / total
  Visuals in the plan (for example `10 / 11`), updated during Asset selection
  and generation. Missing Visual counts display "n/a"; continuation does
  not show stale counts from a prior execution before new progress arrives.
  Generation activity shows its provider, model, phase, actual inference
  steps or rendered-frame counts, and template provenance via Run Events;
  loading/download is indeterminate, never an invented percentage.
  Local graphics renders use phase `rendering`, expose the selected
  HyperFrames/Manim adapter and template provenance, and may show
  `progress_fraction` only when measured from actual completed frames;
  watchdog heartbeats are silent and do not advance the displayed progress.
  During Wan inference, actual step progress advances the Execution bar within
  `select_assets`, weighted by Visual index/count. Encoding and validation
  reserve the end of each Visual's portion; stage completion finishes it.
- **Acceptance:**
  - For a fixture Run failing with `evaluation_failed_after_retries`, the page shows the final blocking issues and all 4 Attempts.
  - The Run record header links to the produced Clip when `clip_id` is present,
    including on failed Runs; no Clip link is offered before one exists.
  - Initial and newly received events appear newest first without duplicates.
  - Execution updates elapsed time while running and freezes it at finish.
  - Generation phases update live and expose failures, including after reload.
  - Failed records offer Continue Run with current application settings,
    preserving the Run ID and completed work and resetting used revision
    retries to zero (CF-REQ-657); conflicts are shown.
  - Continue Run and Stop are adjacent to Execution status. Stop is offered
    for queued/running Runs. Both act on one click without confirmation
    panels; descriptive button titles explain current-settings use and
    potential unfinished-media loss. Pending requests disable their controls,
    Stop shows Stopping until completion, and API errors remain visible.
- **Related:** CF-REQ-118, CF-REQ-265, CF-REQ-409, CF-REQ-850

### CF-REQ-605 — Asset library

- **Description:** The asset library shall list Assets with filters (media
  type, category, origin, status, tag, licence), thumbnails/previews,
  provenance and attribution, usage count, and allow editing tags/description,
  quarantining/retiring, and importing files with licence metadata.
- **Behaviour:** Selecting an Asset opens an inline preview with video/audio
  controls or an image, using the existing range-capable Asset file endpoint.
  The library shows the storage key; the preview shows the resolved local
  folder and filename when local storage is configured, plus provenance and
  media metadata. Missing/unplayable media displays an explicit error.
- **Acceptance:**
  - Retiring an Asset in the UI updates its status via the API and removes it from the default "active" filter.
  - Image, video and audio Assets can be previewed without leaving the library.
  - The selected Asset's folder, filename and storage key are visible; the
    file can also be opened directly using its Asset-ID endpoint.
    - Media type, origin and provider filters combine with status filtering.
      Provider choices come from the loaded Assets' provenance, including
      local generators and external media sources. These filters operate on
      the current loaded library page (up to 500 Assets for the selected status).
  - The library paginates 20 Assets per page using `limit`/`offset` and the
    returned `total`.
- **Related:** CF-REQ-213, CF-REQ-216

### CF-REQ-606 — Settings

- **Description:** The settings page shall edit application settings
  sections, display the publishing mode prominently, and expose provider
  selection without displaying or accepting secrets. Provider readiness and
  credential-status summaries shall not appear on Settings.
- **Acceptance:**
  - No input on the settings page accepts an API key or token.
  - Provider readiness and its credential-status grid are absent, even when
    the settings response includes provider credential-presence metadata.
  - Server-side validation errors are displayed next to the field.
  - Fixed-choice environment output modes, Whisper device and publishing
    mode use labelled dropdowns containing their configured allowed values.
    Closed controls and native option menus have readable dark-theme contrast
    and keyboard focus indicators. Unknown existing values remain visible,
    never silently replaced; open-ended model IDs and other strings remain editable.
  - Settings / Environment exposes `wan_max_generations_per_run` (default 2,
    integer 0–100) with guidance that 0 disables new Wan calls and Retry/
    Continue retain usage. Additional Visuals use suitable graphics or refined
    free-media searches, not unlimited Wan generation (CF-REQ-266).
  - Automation & Dispatch belongs to Content Profile, not Settings.
    It groups rules by selectable saved profile, supports adding multiple
    daily times, explicit time saving, enabled toggles and individual deletion.
    All times use backend host local time, without a timezone picker.
    Inactive profiles remain editable; activation controls dispatch only.
    Validation and API failures remain visible. Empty schedules allow adding
    a new rule. The profile editor exposes Account Env Prefix but no secrets.
  - Each Settings group, including Providers and nested setting groups, is a
    collapsible section that starts collapsed, is operable by keyboard
    (button with `aria-expanded`), and can be expanded or collapsed
    independently without losing unsaved edits.
  - Research policy belongs to the selected Content Profile (CF-REQ-607), not
    Settings: the settings page never offers a Research section, even when a
    legacy payload still contains one.
- **Related:** CF-REQ-651, CF-REQ-752, CF-REQ-753

### CF-REQ-607 — Content Profile editor

- **Description:** The profile page shall edit every Content Profile field
  with client-side validation mirroring CF-REQ-551 and server-side validation
  as authority. A selector lists saved Content Profiles; the owner can load
  one for editing, save the current form as a new named profile, update or
  activate the selected profile, and delete a profile that is not active
  (CF-REQ-550 named-profile APIs).
- **Profile branding:** The selected saved profile shows its stable
  server-assigned `branding/<profile-slug>/` path and the `uv run clipfactory branding` command.
  These are read-only instructions, not editable arbitrary filesystem paths.
- **Acceptance:**
  - Entering `min 90 / max 60` shows a field error and does not submit.
  - Saving as new adds the profile to the selector; deleting the active
    profile is refused with the server's 409 message.
  - The selected profile shows one dedicated, initially collapsed Research section containing the
    research limits plus RSS feeds (`[publisher, url]` rows that can be added
    and removed), publisher quality tiers by hostname, story novelty window,
    maximum article bytes and the other profile research fields. Edits are
    saved only with the selected profile. An empty feed list is saved as
    `[]` and shown as an explicit empty state; it never inherits another
    profile's feeds. Client checks mirror the backend exactly (duplicate feed
    URLs and any hostname case are allowed; values are sent unnormalized);
    labelled errors appear next to their fields and block submission.

### CF-REQ-608 — Run Now

- **Behaviour:** Start a Run includes a labelled Content Profile selector
  listing saved profiles, including inactive ones. The owner explicitly
  chooses the profile used by Run Now and Manual URL. Loading, unavailable
  or empty profile lists disable dispatch and display their state. Selecting
  a profile does not alter activation or schedules. The selected ID is sent
  to the API and its immutable snapshot, including account scope, is used.
  API clients omitting the ID retain the most recently updated active profile
  default. A missing selected profile returns 404 `profile_not_found`, never
  silently creating or selecting a default.
- **Description:** A Run Now button shall start a Run immediately. It is
  disabled while a Run is active; if the server reports a conflict, the UI
  shows the active Run link.
- **Acceptance:**
  - Clicking Run Now while idle navigates to the new Run's detail page.
  - The API returns 409 when a Run is active (see CF-REQ-652).
  - Choosing a different saved profile changes the Run snapshot without
    changing any saved profile's activation status or schedule.

### CF-REQ-609 — Manual URL input

- **Description:** A Manual URL dialog shall accept one `http`/`https` URL,
  validate it client-side, and start a `manual_url` Run; server-side errors
  (invalid URL, blocked address, Run active) are displayed.
- **Acceptance:**
  - `ftp://example.com` is rejected before submission.
- **Related:** CF-REQ-700

### CF-REQ-610 — Clips page

- **API behaviour:** `GET /api/clips` accepts `limit` (default 100, 1–100),
  `offset` (default 0, non-negative) and `filter=all|published|failed` (default
  `all`). It returns `{"items": [...], "total": integer}` with existing item
  fields, newest-first ordering and ID tie-breaker. `all` includes every Clip
  status; `published` means at least one Publication has status `published`;
  `failed` means Clip status `rejected`/`failed` or at least one Publication
  has status `failed`. These predicates may overlap and each Clip is counted
  once. Total is computed after filtering and before limit/offset; out-of-range
  offsets return empty items with the full filtered total. Invalid parameters
  return 422. Listing failed Clips does not authorise their publication.

- **Description:** The Clips page shall list Clips with preview
  playback (HTTP range streaming), Story title, creation time, and per-platform
  Publication status, link and latest metrics, in three tabs — **All**,
  **Published** and **Failed** — mapped to the `filter` parameter, 20 Clips
  per page. A `published` status badge is shown in green. Each Clip card
  features individual **Approve** and **Reject** actions directly below the
  platform states only while a Publication awaits approval and no Publication
  is already published. Delete is an accessible trash icon in the top-right
  corner of the card or detail panel. Approving or rejecting submits the
  publication decision, and deleting removes the Clip, its render revisions,
  scheduled publish tasks, and storage media.
- **Acceptance:**
  - Switching tab resets to page 1 and requests the matching filter;
    pagination controls reflect `total`.
  - Clip duration is displayed rounded to the nearest whole second on cards
    and detail pages; stored media duration remains precise.
  - A Publication with `error_code=not_configured` displays only a red
    `Not Configured` status, not `Failed` or an additional detail/metrics line.
    This also applies to pending-approval platform badges (CF-REQ-457).
  - Seeking in the preview player issues range requests that the API serves with 206.
  - Published Clips show no Approve or Reject buttons, including when the
    Clip remains `approved` but a Publication is `published`.
  - Pending approval Clips retain Approve and Reject; every card has an
    icon-only Delete button with an accessible label and confirmation.
  - Unavailable preview media shows an explicit error rather than a blank player.

### CF-REQ-611 — Safe rendering of external text

- **Description:** All text originating from Sources, LLMs, providers or
  platforms shall be rendered as text, never as HTML.
- **Acceptance:**
  - A Source title `<img src=x onerror=alert(1)>` renders literally (component test).
  - The codebase contains no `dangerouslySetInnerHTML` (lint rule).
- **Related:** CF-NFR-107

### CF-REQ-612 — Cost display

- **Description:** The UI shall show cost in `budget.currency`: per Run (total
  and entries by provider/operation, marked reported or estimated) on Run
  detail; cost per Clip on the Clips page; month-to-date spend versus the
  monthly limit and the per-Clip limit on the dashboard; and editable limits
  and price table on the Settings page.
- **Acceptance:**
  - The dashboard shows e.g. "€12.40 of €30.00 this month" matching `GET /api/budget`.
  - Overview budget amounts (spend, monthly limit, remaining and per-Clip
    limit) display exactly two decimal places, rounding for display only.
  - Estimated entries are visibly labelled "estimated".
- **Related:** CF-REQ-665

### CF-REQ-613 — Approval of pending Clips and Monetization Goals

- **API behaviour:** `GET /api/clips/pending-approval` accepts `limit` (default
  100, 1–100) and `offset` (default 0, non-negative), returning
  `{"items": [...], "total": integer}`. Only approved Clips with at least one
  `awaiting_approval` Publication qualify; pagination, stable ordering and total
  follow CF-REQ-610. `GET /api/goals` and `POST /api/goals/refresh` return
  monetization progress across YouTube, Facebook, Instagram and TikTok.

- **Description:** When Clips are `awaiting_approval`, each Clip in the Clips
  workspace shall display explicit Approve and Reject buttons directly beneath
  its platform statuses, unless a Publication is already published. The
  navigation provides a dedicated **Goals** tab
  (`/goals`), titled **Obtain Monetization**, displaying platform subscriber/follower
  milestones, watch hours/views, and regulatory policy restrictions including
  EU AI Act Article 50 transparency disclosure ("AI Generated" badge in the
  bottom-left corner). Goals can be refreshed on demand via the update button.
- **Acceptance:**
  - Approving or rejecting a Clip submits the publication decision.
  - The Goals tab displays milestones, progress percentages, and policy checklists for each eligible platform.
  - The update button on the Goals page refreshes metrics.
- **Related:** CF-REQ-459, CF-REQ-460

### CF-REQ-614 — Storyboard and version-bound quality review UI

- **Description:** The owner shall inspect the beat/shot contact sheet, Asset provenance/licence/date/identity evidence, subtitles and editorial labels, motion/transition intent, audio cues, full playback and remaining request/cost budget before approving a render.
- **Behaviour:** Permit targeted replace/trim/label/style/audio edits through saved-package rerender. Show cache reuse, pending reasons and exact version/hash. Distinguish technical validity, model review, owner approval and publication eligibility. Blocking factual/licensing/security issues cannot be bypassed. Changed output invalidates stale approval.
- **Acceptance:** Replacing a shot makes no new research or unchanged TTS calls; unverified identity is visible; stale-hash approval is rejected; quota-blocked evidence remains pending.
- **Related:** CF-REQ-260, CF-REQ-361, CF-REQ-417, CF-REQ-459
