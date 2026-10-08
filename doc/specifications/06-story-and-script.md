# 06 — Story Package and Script

Covers stages `build_story_package` and `write_script`, and social metadata.
Entities: `StoryPackage`, `Script`, `ScriptSegment`, `SocialMetadata` in
[04-domain-model.md](04-domain-model.md).

## Story Package contents

```text
Story Package (versioned)
 ├── story            → Story (selected)
 ├── sources          → evidence Sources with independence flags
 ├── claims           → accepted Claims with verified evidence
 ├── key facts        → subset of accepted Claims
 ├── script           → Script (current + previous versions)
 ├── visual plan      → Visual Plan (see 08)
 ├── asset requirements → per Visual Segment (see 08)
 └── social metadata  → title, description, hashtags, attributions, disclosures
```

Downstream stages read only the Story Package (and the Assets it
references). They never call a `NewsSource` again.

## Requirements

### CF-REQ-150 — Story Package creation

- **Description:** `build_story_package` shall create a Story Package from the
  selected Story, its evidence Sources and accepted Claims.
- **Preconditions:** CF-REQ-111 and CF-REQ-117 satisfied.
- **Acceptance:**
  - The package references exactly the selected Story, its evidence Sources and only `accepted` Claims.
  - A `story_package_id` is set on the Run.
- **Related:** ADR-014

### CF-REQ-151 — Key facts

- **Description:** The system shall select 3–8 key facts (accepted Claims)
  ranked by support level (corroborated first) and LLM-judged importance.
  The importance ranking is returned by the `extract_claims` request
  (CF-REQ-112); no separate LLM request is made.
- **Acceptance:**
  - Every key fact ID is an accepted Claim of the Story.
  - With ≥ 3 corroborated Claims available, no `single_source` Claim ranks above a corroborated Claim of equal importance.

### CF-REQ-152 — Story Package versioning

- **Description:** Any change to the script, visual plan or social metadata
  shall increment `StoryPackage.version` and retain the previous version.
- **Acceptance:**
  - After one script revision, both version 1 and version 2 scripts are retrievable.
  - Each Clip records the `story_package_version` it was composed from.

### CF-REQ-153 — Grounded script generation

- **Description:** `write_script` shall generate a narration script in which
  every factual statement derives from accepted Claims of the Story Package.
- **Inputs:** Story, accepted Claims with evidence excerpts, key facts,
  Content Profile (language, category, duration, voice words-per-minute,
  visual style), `script.*` settings, and — on revision — the Actions to apply.
- **Behaviour:** One LLM request (task `write_script`) returns the script
  segments, the social metadata text (CF-REQ-160) and the visual plan draft
  (CF-REQ-250, CF-REQ-263). Each visual draft has a typed `kind` and, for
  graphics, a schema-validated declarative payload from the bounded templates
  in CF-REQ-263; legacy drafts without a kind default to `media`. Factual
  graphic labels, values and text cite accepted Claim IDs. This remains the
  same single structured request, not an additional LLM call or loop. Each
  segment lists the `claim_ids` it uses and an
  `attribution` when required (CF-REQ-116). The prompt forbids facts,
  numbers, names, dates or quotes not present in the provided Claims.
- **Acceptance:**
  - With a fake LLM, every returned segment is persisted with its claim IDs.
  - A segment citing a Claim ID not in the package is rejected by the script gate.
  - A first-attempt Run makes exactly one `write_script` request.
- **Related:** CF-REQ-158, CF-REQ-263, CF-REQ-406

### CF-REQ-154 — Script language

- **Description:** The script shall be written in the Content Profile
  `language`, regardless of Source languages.
- **Acceptance:**
  - With `language = "pt"`, the prompt requests Portuguese and the Script records `language = "pt"`.

### CF-REQ-155 — Duration budget

- **Description:** The system shall compute a word budget from the Content
  Profile: `target_words = round(target_seconds × words_per_minute / 60)`,
  `min_words = ceil(min_seconds × wpm / 60)`, `max_words = floor(max_seconds × wpm / 60)`,
  where each duration first has `lead_in_seconds + tail_seconds` subtracted.
- **Behaviour:** The LLM is asked for `target_words`; the estimated duration
  is `word_count × 60 / words_per_minute + lead_in + tail`.
- **Acceptance:**
  - Defaults (60/70/90 s, 150 wpm, 0.3 s + 1.0 s) ⇒ target 172, min 147, max 221 words.
- **Related:** CF-REQ-158, CF-REQ-401, OD-002

### CF-REQ-156 — Segment structure

- **Description:** A script shall contain between `script.min_segments`
  (default 4) and `script.max_segments` (default 8) segments.
- **Acceptance:**
  - A 3-segment script fails the script gate with issue `script_segment_count`.

### CF-REQ-157 — Hook

- **Description:** Segment 0 shall be the hook; its estimated duration shall
  not exceed `script.hook_max_seconds` (default 5 s) and it shall cite at
  least one accepted Claim.
- **Acceptance:**
  - A 20-word hook at 150 wpm (8 s) fails the script gate with `hook_too_long`.

### CF-REQ-158 — Script gate

- **Description:** After `write_script`, a deterministic stage gate shall
  validate the script and produce a `stage_gate` Evaluation.
- **Checks (each is a blocking issue code):**
  - `script_segment_count` — CF-REQ-156
  - `hook_too_long`, `hook_ungrounded` — CF-REQ-157
  - `segment_ungrounded` — a segment cites no Claim
  - `unknown_claim` — cites an ID that is not an accepted Claim of the package
  - `missing_attribution` — CF-REQ-116
  - `script_too_short` / `script_too_long` — estimated duration outside `[min_seconds, max_seconds]`
  - `forbidden_content` — URLs, Markdown, SSML/markup, emoji, or text in a different script than the profile language's expected script
