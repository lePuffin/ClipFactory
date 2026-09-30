# 17 — Manual Input (Manual URL)

The user can seed a Run with a news URL. The Manual URL path replaces only
the `research`, `cluster_stories` and `select_story` stages with
`ingest_url`; everything from `gather_sources` onward is the normal pipeline.
There is no second production pipeline.

```text
Manual URL ──► ingest_url ──► gather_sources ──► extract_claims ──► … (normal pipeline)
```

## Requirements

### CF-REQ-700 — Manual URL submission

- **Description:** The API shall accept a URL and start a Run with
  `trigger = manual_url`.
- **Inputs:** `url` string.
- **Behaviour:** Validate before creating the Run: scheme `http`/`https`,
  length ≤ 2 048, host present, no credentials in URL, host resolving only to
  public addresses (CF-NFR-103). Single-active-Run rule applies (CF-REQ-652).
- **Failure:** Invalid URL ⇒ 422 with reason; nothing is created.
- **Acceptance:**
  - `http://127.0.0.1/admin`, `http://10.0.0.5/`, `file:///etc/passwd` and `https://user:pw@example.com/` are rejected with 422.
  - A valid public URL returns 202 with a Run ID.
- **Related:** CF-REQ-609

### CF-REQ-701 — URL ingestion

- **Description:** `ingest_url` shall fetch and extract the article
  (CF-REQ-101, CF-REQ-103, CF-REQ-104), create its `Source`, and create a Story
  with `status = selected`, using the article title and lead paragraph as
  provisional title and summary (no LLM request; refined by the
  `extract_claims` request).
- **Failure:** Unreachable URL ⇒ `url_unreachable`; non-article or
  unextractable content ⇒ `url_not_article`; a `blocked` publisher ⇒
  `url_blocked_source`. Each fails the Run at `ingest_url`.
- **Acceptance:**
  - A fixture article URL yields one Source (role `evidence`) and one selected Story, then a `story_selected` event.

### CF-REQ-702 — Same pipeline after ingestion

- **Description:** After `ingest_url`, the Run shall continue at
  `gather_sources` and execute the same stages, gates, evaluation, retry and
  publishing rules as a scheduled Run.
- **Acceptance:**
  - The E2E manual URL test observes the same stage sequence from `gather_sources` onward as the scheduled test.
  - No module contains a manual-URL-specific branch after `ingest_url` (reviewer check; workflow graph test).

### CF-REQ-703 — Profile rules for user-selected Stories

- **Description:** For a Manual URL, category mismatch, excluded topics and
  story novelty shall produce `warning` events instead of rejection, because
  the user chose the Story explicitly. Source grounding rules
  (CF-REQ-111, CF-REQ-117) still apply.
- **Acceptance:**
  - A URL about an excluded topic proceeds with warning `excluded_topic_overridden`.
  - A URL with only 2 extractable Claims fails with `insufficient_claims` (no fallback candidate exists).
