# 15 — UI and Dashboard

Single-page web application (React, TypeScript, Vite, Tailwind CSS) served by
the backend. Architecture: [architecture/frontend-architecture.md](architecture/frontend-architecture.md).
API contract: [architecture/application-architecture.md](architecture/application-architecture.md#http-api).

## Pages

| Route | Page | Purpose |
| --- | --- | --- |
| `/` | Dashboard | Current Run, recent Runs, KPIs, next scheduled Run |
| `/runs` | Runs | Run history with status/outcome filters |
| `/runs/:id` | Run detail | Timeline, Story, Sources, Claims, Script, Evaluations, Clip, failure reason |
| `/clips` | Clips | Approved Clips, preview, publications, latest metrics |
| `/analytics` | Analytics | Per-platform metrics and estimated revenue over time |
| `/assets` | Asset library | Browse, filter, preview, provenance, status, import |
| `/profile` | Content Profile | Edit the active profile |
| `/settings` | Settings | Application settings, provider status, publishing mode, approval gate, budget limits and price table |

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
- **Acceptance:**
  - With fixtures, each element renders the expected values (component tests).

### CF-REQ-602 — Live Run progress

- **Description:** The UI shall display live Run progress through the SSE
  stream of Run Events, rendering the canonical stage list with states
  pending / running / done / failed / skipped and the current Attempt.
- **Behaviour:** On disconnect the client reconnects with `Last-Event-ID` and
  receives missed events; no polling loop is required.
- **Acceptance:**
  - An E2E test starting a fake Run sees stages advance to `publish` without page reload.
  - Reconnecting mid-Run shows no duplicated or missing events.
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
- **Acceptance:**
  - For a fixture Run failing with `evaluation_failed_after_retries`, the page shows the final blocking issues and all 4 Attempts.
- **Related:** CF-REQ-118, CF-REQ-409, CF-REQ-850

### CF-REQ-605 — Asset library

- **Description:** The asset library shall list Assets with filters (media
  type, category, origin, status, tag, licence), thumbnails/previews,
  provenance and attribution, usage count, and allow editing tags/description,
  quarantining/retiring, and importing files with licence metadata.
- **Acceptance:**
  - Retiring an Asset in the UI updates its status via the API and removes it from the default "active" filter.
- **Related:** CF-REQ-213, CF-REQ-216

### CF-REQ-606 — Settings

- **Description:** The settings page shall edit application settings
  sections, display the publishing mode prominently, and show per-provider
  selection and credential status (configured / not configured) without
  displaying or accepting secrets.
- **Acceptance:**
  - No input on the settings page accepts an API key or token.
  - Server-side validation errors are displayed next to the field.
- **Related:** CF-REQ-752, CF-REQ-753

### CF-REQ-607 — Content Profile editor

- **Description:** The profile page shall edit every Content Profile field
  with client-side validation mirroring CF-REQ-551 and server-side validation
  as authority.
- **Acceptance:**
  - Entering `min 90 / max 60` shows a field error and does not submit.

### CF-REQ-608 — Run Now

- **Description:** A Run Now button shall start a Run immediately. It is
  disabled while a Run is active; if the server reports a conflict, the UI
  shows the active Run link.
- **Acceptance:**
  - Clicking Run Now while idle navigates to the new Run's detail page.
  - The API returns 409 when a Run is active (see CF-REQ-652).

### CF-REQ-609 — Manual URL input

- **Description:** A Manual URL dialog shall accept one `http`/`https` URL,
  validate it client-side, and start a `manual_url` Run; server-side errors
  (invalid URL, blocked address, Run active) are displayed.
- **Acceptance:**
  - `ftp://example.com` is rejected before submission.
- **Related:** CF-REQ-700

### CF-REQ-610 — Clips page

- **Description:** The Clips page shall list approved Clips with preview
  playback (HTTP range streaming), Story title, creation time, and per-platform
  Publication status, link and latest metrics.
- **Acceptance:**
  - Seeking in the preview player issues range requests that the API serves with 206.

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
  - Estimated entries are visibly labelled "estimated".
- **Related:** CF-REQ-665

### CF-REQ-613 — Approval of pending Clips

- **Description:** When Clips are `awaiting_approval`, the dashboard shall
  show them prominently with preview, metadata per platform, the time left
  before auto-publish, and Approve / Reject actions.
- **Acceptance:**
  - Approving from the dashboard triggers publication and the item disappears from the pending list.
  - The countdown matches the `auto_publish` task due time.
- **Related:** CF-REQ-459, CF-REQ-460
