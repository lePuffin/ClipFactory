# 05 — Research and Source Grounding

Covers pipeline stages `research`, `cluster_stories`, `select_story`,
`gather_sources`, `extract_claims`.

Architecture: [architecture/workflow-architecture.md](architecture/workflow-architecture.md),
[diagrams/research-workflow.puml](architecture/diagrams/research-workflow.puml).
Entities: `Source`, `Story`, `StorySource`, `Claim`, `Evidence` in
[04-domain-model.md](04-domain-model.md). Decision: [ADR-014](decisions/ADR-014-source-grounded-story-claim-model.md).

## Principles

- **Article ≠ Story.** ClipFactory reasons about Stories. Many Articles may
  describe one Story; syndicated copies add Articles but not independent Sources.

  ```text
  Reuters ─┐
  AP ──────┤
  BBC ─────┼──► Story A   articles = 5, independent sources = 4
  CNN ─────┤
  Blog ────┘ (copy of Reuters → syndicated, origin_publisher = Reuters)
  ```

- **Small, high-quality input.** Fetch the full text of at most
  `ResearchPolicy.max_candidate_articles` (default 20; intended range 10–20)
  candidate articles, not hundreds.
- **Explicit evidence.** The pipeline is never `search → LLM summary → video`.
  Scripts are written from accepted Claims whose evidence is verified verbatim
  in Source text.
- **Source text is untrusted input** to LLM prompts (CF-NFR-108).

## Stage summary

| Stage | Deterministic work | LLM work |
| --- | --- | --- |
| `research` | Feed retrieval, age/publisher filtering, canonical URLs, text extraction, quality tiering, exact and near-duplicate detection | — |
| `cluster_stories` | Similarity pre-grouping | Confirm/merge groups that describe the same event |
| `select_story` | Weighted score, tie-breaks, novelty and exclusion filters | Relevance to profile and newsworthiness ratings |
| `gather_sources` | Matching and fetching additional Articles, independence computation | Optional query formulation |
| `extract_claims` | Evidence verification, support levels, acceptance rules | Claim extraction with excerpts |

## Requirements

### CF-REQ-100 — Candidate article discovery

- **Description:** The `research` stage shall obtain article references from
  every configured `NewsSource` and choose at most
  `ResearchPolicy.max_candidate_articles` candidates for full retrieval.
- **Inputs:** Content Profile snapshot, `research.feeds`, `research.publisher_quality`.
- **Behaviour:**
  1. Collect references (URL, title, publisher, published time, summary).
  2. Discard references older than `max_article_age_hours`, from
     `blocked` or `blocked_publishers` publishers, outside `allowed_publishers`
     when that list is set, or whose title/summary matches an excluded topic
     (case-insensitive keyword match).
  3. Rank remaining references by publisher tier (high > standard > low),
     then keyword overlap with profile topics, then recency; take the top N.
- **Failure:** Zero usable references ⇒ Run fails at `research` with
  `failure_code = no_candidates`. A failing `NewsSource` is logged as a
  warning event and the others are still used; if all fail, `no_candidates`.
- **Acceptance:**
  - With 50 fixture references and `max_candidate_articles = 20`, exactly 20 are fetched.
  - A reference from a blocked publisher is never fetched.
  - A reference 30 h old with `max_article_age_hours = 24` is discarded.
  - One of two `NewsSource`s raising an error still yields candidates from the other.
