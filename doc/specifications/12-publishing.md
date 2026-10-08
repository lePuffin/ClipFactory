# 12 — Publishing

Covers stage `publish`. Decision: [ADR-005](decisions/ADR-005-provider-adapters.md).
Port: `Publisher` in [architecture/provider-architecture.md](architecture/provider-architecture.md#publisher).
Diagram: [architecture/diagrams/publishing-flow.puml](architecture/diagrams/publishing-flow.puml).

```text
approved Clip + SocialMetadata
          │
          ▼
  PublicationRequest (platform-neutral)
          │
   ┌──────┼──────────┼──────────┐
   ▼      ▼          ▼          ▼
YouTube  Instagram  TikTok    Facebook   Publisher adapters (platform rules live here only)
Publisher Publisher Publisher Publisher
```

## Platform notes (unverified — must be validated during implementation)

These are known constraints to design around; none has been verified against
live APIs in this repository. See OD-009.

| Platform | Expected API | Notable constraint |
| --- | --- | --- |
| YouTube | YouTube Data API v3 `videos.insert` (resumable upload), OAuth 2.0 | Upload quota; vertical ≤ 3 min videos are surfaced as the platform's vertical format automatically |
| Instagram | Instagram Graph API (content publishing for professional accounts) | The API fetches media from a **publicly reachable URL**; solved with a short-lived signed URL through the owner's reverse proxy (CF-REQ-461) |
| TikTok | TikTok Content Posting API, OAuth 2.0 | Unaudited apps may be limited to private/self-only posts |
| Facebook | Facebook Graph API (Page video publishing), OAuth 2.0 via a Page access token | Like Instagram, the API fetches media from a **publicly reachable URL**; reuses the same short-lived signed URL mechanism (CF-REQ-461); posting requires a linked Facebook Page |

## Requirements

### CF-REQ-450 — Publish only approved Clips

- **Description:** The `publish` stage shall run only after a Clip becomes
  `approved` and shall publish only that Clip.
- **Acceptance:**
  - No code path creates a Publication for a non-approved Clip (see CF-REQ-413 tests).
- **Related:** CF-REQ-413

### CF-REQ-451 — Platform-neutral PublicationRequest

- **Description:** The workflow shall build one `PublicationRequest` from the
  Clip and `SocialMetadata` and pass it unchanged to every enabled
  `Publisher`. Each adapter adapts length limits, hashtag formatting and
  platform fields internally.
- **Acceptance:**
  - Workflow and application modules contain no platform-specific field names (architecture test on imports and a grep-based test for platform API terms).
  - Each adapter has unit tests for truncation of an over-long title.
- **Related:** CF-REQ-160, CF-REQ-161

### CF-REQ-452 — Publishing mode [Derived]

- **Description:** `publishing.mode` shall control publishing: `disabled`
  (skip the stage), `dry_run` (default; build requests, persist Publications
  with status `dry_run`, call no platform API), `live` (call adapters).
- **Rationale:** Prevents accidental posting during development and while
  credentials or platform approvals are incomplete.
- **Acceptance:**
  - In `dry_run`, fake publishers record zero calls and Publications exist with status `dry_run`.
  - Run outcome is `not_published` unless mode is `live`.

### CF-REQ-453 — Synthetic media disclosure

- **Description:** Adapters shall map `contains_synthetic_media` and
  `synthetic_voice` to the platform's disclosure mechanism where the API
  supports it and record in the Publication when it does not.
- **Acceptance:**
  - Adapter unit tests show the mapping (or the recorded "unsupported" note) for each platform.
- **Related:** CF-REQ-162

### CF-REQ-454 — Independent platform publications

- **Description:** Each platform enabled in the Content Profile shall be
  published independently; a failure on one platform shall not prevent the
  others.
- **Behaviour:** Run outcome: all succeeded ⇒ `published`; some ⇒
  `partially_published`; none ⇒ `not_published`. Publications requiring
  approval follow CF-REQ-459.
- **Acceptance:**
  - With YouTube succeeding and TikTok failing, the Run completes with `partially_published`.

### CF-REQ-455 — Idempotent publication

- **Description:** At most one Publication shall exist per (Clip, platform).
  A `published` Publication is never uploaded again. A Publication found in
  `publishing` state after a restart is set to `failed` with
  `error_code = unknown_outcome` and is not retried automatically.
- **Rationale:** Avoids duplicate posts when the outcome of an interrupted upload is unknown.
- **Acceptance:**
  - Resuming a Run whose YouTube Publication is `published` makes no YouTube call.

### CF-REQ-456 — Publisher failures

- **Description:** Transient publisher errors (timeouts, HTTP 429/5xx) shall
  be call-retried; permanent errors (auth, validation, quota exceeded) shall
  mark the Publication `failed` with a machine-readable `error_code` and
  actionable message.
- **Acceptance:**
  - A fake publisher returning a permanent `auth_failed` makes exactly one call.
- **Related:** CF-REQ-414

### CF-REQ-457 — Publisher configuration checks

- **Description:** Each adapter shall expose whether it is configured
  (credentials present and structurally valid). An enabled but unconfigured
  platform yields a `failed` Publication with `error_code = not_configured`
  in `live` mode, without calling the platform.
- **Acceptance:**
  - Enabling TikTok without credentials in `live` mode yields `not_configured` and a warning event.
- **Related:** CF-REQ-753

### CF-REQ-458 — Metric collection scheduling

- **Description:** When a Publication becomes `published`, the system shall
  create one scheduled metric task per `analytics.snapshot_offsets` entry,
  due at `published_at + offset`.
- **Acceptance:**
  - A publication at 10:00 creates tasks due at 11:00, 16:00, next day 10:00, +2 d, +7 d, +30 d.
- **Related:** CF-REQ-501

### CF-REQ-459 — Optional approval gate

- **Description:** When `publishing.approval_required` is true (default
  true in the quality rollout) and mode is `live`, the `publish` stage shall create Publications
  with status `awaiting_approval` instead of calling platforms, complete the
  Run with outcome `awaiting_approval`, emit `publication_awaiting_approval`,
  and hold them until an explicit owner decision. An `auto_publish` task is created only when timeout publication is explicitly enabled after the accepted quality benchmark.
- **Behaviour:** The owner approves or rejects in the UI/API. Approve ⇒
  publish immediately (as CF-REQ-454) and cancel the task. Reject ⇒
  Publications `rejected`, outcome `not_published`, task cancelled. The Run's
  outcome is updated when the approval resolves. Approval never bypasses
  evaluation: only `approved` Clips reach this state.
- **Acceptance:**
  - With the rollout gate on, no platform call happens before explicit approval, even after the configured legacy timeout.
  - Approving via `POST /api/clips/{id}/approval` `{decision: "approve"}` publishes once; a second approval is a no-op.
  - Rejecting sets all Publications `rejected` and outcome `not_published`.
- **Related:** CF-REQ-613, OD-019

### CF-REQ-460 — Auto-publish after timeout

- **Description:** If the owner has not decided when the `auto_publish` task
  becomes due, publication is allowed only when `publishing.auto_publish_enabled` is explicitly true, the quality benchmark is accepted, all required reviews pass for the exact variant hash, and the owner selected automatic operation. During human-review rollout it is false and no timeout may approve or publish.
- **Acceptance:**
  - Advancing a fake clock beyond ten minutes in human-review mode makes zero platform calls and leaves the owner decision pending.
  - Opt-in automatic mode publishes once only after benchmark/review checks; downtime does not bypass those checks.

### CF-REQ-461 — Signed public media URL for URL-pull platforms

- **Description:** For adapters whose platform API pulls media from a URL
  (Instagram, Facebook), the system shall issue a signed, expiring URL
  `${PUBLIC_MEDIA_BASE_URL}/public/media/{token}` for the Clip file
  being published, served by the backend and exposed publicly only via the
  owner's reverse proxy.
- **Behaviour:** Token = HMAC-SHA256 (with `MEDIA_URL_SIGNING_KEY`)
  over Clip ID and expiry; valid for `publishing.public_media_url_ttl_minutes`
  and only while the Publication is `publishing`. The endpoint serves `GET`/`HEAD`
  with range support and no other data. Without the base URL or key, the
  Instagram and Facebook adapters report `not_configured`.
- **Acceptance:**
  - A valid token serves the MP4; an expired, tampered or unknown token returns 404.
  - A token for a Clip whose Publication is no longer `publishing` returns 404.
- **Related:** CF-NFR-114, OD-009
