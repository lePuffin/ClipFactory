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
  The writer names each publisher at most once across the complete narration,
  not once per segment, while preserving every required attribution field.
  Media visual descriptions request ordinary photographable scenes that free
  stock libraries plausibly hold (places, crowds, buildings, objects,
  activities); on-screen text, tables, scoreboards, specific numbers, logos
  and screenshots are never requested as stock media, because data belongs
  in a typed graphics payload (CF-REQ-263, CF-REQ-266).
- **Acceptance:**
  - With a fake LLM, every returned segment is persisted with its claim IDs.
  - The writing prompt states the stock-findable media description rule.
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
  - The script gate counts `lead_in + tail` once: with the defaults a 146-word
    script is rejected as `script_too_short` and a 147-word script passes.
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
  - `repeated_attribution` — more than one spoken mention of a known publisher
    across the complete narration (CF-REQ-116); metadata fields do not count
  - `repeated_sentence` — the same sentence of five or more words (after
    case, whitespace and punctuation normalization) is spoken more than once
    across the complete narration; this is the deterministic form of
    CF-REQ-163's repetitive-narration `editorial_quality` rule. The same code
    flags a paraphrased restatement: a later sentence with four or more
    content words (stopwords and request verbs such as "asked" removed,
    simple suffix stemming so "convicted" and "conviction" match, stems of
    five or more letters matching when one prefixes the other so "reduced"
    and "reduction" match, spelled ordinals as numbers) of which at least
    65% already occur in one earlier sentence, or in the combined text of
    one earlier script segment (a closing line that re-summarizes a finding
    split across two sentences, as in live Run 9f50477a). A later sentence
    that is not directly after an earlier sentence with five or more content
    words and repeats at least 80% of that earlier sentence's content words
    is also a restatement, even when it adds new detail (owner review of live
    Run c7b99ffb: the hook "Andy Burnham will publish all details of his City
    dealings" was spoken again in full four sentences later). The revision
    instruction names both passages and asks for the restatement to be
    deleted or replaced by a different accepted fact (owner review of live
    Run d519e520: one eligibility fact was narrated three times; live Run
    620a25e1 followed a court deadline "to explain whether it reduced the
    reach … and to detail any irregularities" with "The court asked Meta to
    clarify both the reach reduction and the reported irregularities"). The
    same code also flags a Claim-grounded restatement that uses synonyms:
    each sentence is mapped to the accepted Claim whose words (digits also in
    spoken form) it covers most; a later sentence with three or more covered
    Claim words is a restatement when an earlier sentence other than the
    opening hook maps to the same Claim and already covers at least 60% of
    those words, and the later sentence adds at most one Claim word not yet
    spoken for that Claim (owner review of live Runs 0b566a75 — "secure a
    large victory" after "win by massive numbers" — and 63197c85 — "three
    points clear … at the summit" after "three-point lead at the top"). The
    opening hook is exempt as the earlier passage because the next sentence
    normally elaborates the headline. A Story too
    thin to reach the minimum duration without padding fails with
    `script_too_short` instead of producing repeated filler
  - `spoken_call_to_action` — a narration sentence asks the viewer to
    follow, subscribe, like, share, comment, turn on notifications, "stay
    tuned", or refers to "our/this channel/page"; or promises "we will keep
    monitoring/report/bring updates"; or tells viewers/the audience they are
    invited/encouraged to act or to submit questions (Run 5feb3c43: "The
    audience is encouraged to submit questions via social media during the
    broadcast."). The fixed end card (CF-REQ-360) is the
    only follow invitation in a Clip, so the narration never contains one
    (owner review of Clip 8c694e6d: "Please follow our channel for further
    news…" was spoken at 0:55 before the end card). The revision instruction
    names the sentence and asks for it to be deleted or replaced by an
    accepted fact. The post caption (`social_metadata.description`, CF-REQ-160)
    is not narration and keeps its follow invitation
  - `filler_padding` — narration padded with empty intensifier adverbs
    (notably, remarkably, noticeably, impressively, truly, incredibly,
    undeniably, strikingly, stunningly, astonishingly, amazingly,
    interestingly, importantly, clearly), ignoring text inside quotation
    marks: two or more in one sentence, or four or more across the whole
    narration (every sentence containing one is then named). Length is
    changed only by adding or removing accepted facts or necessary context
    (owner review of live Run 2274bf0b: a "add at least 4 words" retry
    produced "Notably, clearly he noticeably impressively scored…")
  - `stage_direction` — a narration sentence is a director's note rather
    than news copy: camera or shot language (the camera pulls back/pans/
    zooms, final/opening/wide shot, the shot lingers, cut to, fade out),
    an instruction to watch ("watch the action unfold", "we see", "on
    screen"), a description of on-screen lighting ("under bright overhead
    lights"), something that "appears in the crowd/frame", or a crowd
    action in the present tense ("crowd chants loudly"). Visuals are
    planned only in the media fields; the narration never describes them
    (owner review of approved Clip 4743e208: "The camera pulls back to show
    the rally hall…" was spoken at 0:23). Quoted text is ignored. The
    revision instruction names the sentence and asks for it to be deleted
    or replaced by an accepted fact
  - `unsupported_commentary` — a narration sentence with three or more
    content words of which fewer than 30% (after the restatement stemming)
    occur in the accepted Claims, the segment attributions or the Claim
    publishers. Digits in the evidence also count in their spoken form
    (860,000 → eight hundred sixty thousand; 2026 → twenty twenty-six).
    This catches generic analysis and invented context that names no
    specific fact, which `unsupported_statement` cannot see (owner standard
    "news, not opinion"; live Run a811d673 added "Observers view this as a
    notable shift.", "Critics argue the decision may influence regional
    stability." and "The warning emerged during a public briefing." although
    the warning was a social-media post; a scan of 393 sentences from 44
    completed scripts flagged 86, all padding, invented context or text from
    a rejected Claim). The revision instruction names the sentence and asks
    for it to be deleted or replaced by an accepted fact in the Claim's own
    words
  - `headline_fragment` — a segment's narration does not end with
    sentence-final punctuation (`.`, `!`, `?` or `…`, optionally followed by
    a closing quote or bracket), or its first word is entirely lowercase: the
    tail of a source sentence whose start was cut away (owner review of live
    Run ebea2875: segment 1 was "to do more to make sure it is safe."). Narration is spoken copy made of complete
    sentences, not headlines; an unpunctuated headline also runs into the
    next segment, which hides restatements of it from the sentence checks
    (owner review of live Run 48c3524d: the writer copied two live-blog
    headlines, "Hanson-Young writes to Albanese govt after Hegseth comment"
    and "Greens urge block of US execution livestream", as segments 0 and 1
    and the next segment repeated them). The revision instruction names the
    segment and asks for one complete spoken sentence
  - `script_too_short` / `script_too_long` — estimated duration outside `[min_seconds, max_seconds]`
  - `forbidden_content` — URLs, Markdown, SSML/markup, emoji, or text in a different script than the profile language's expected script
- **Failure:** A failed gate routes to a script revision (counts as a revision
  retry) with the issues as instructions.
  A schema-valid rejected draft is retained as a non-approved `write_script`
  stage artifact, bound to the Story Package, for the next retry/Continue.
  It is never the current accepted Script and cannot proceed downstream.
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
  For a retained schema-valid draft whose only failures are hook length,
  narration length, missing/repeated attribution or forbidden narration
  formatting, repeated sentences, a spoken call to action, filler padding, a stage direction, unsupported commentary or a headline fragment, the existing single `write_script` retry request returns only
  indexed narration corrections (`text`, `attribution`). Code merges these
  into the draft, preserving Claim IDs, purposes, social metadata, visual
  drafts and editorial overlays, then reruns every original gate. A hook-only
  failure permits only index 0; duration-only corrections preserve a passing
  hook. Duplicate, out-of-range or out-of-scope corrections are rejected.
  Other failures continue to use the full writer output. No extra call,
  unbounded repair loop, word truncation or relaxed gate is introduced.
- **Acceptance:**
  - Revising with a single `remove_claim` Action on segment 3 yields identical text for segments not citing that Claim (fake LLM honours instruction; code verifies unchanged segments are recognised as unchanged by text hash).
  - A retained 13-word hook failing a 12-word limit is corrected in one
    narration-only request; unaffected segments and all visual/metadata
    fields remain identical. A still-overlong correction remains rejected
    and is retained for the next bounded retry.

### CF-REQ-160 — Social metadata

- **Description:** The system shall generate platform-neutral social metadata:
  title (≤ 100 characters), description (≤ 2 000 characters), 3–8 hashtags,
  in the profile language, as part of the `write_script` request. The
  description is a descriptive post caption: two to four sentences that
  summarise the Story's key verified facts and why they matter, ending with
  an invitation to follow for more news; it never states facts absent from
  accepted Claims. Hashtags are specific discovery tags (people, places,
  organisations, topic) without spaces. When the generated description is
  shorter than 120 characters, the deterministic composition appends the
  Story Package summary. At publication, the platform-neutral request appends
  the configured `publishing.discovery_hashtags` (case-insensitive
  de-duplication) while keeping at most 8 hashtags, generated tags first.
- **Acceptance:**
  - Titles and descriptions exceeding limits are rejected by schema validation and repaired (CF-REQ-758).
  - The `write_script` prompt requests the descriptive caption and specific hashtags.
  - A one-line description is extended with the Story summary; three generated hashtags plus the default discovery tags yield six unique hashtags.
- **Owner decision 2026-10-11:** posts need a descriptive caption and hashtags that help platform discovery.
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
- **Owner branding revision (2026-10-10):** The explicitly configured end
  card in CF-REQ-360 may display the fixed "Follow for more" branding outside
  the spoken narrative. It does not invent a Claim or require a spoken CTA;
  its three seconds count within the tail and existing Clip duration budget.
  When the end card is configured it is the only follow/subscribe
  invitation: spoken narration never contains one (CF-REQ-158
  `spoken_call_to_action`).
- **Acceptance:** Two invitations fail when the configured maximum is one; disabling invitations emits no invitation text; a sensitive-story fixture contains no promotional invitation; removing an invitation leaves the factual narration unchanged.
- **Related:** CF-REQ-155, CF-REQ-163, CF-REQ-164
