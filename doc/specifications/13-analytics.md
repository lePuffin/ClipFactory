# 13 — Analytics

Covers post-publication metric collection and estimated revenue.
Entity: `MetricSnapshot`, `EstimatedRevenue` in [04-domain-model.md](04-domain-model.md#metricsnapshot).
Metrics are fetched through the platform adapter's `fetch_metrics` operation
([provider-architecture](architecture/provider-architecture.md#publisher)).
Scheduling: [16-scheduling-and-runs.md](16-scheduling-and-runs.md).

## Requirements

### CF-REQ-500 — Metric collection

- **Description:** For each due metric task, the system shall call the
  platform adapter's `fetch_metrics` for the Publication and persist a
  `MetricSnapshot` with views, likes, comments, shares, watch time, average
  retention, follower delta, estimated revenue, platform, Publication and
  capture timestamp.
- **Acceptance:**
  - A fake adapter returning fixed metrics produces a snapshot with identical values and `offset_label` matching the task.
- **Related:** CF-REQ-458

### CF-REQ-501 — Snapshot schedule

- **Description:** Snapshots shall be taken at the offsets in
  `analytics.snapshot_offsets` (default 1 h, 6 h, 24 h, 48 h, 7 d, 30 d after
  `published_at`). Changing the setting affects Publications published
  afterwards.
- **Acceptance:**
  - With offsets `["2h"]`, a new Publication gets exactly one task at +2 h.

### CF-REQ-502 — Missing metrics are null

- **Description:** Metrics a platform does not provide shall be stored as
  `null` and displayed as "not available", never as 0.
- **Acceptance:**
  - A fake adapter omitting `shares` yields `shares = null`; the UI shows "n/a".

### CF-REQ-503 — Late and failed snapshots

- **Description:** A task due while the application was down shall run at
  the next scheduler tick, recording the actual `captured_at`. Transient
  failures are retried at the next tick up to 3 attempts; then the task is
  `failed` with the error recorded.
- **Acceptance:**
  - With a fake clock advanced 5 h past due, the snapshot is captured once with `captured_at` = current time.

### CF-REQ-504 — Estimated revenue

- **Description:** `estimated_revenue` shall be:
  1. the platform-reported estimated revenue if the adapter provides it
     (`basis = platform_reported_estimate`); else
  2. `views / 1000 × analytics.rpm_by_platform[platform]` when an RPM is
     configured (`basis = rpm_estimate`, `rpm_used` stored); else
  3. `null`.
- **Behaviour:** All UI and API labels say "Estimated revenue"; totals mix
  bases only with a visible breakdown by basis.
- **Acceptance:**
  - 12 000 views with RPM 0.50 USD ⇒ 6.00 USD, basis `rpm_estimate`.
  - No RPM configured and no platform estimate ⇒ `null`.
- **Related:** OD-010

### CF-REQ-505 — Analytics queries

- **Description:** The API shall provide aggregated analytics: per platform
  and overall totals for a period (7 d, 30 d, all), per-Clip latest metrics,
  and per-Publication snapshot time series.
- **Behaviour:** Aggregates use the latest snapshot per Publication.
- **Acceptance:**
  - Two snapshots for one Publication (1 h: 100 views, 24 h: 900 views) contribute 900 views to totals.
- **Related:** CF-REQ-603

### CF-REQ-506 — Snapshot immutability

- **Description:** Metric Snapshots shall be append-only; at most one per
  (Publication, offset label).
- **Acceptance:**
  - Re-running a completed task does not create a second snapshot.

### CF-REQ-507 — Capability-aware engagement metrics

- **Description:** Engagement reporting shall expose platform-supported views, watch time, retention/completion, comments, shares and attributable follows/subscriptions with metric definitions, source, capture time, denominator and capability availability.
- **Behaviour:** Unsupported fields remain null, not zero or inferred. Account-level follower delta is not per-Clip subscription conversion. Retention curves or comment intent are not fabricated from aggregate counts. Incompatible platform definitions are not directly compared. Raw-comment ingestion or sentiment analysis is outside this increment.
- **Acceptance:** Unsupported attributable subscriptions display unavailable; cumulative snapshots are not summed; completion rate has an explicit denominator and is unavailable without it.
- **Related:** CF-REQ-500, CF-REQ-502, CF-REQ-505

### CF-REQ-508 — Versioned creative comparisons

- **Description:** Analytics shall connect each Publication to its exact Story Package/render/template/hook versions and permit owner-controlled comparisons of creative changes.
- **Behaviour:** Compare matching platform, capture age and compatible definitions; show sample size, exposure and confounders. Distinguish observational comparisons from platform-provided randomized experiments. Record the changed creative variable. Results inform owner decisions, never guarantee growth or automatically optimize editorial policy for controversy.
- **Acceptance:** Cumulative observations contribute only the latest count; an observational hook comparison is not labelled an A/B experiment; low-exposure results show sample size rather than declaring a winning style.
- **Related:** CF-REQ-164, CF-REQ-505, CF-REQ-507