- **Related:** CF-REQ-103, CF-REQ-108, [provider-architecture](architecture/provider-architecture.md#newssource)

### CF-REQ-101 — Article retrieval and text extraction

- **Description:** The system shall retrieve each candidate URL and extract
  title, author, publication time, language and main plain text.
- **Behaviour:** Retrieval uses the safe HTTP client (CF-NFR-103). Extracted
  text is normalised (Unicode NFC, collapsed whitespace, control characters
  removed). `canonical_url` is derived from `<link rel="canonical">` when
  present, otherwise from the final URL with tracking parameters (`utm_*`,
  `fbclid`, `gclid`) and fragments removed.
- **Failure:** A failed or empty extraction marks the reference as skipped
  with a reason; it does not fail the stage unless no Article remains.
- **Acceptance:**
  - Two URLs differing only by `utm_source` produce one `Source` record.
  - Extracted text contains no HTML tags or script content.
- **Related:** CF-REQ-102, CF-NFR-103, CF-NFR-107

### CF-REQ-102 — Exact duplicate removal

- **Description:** Articles with the same `canonical_url` or the same
  `text_hash` shall be stored once.
- **Acceptance:**
  - Re-running research over identical fixtures creates no additional `Source` rows.

### CF-REQ-103 — Source quality evaluation

- **Description:** Each Source shall receive a `quality_tier` using
  deterministic rules.
- **Behaviour:** Start from `research.publisher_quality[publisher_domain]`
  (unknown ⇒ `standard`). Downgrade one tier when extracted text has fewer
  than 150 words (probable paywall/teaser) or no publication time. `blocked`
  Sources are never used as evidence.
- **Acceptance:**
  - A `high` publisher with a 90-word extraction becomes `standard`.
  - An unknown publisher with a full article is `standard`.
- **Related:** CF-REQ-107

### CF-REQ-104 — Syndication and near-duplicate detection

- **Description:** The system shall detect Articles that copy other Articles
  and record `syndication_of` and `origin_publisher`.
- **Behaviour:** Two Articles are near-duplicates when the Jaccard similarity
  of their normalised 5-word shingles ≥ `research.near_duplicate_threshold`
  (default 0.8, Provisional). The earlier-published (then higher-tier) Article
  is the original. Independently, text that credits a wire service in a
  dateline or credit line (e.g. "(Reuters) —", "Associated Press") sets
  `origin_publisher` to that wire service.
- **Acceptance:**
  - A blog Article that is a light rewrite of a Reuters fixture (similarity 0.9) gets `syndication_of = <Reuters source>` and `origin_publisher = Reuters`.
  - Two independently written fixtures on the same event (similarity 0.3) are not near-duplicates.
- **Related:** CF-REQ-106

### CF-REQ-105 — Story clustering

- **Description:** Story candidates shall partition the candidate Articles,
  each describing one underlying event.
- **Behaviour:**
  1. `cluster_stories` (deterministic, no LLM): near-duplicate groups
     (CF-REQ-104) are merged first; remaining Articles are grouped when
     title+lead token similarity exceeds a fixed threshold.
  2. The single `select_story` LLM request (LLM task `rank_stories`,
     CF-REQ-107) also receives the pre-groups (titles and leads only) and
     returns which pre-groups describe the same event, plus a title and
     one-sentence summary per merged Story candidate.
  3. Every Article belongs to exactly one Story candidate.
- **Failure:** A partition that omits or duplicates Articles fails schema
  validation (CF-REQ-758). If the LLM request ultimately fails, the
  deterministic pre-groups are used as Story candidates and a warning event
  is emitted.
- **Acceptance:**
  - The Reuters/AP/BBC/CNN/Blog fixture set yields one Story candidate with 5 Articles.
  - Two unrelated fixture events yield two Story candidates.
- **Related:** CF-REQ-106, ADR-014

### CF-REQ-106 — Independent source counting

- **Description:** For every Story, the system shall compute `article_count`
  and `independent_source_count` separately.
- **Behaviour:** `independent_source_count` = number of distinct
  `origin_publisher` values among non-syndicated, non-blocked evidence
  Sources linked to the Story.
- **Acceptance:**
  - Reuters, AP, BBC, CNN plus a Reuters copy ⇒ `article_count = 5`, `independent_source_count = 4`.
  - Two Reuters Articles from different Reuters URLs count as one independent Source.
- **Related:** CF-REQ-104, CF-REQ-111

### CF-REQ-107 — Story scoring and selection

- **Description:** The `select_story` stage shall score every eligible Story
  candidate and select exactly one.
- **Inputs:** Story candidates, Content Profile, `research.selection_weights`.
- **Behaviour:** One LLM request (task `rank_stories`, shared with the merge
  of CF-REQ-105) rates each candidate for `profile_relevance` and
  `newsworthiness` (0.0–1.0 each, with a one-sentence rationale) and flags
  excluded topics and recently covered Stories (CF-REQ-108, CF-REQ-109).
  Fallback selection (CF-REQ-111, CF-REQ-117) reuses these ratings without a
  new request. Code computes:
  - `independent_sources = min(independent_source_count / preferred_independent_sources, 1.0)`
  - `source_quality = mean(tier value)` with high = 1.0, standard = 0.6, low = 0.2
  - `recency = clamp(1 − age_hours_of_newest / max_article_age_hours, 0, 1)`
  - `score = Σ weight_i × criterion_i` using `selection_weights`.
  Ties break by higher `independent_source_count`, then newest Article, then
  lexicographic Story title. The selected Story is `selected`; others are
  `rejected` with a reason. Score breakdown and rationale are persisted.
- **Failure:** No eligible candidate ⇒ Run fails with `no_suitable_story`.
- **Acceptance:**
  - Given fixed fake LLM ratings, selection is identical across repeated runs.
  - The persisted `score_breakdown` contains all five criteria and weights.
- **Related:** CF-REQ-108, CF-REQ-109, CF-REQ-111

### CF-REQ-108 — Profile filters on Stories

- **Description:** Story candidates matching `excluded_topics` (keyword match
  on title/summary, or LLM flag returned with the relevance rating) shall be
  ineligible, and candidates whose category differs from the profile category
  shall be ineligible unless the profile category is `general`.
- **Acceptance:**
  - With `excluded_topics = ["celebrity"]`, a candidate titled "Celebrity divorce" is rejected with reason `excluded_topic`.
- **Related:** CF-REQ-551

### CF-REQ-109 — Story novelty [Derived]

- **Description:** A Story candidate shall be ineligible when it is judged the
  same Story as one covered by an approved Clip within
  `research.story_novelty_window_days`.
- **Rationale:** Daily Runs would otherwise repeatedly cover the same
  dominant Story.
- **Behaviour:** Compare by shared Source `canonical_url`s first; otherwise
  include the titles of recently covered Stories in the clustering/selection
  prompt and require the LLM to flag duplicates.
- **Acceptance:**
  - A candidate sharing a Source URL with a Clip approved 2 days earlier is rejected with reason `recently_covered` when the window is 7.
  - With the window set to 0, the same candidate is eligible.
- **Related:** CF-REQ-107

### CF-REQ-110 — Additional source gathering

- **Description:** After selection, `gather_sources` shall try to raise the
  Story's `independent_source_count` to `preferred_independent_sources`.
- **Behaviour:** Search, in order: (1) unused references from the research
  pool matching the Story; (2) `NewsSource.search()` for sources that support
  search, with a query derived from the Story title and key entities. Fetch at
  most `research.max_additional_sources` Articles, apply CF-REQ-101–104, and
  attach matches as `evidence`. Stop early once the preferred count is met.
- **Failure:** Not reaching the preferred count is **not** a failure; a
  `warning` event records the achieved count.
- **Acceptance:**
  - A Story with 1 independent Source and 2 matching unused references ends with 3.
  - `sources_collected` event payload contains `article_count` and `independent_source_count`.
- **Related:** CF-REQ-111, CF-REQ-106

### CF-REQ-111 — Minimum source requirement

- **Description:** A Story shall not proceed past `gather_sources` unless its
  `independent_source_count ≥ ResearchPolicy.min_sources` (default 1).
- **Rationale:** One strong Source can suffice; three independent Sources is
  the preferred standard, not a hard gate.
- **Acceptance:**
  - `min_sources = 1`: a Story with 1 high-tier Source proceeds with a warning that the preferred standard (3) was not met.
  - `min_sources = 2`: the same Story is rejected with `insufficient_sources`; the next-best eligible candidate is selected (counts toward the fallback limit of CF-REQ-117); with none left, the Run fails with `insufficient_sources`.
- **Related:** CF-REQ-107, CF-REQ-110

### CF-REQ-112 — Claim extraction with evidence

- **Description:** `extract_claims` shall extract atomic factual Claims about
  the selected Story from its evidence Sources, each with at least one
  verbatim excerpt and its Source ID.
- **Behaviour:** One structured LLM request (task `extract_claims`) receives
  all evidence Sources of the Story, each truncated deterministically so the
  total fits `llm.max_input_chars` (lowest-tier Sources are dropped first,
  then texts are cut at paragraph boundaries), and returns Claims with `kind`,
  excerpts and Source IDs, contradictions, the key-fact ranking (CF-REQ-151),
  and a refined Story title/summary. Claims across Sources expressing the same
  assertion are merged, combining evidence.
- **Acceptance:**
  - Every stored Claim has ≥ 1 `Evidence` entry referencing a Source of the Story.
  - A Story with 6 evidence Sources causes exactly 1 `extract_claims` request.
  - With input exceeding `llm.max_input_chars`, a `low`-tier Source is dropped before any `high`-tier text is truncated.
- **Related:** CF-REQ-113, CF-REQ-114

### CF-REQ-113 — Deterministic evidence verification

- **Description:** Each `Evidence.excerpt` shall be verified to occur in the
  referenced Source's text after normalisation (case-folding, whitespace
  collapse, unified quotes/dashes). Unverifiable excerpts get `verified = false`.