- **Failure:** A failed gate routes to a script revision (counts as a revision
  retry) with the issues as instructions.
- **Acceptance:**
  - Each listed check has a unit test with a passing and a failing example.
  - A failed gate never proceeds to `plan_visuals`.
- **Related:** CF-REQ-410, CF-REQ-411

### CF-REQ-159 — Targeted script revision

- **Description:** When revising, the script writer shall receive the
  previous script, the blocking issues and Actions, and shall change only what
  the Actions require.
- **Behaviour:** Segments whose text is unchanged keep their index so that
  downstream artefacts (visual segments, selected Assets) can be reused
  (CF-REQ-412).
- **Acceptance:**
  - Revising with a single `remove_claim` Action on segment 3 yields identical text for segments not citing that Claim (fake LLM honours instruction; code verifies unchanged segments are recognised as unchanged by text hash).

### CF-REQ-160 — Social metadata

- **Description:** The system shall generate platform-neutral social metadata:
  title (≤ 100 characters), description (≤ 2 000 characters), 3–8 hashtags,
  in the profile language, as part of the `write_script` request.
- **Acceptance:**
  - Titles and descriptions exceeding limits are rejected by schema validation and repaired (CF-REQ-758).
- **Related:** CF-REQ-451

### CF-REQ-161 — Attribution in metadata [Derived]

- **Description:** `SocialMetadata.source_attributions` shall list the
  publisher and URL of every evidence Source cited by the script, and
  `asset_attributions` shall list the `attribution_text` of every used Asset
  whose licence requires attribution. Both are appended to the description.
- **Acceptance:**
  - A Clip using one CC BY image includes that image's attribution text in the description.
- **Related:** CF-REQ-203, CF-REQ-451

### CF-REQ-162 — Synthetic media disclosure flags [Derived]

- **Description:** `SocialMetadata.contains_synthetic_media` shall be true
  when any used Asset has `origin = generated`, and `synthetic_voice` shall be
  true whenever narration is produced by a TTS provider.
- **Rationale:** Platforms require disclosure of realistic synthetic media;
  adapters map these flags to platform features where available.
- **Acceptance:**
  - A Clip with only external photos and TTS narration has `contains_synthetic_media = false`, `synthetic_voice = true`.
- **Related:** CF-REQ-453

## News-explainer quality extension

Owner-authorized direction (2026-10-06): factual modern news explainers for YouTube, Instagram, TikTok and Facebook. These requirements extend the baseline; their presence does not mean their implementation or live verification is complete.

### CF-REQ-163 — Narrative beats and editorial intent

- **Description:** The existing `write_script` request shall return Narrative Beats alongside the narration, social metadata and Visual Plan draft, without an additional request for each creative feature.
- **Behaviour:** Each beat records its function (`hook`, `context`, `evidence`, `significance`, `uncertainty`, `conclusion` or `call_to_action`), Script Segment references, accepted Claim references, visual objective and emphasis. The Story shall explain what changed and why it matters, present relevant context and uncertainty, and reach an informative ending. Beat functions may be combined; irrelevant context or unsupported consequences shall not be invented to fill a template. Every Script Segment is covered in order. Word-count splitting is a timing safeguard, not a substitute for editorial shot planning.
- **Failure:** Missing or invalid references enter structured-output repair; incomplete or repetitive narration produces a blocking `editorial_quality` issue and a targeted script revision.
- **Acceptance:** A fixture containing a clipped sentence is rejected; an unchanged context beat survives a hook-only revision; a first successful script request supplies both narration and beats; every factual beat references accepted Claims.
- **Related:** CF-REQ-153, CF-REQ-157, CF-REQ-159, CF-REQ-406

### CF-REQ-164 — Evidence-bound engagement

- **Description:** Hooks, headlines and narrative emphasis shall make the Story understandable and interesting without misleading viewers.
- **Behaviour:** The hook identifies a supported development or significance within the existing hook duration. Material qualifications and uncertainty are preserved. The system shall not fabricate urgency, outrage, identity, quotes, unanswered questions or promised outcomes; withhold the central fact merely to force continued viewing; or optimize factual selection for controversy alone. Views, comments and subscriptions are goals to measure, not guaranteed outputs or factual quality scores.
- **Failure:** Unsupported statements or misleading framing block quality review using the existing grounding/editorial issue codes.
- **Acceptance:** A hook claiming a confirmed outcome when the evidence reports an allegation fails; a grounded question that the Story actually addresses passes; an unsupported engagement claim never appears in social metadata.
- **Related:** CF-REQ-116, CF-REQ-157, CF-REQ-160, CF-REQ-406, CF-REQ-408

### CF-REQ-165 — Optional audience invitation

- **Description:** A Clip may include a relevant, non-coercive audience invitation under `quality.*` policy.
- **Behaviour:** No more than `quality.max_ctas_per_clip` invitations are allowed; their duration counts against the existing Clip budget. A question must relate to the covered Story without asserting a new fact. Subscription invitations are optional rather than mandatory in every Clip. Sensitive-story policy suppresses promotional or playful invitations. Invitations are separately typed beats, never fabricated accepted Claims.
- **Failure:** Invalid invitations are removed or revised; they shall not force publication or bypass quality review.
- **Acceptance:** Two invitations fail when the configured maximum is one; disabling invitations emits no invitation text; a sensitive-story fixture contains no promotional invitation; removing an invitation leaves the factual narration unchanged.
- **Related:** CF-REQ-155, CF-REQ-163, CF-REQ-164