- **Rationale:** Prevents LLM-fabricated quotations from counting as support.
- **Acceptance:**
  - An excerpt with a single invented word is `verified = false`.
  - An excerpt differing only by curly vs straight quotes is `verified = true`.

### CF-REQ-114 — Support level

- **Description:** `support_level` shall be computed in code: `corroborated`
  if verified evidence comes from ≥ 2 independent Sources, `single_source` if
  from 1, `unsupported` if none.
- **Acceptance:**
  - Evidence from Reuters and its syndicated copy ⇒ `single_source`.
- **Related:** CF-REQ-106

### CF-REQ-115 — Claim acceptance

- **Description:** Claims shall be `accepted` unless `unsupported`, or
  contradicted by another accepted Claim without attribution.
- **Behaviour:** When Sources disagree (the LLM flags contradicting Claims),
  both Claims may be accepted only as `statement_attributed` Claims that name
  their Source; otherwise the less-supported Claim is rejected with reason
  `contradicted`.
- **Acceptance:**
  - `unsupported` Claims are always `rejected`.
  - Contradictory figures from two Sources end as two attributed Claims or one rejected Claim, never two unattributed accepted Claims.
- **Related:** CF-REQ-116

### CF-REQ-116 — Attribution of single-source claims

- **Description:** A script segment that uses a `single_source` or
  `statement_attributed` Claim shall attribute it to its Source by publisher
  name (e.g. "according to Reuters").
- **Acceptance:**
  - The script gate fails a segment that cites a `single_source` Claim without an `attribution`.
- **Related:** CF-REQ-158, CF-REQ-400

### CF-REQ-117 — Minimum grounded content

- **Description:** `extract_claims` shall fail the Story when fewer than 3
  accepted Claims exist.
- **Behaviour:** The workflow selects the next eligible Story candidate if
  one exists (at most 2 fallbacks per Run); otherwise the Run fails with
  `insufficient_claims`.
- **Acceptance:**
  - A fixture Story with 2 accepted Claims triggers fallback to the next candidate and emits a `story_selected` event for it.
- **Related:** CF-REQ-107

### CF-REQ-118 — Research persistence

- **Description:** All candidate references, fetched Sources, Story
  candidates with scores and rejection reasons, and Claims (accepted and
  rejected) shall be persisted and linked to the Run.
- **Rationale:** Answers "why was this Story chosen / why did research fail?".
- **Acceptance:**
  - The Run detail API returns every Story candidate with its status, score breakdown and rejection reason.
- **Related:** CF-REQ-850, CF-REQ-604
