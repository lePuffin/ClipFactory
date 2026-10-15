# 08 — Visual Production

Covers stage `plan_visuals` and the visual rules used by `select_assets` and
`compose_clip`. Entities: `VisualPlan`, `VisualSegment`, `AssetRequirement`
in [04-domain-model.md](04-domain-model.md).

**Rule:** basic motion (pan, zoom, crop, Ken Burns, transitions) remains
deterministic FFmpeg processing. Typed infographic and scientific graphic
Assets use the bounded local renderers in CF-REQ-263–265; they are not
authored with FFmpeg filters/SVG or model-supplied code. FFmpeg remains the
final assembler/prober and may be used internally by a renderer for encoding.
Ordinary media remains on the existing acquisition/permitted Wan path.
Native Wan calls are bounded per Run by CF-REQ-266.

## Requirements

### CF-REQ-250 — Visual Plan generation

- **Description:** `plan_visuals` shall produce a Visual Plan with at least
  one Visual Segment per Script Segment, in script order.
- **Behaviour:** The visual plan draft comes from the `write_script` LLM
  request (CF-REQ-153): per segment, visual objective, typed visual
  kind/payload, motion and transition suggestions. `plan_visuals` itself is
  deterministic: it validates and normalises the draft
  (CF-REQ-251, CF-REQ-253, CF-REQ-263), computes
  planned durations from word counts, and splits any Script Segment whose
  estimated duration exceeds `visual.max_segment_seconds`. A `replan_visuals`
  Action re-issues the `write_script` request with the script frozen; code
  verifies the script text is unchanged. When the draft lists fewer Visuals
  than Script Segments, schema normalization appends one reviewable media
  Visual per uncovered Script Segment (description from that segment's
  narration, tags from its narration keywords, category of the last drafted
  Visual) instead of rejecting the whole Script; these Visuals follow normal
  acquisition, review and `missing_asset` rules.
- **Acceptance:**
  - Every Visual Segment references a valid `script_segment_index`.
  - Segments appear in narration order; planned durations sum to the script's estimated duration ± 1 s.
  - `plan_visuals` makes no LLM request.
  - A draft with fewer Visuals than Script Segments is accepted with narration-derived Visuals for the uncovered segments.
- **Related:** CF-REQ-153, CF-REQ-251, CF-REQ-256, CF-REQ-263

### CF-REQ-251 — Asset requirements

- **Description:** Each Visual Segment shall contain an `AssetRequirement`
  with media type, category, description, subjects, tags and strategy.
- **Behaviour:** Strategy defaults to `reuse_first`; `generate_allowed` may be
  set only when the profile allows generated media (CF-REQ-208) and never when
  `subjects` include a real, identifiable person (forced to `acquire_only`,
  CF-REQ-215). For typed graphics, `subjects` means entities depicted by the
  rendered visual; a Claim-backed person's name used as text is not a
  depiction subject and never authorizes a portrait/avatar or other likeness.
- **Acceptance:**
  - With `allow_generated_media = false`, a plan containing `generate_allowed` fails schema/business validation and is repaired.
  - A segment whose subjects include a named person is normalised to `acquire_only` by code.
  - A typed `infographic`/`scientific` segment (whose only meaning is a
    local template render) is normalised to `generate_allowed` by code when
    the profile allows generated media and no named person is a depiction
    subject; otherwise the writer's strategy is kept (Run 23a209d7 failed
    because a timeline infographic was labelled `reuse_first`).
  - A `media` segment whose description, queries or tags ask for a calendar
    or date depiction, whose narration names a month, and for which an
    accepted Claim cited by that segment (else any accepted Claim) contains a
    matching date expression verbatim (for example "January 1", "1 January",
    "Jan. 1, 2027"), is converted by code into a `key_date` infographic
    grounded on that Claim when generated media is allowed; otherwise the
    media requirement is kept. Stock calendars cannot show the narrated date
    reliably (owner review of Run d519e520: a "May 1st" calendar illustrated
    "January first").

### CF-REQ-252 — Deterministic motion

- **Description:** Motion values (`zoom_in`, `zoom_out`, `pan_*`, `ken_burns`)
  shall be rendered by parameterised FFmpeg filters with fixed formulas; the
  same inputs produce the same filter graph.
- **Acceptance:**
  - Unit tests assert the exact filter expression generated for each motion value for a 5 s segment at 30 FPS.
  - No provider is called to create motion.
- **Related:** CF-REQ-353, ADR-013

### CF-REQ-253 — Motion defaults

- **Description:** Motion is selected for each shot from its actual media and subject framing, not from a Clip-wide effects recipe. Owner direction (2026-10-07): still images shall not sit frozen on screen. Video Assets keep their native motion. An explicit pan or zoom from the writing draft is preserved with its reason. Otherwise code assigns each still a slow move: wide stills alternate zooms and horizontal pans, tall stills alternate zooms and vertical pans, and text cards, maps, charts and diagrams receive only a gentle zoom so they stay readable. A shot never repeats the move of either of the two preceding moving shots when an alternative exists; a continuation of the same image within one Script Segment reverses the previous move instead of restarting it. The chosen move and its reason are recorded on the Visual Segment. `motion_intensity`
  scales zoom amount: low 1.05×, medium 1.10×, high 1.20× over the segment.
- **Acceptance:**
  - Every still image receives a non-`none` move; video keeps `none` unless explicitly requested; a text card gets only `zoom_in` or `zoom_out`; three consecutive stills never share one move; an explicit scripted pan is preserved; a same-image continuation reverses the prior move.

### CF-REQ-254 — Transitions

- **Description:** Transitions shall be one of `cut`, `crossfade`,
  `fade_black`, `slide_left`, `slide_up`, rendered with FFmpeg (`xfade`) and
  lasting `composition.transition_seconds` (except `cut`). Segment 0 uses `cut`.
- **Acceptance:**
  - Total Clip duration is unaffected by transitions (overlap compensated), verified by probe.

### CF-REQ-255 — Frame fitting

- **Description:** Assets shall be fitted to the output frame deterministically:
  sources with aspect ratio (w/h) < 1.0 are scaled and centre-cropped to cover
  the frame; sources with w/h ≥ 1.0 are fitted inside the frame over a blurred,
  darkened, cover-scaled copy of themselves (`fit_blur`).
  Owner revision (2026-10-14): verified person stills with a confidently
  detected dominant face use a face-safe crop, without changing the information
  banner. Owner feedback refinement (2026-10-14): prefer edge-to-edge sharp
  imagery rather than an inset photo with visible rectangular side margins.
  Place the face in the upper-middle area below the active banner, retaining
  headroom and limiting face enlargement. Use blurred padding only where a
  full-cover crop cannot preserve those bounds, blending the sharp photo's
  top/bottom edges into that padding without fading the face. Portrait shots remain still
  rather than forcibly zooming/panning a face toward the exact frame centre.
  Local detection is positioning evidence only, never identity verification.
  Detection evidence is bound to the source hash and retained for Retry and
  saved rendering. Owner correction (2026-10-15): missing or ambiguous
  detection fits the complete sharp portrait below the unchanged active banner
  over blurred padding, without motion, rather than allowing a centre crop to
  hide the subject. Emit a visible framing-unavailable warning; do not invent
  face bounds or identity evidence.
- **Acceptance:**
  - A 1920×1080 photo produces a 720×1280 frame whose central 720×405 band contains the whole photo.
  - Portrait fixtures of landscape, square/9:16 and tall shapes retain the
    complete face below the unchanged active top banner, with headroom and
    face height at most 32% of output height. Sources that permit a safe
    cover crop show no blurred margins. A replaced source cannot reuse old
    face bounds; the framing revision participates in the composition hash.
  - With unavailable detection, the entire portrait remains below the active
    banner at both the start and end of the shot.
- **Related:** OD-012, ADR-020

### CF-REQ-256 — Timing reconciliation

- **Description:** After captions are built, each Visual Segment's
  `start_seconds`/`end_seconds` shall be set from the word timings of its
  Script Segment (split segments share the Script Segment's span
  proportionally to planned durations). The first segment starts at 0 and
  includes `lead_in_seconds`; the last ends at Clip end including `tail_seconds`;
  there are no gaps. When a reconciled span longer than
  `visual.max_segment_seconds` is split into pieces that share one video
  Asset, each piece records a `source_offset_seconds` equal to the time already
  shown by earlier pieces, so the pieces play consecutive, non-overlapping
  spans of the footage. A video Asset is never restarted from its beginning
  to fill time, including when a Retry reconciles an already-split plan.
  Reconciliation preserves the total planned weight and cumulative source
  offsets of split pieces, and resets offsets only for a different selected
  Asset. Media selection prefers video candidates whose duration covers
  the segment's planned duration plus 2 s (plus `tail_seconds` for the last
  segment) over shorter ones, keeping review order otherwise.
- **Failure:** A video Asset shorter than its segment (measured from its
  `source_offset_seconds`) is extended by holding its last frame for at most
  1.0 s; beyond that, the compose gate issues `asset_too_short` with the
  planned segment index, routing to `reselect_asset` for that segment, which
  excludes the short Asset and complements the footage with a longer one.
- **Acceptance:**
  - Segment boundaries are contiguous and cover `[0, clip_duration]`.
  - Split pieces of one video Visual Segment have increasing, non-overlapping
    source offsets; no piece replays footage shown by an earlier piece
    (Runs 770c59d5 and d519e520 replayed the first ~4 s of a stock video).
  - A video Asset too short to cover its piece from its offset (beyond the
    1.0 s hold) never reaches FFmpeg; `asset_too_short` is raised instead.
  - Reconciling a retained split plan twice preserves timings and consecutive
    source offsets; the penalty footage in Clip `274efcf3` must not replay
    from offset zero on its second piece.
- **Related:** CF-REQ-311, CF-REQ-404

### CF-REQ-257 — Plan gate

- **Description:** Before composition, a deterministic gate shall verify that
  every Visual Segment has a selected, `active`, available Asset, and that
  each reconciled duration is within
  `[visual.min_segment_seconds, visual.max_segment_seconds]`.
  Timing reconciliation first lengthens a piece shorter than
  `visual.min_segment_seconds` by moving its boundary with the longer adjacent
  piece, provided that neighbour keeps at least the minimum (live Run 59a3af59
  failed its last attempt because "Abbas Araghchi earlier today." was spoken
  in 1.19 s); only a piece that cannot be lengthened this way raises
  `segment_too_short`.
- **Failure:** Issues `missing_asset`, `segment_too_short`,
  `segment_too_long` route to `select_assets` or `plan_visuals`.
- **Acceptance:**
  - A plan with one segment lacking an Asset never reaches `compose_clip`.
  - A 1.2 s piece between a 2.7 s and a 5.6 s piece is reconciled to 1.5 s
    by borrowing from the 5.6 s piece; boundaries stay contiguous.
- **Related:** CF-REQ-410

Saved re-render remains subject to source availability: retired or deleted
external inputs under CF-REQ-214 fail the existing saved-visual validation
instead of being silently reused. This does not affect the composed Clip.

### CF-REQ-258 — Beat-aware Shot Intent

- **Description:** Each Visual Segment shall record the Narrative Beat it supports, Shot Intent, requested shot type, accepted Claim references, timing anchors and whether its media is current event footage, archive/location context, illustrative media or a geographic/data graphic.
- **Behaviour:** Shots support explanation and evidence, not merely keyword decoration. A shot change, hold or transition has a recorded editorial reason. The existing writing request provides the draft; deterministic planning validates coverage and normalizes timing without another request. Source dates and uncertainty shall not be disguised by editing.
- **Acceptance:** Every segment maps to a beat in narration order; an archive location photograph cannot be labelled footage of the reported event; splitting an oversized narration span preserves intent and references.
- **Related:** CF-REQ-163, CF-REQ-250, CF-REQ-256

### CF-REQ-259 — Grounded Editorial Overlays

- **Description:** The Visual Plan shall support timed Editorial Overlays distinct from spoken-word captions: headline, person name/role, location/date, Source publisher, attributed quote, supported key number and archive/illustrative disclosure.
- **Behaviour:** Each Overlay Cue records its displayed shot, content, source/Claim or metadata reference, start/end anchors, visual hierarchy and style/template version. Names, roles, places, dates, quotes and numbers must be supported by the Story Package or verified Asset provenance. Source publisher labels and media-author credits remain distinct. Mandatory licence attribution and disclosure are never removed for aesthetics.
- **Failure:** Unsupported overlay facts produce blocking `unsupported_statement`; missing required attribution produces `attribution_missing`. Unknown references are repaired or held for review, never guessed.
- **Run composition (owner request):** In a normal Run the top editorial panel shows context summaries only (`headline`, `place`, `number`, `quote` cues); `source` and `person` cues are not shown there, because spoken attribution and verified portraits already carry them. For each Script Segment the panel uses that segment's first context cue, otherwise the segment's Claim-grounded buzz line (CF-REQ-269) as a `headline`. Each label starts at its segment start (the first at Clip start) and stays until the next label replaces it or the story ends, so the panel is continuously visible until the branded ending. A label that cannot be rendered or read in its window is skipped and the previous label extends over it. The licensed information sound cue (CF-REQ-324) plays at every label change.
- **Acceptance:** A factual label with an unknown Claim fails; a Source badge uses the cited publisher rather than the stock-media provider; subtitle changes do not change an independently timed person label.
  - Run panel labels exclude `source`/`person` cues, fall back to buzz lines per segment, cover Clip start to story end without gaps or overlap, and each change has one sound cue.
  - Owner revision (2026-10-14): primary text in top editorial panels is
    always rendered uppercase, independent of cue kind or input casing.
    Wrapping and safe-width validation use that displayed uppercase text.
    Secondary text, context-placement labels, captions and stored evidence
    retain their original casing. Normal Runs and saved rendering share this rule.
- **Related:** CF-REQ-161, CF-REQ-203, CF-REQ-269, CF-REQ-324, CF-REQ-406

### CF-REQ-260 — Verified identity and Shot Anchors

- **Description:** A person name near an image shall require a verified binding between that identity and the displayed Asset.
- **Behaviour:** Identity evidence records the authoritative source or owner confirmation; a filename, face similarity, search ranking or model guess alone is insufficient. Shot Anchors use validated normalized regions transformed through actual fitting/cropping. If precise placement is unavailable, use a safe lower third without implying an unverified face binding. Labels must not obscure a face or falsely assign one person's name to another.
- **Failure:** Unverified identity remains pending review; incorrect identity blocks the render's approval.
- **Acceptance:** A fixture with two people cannot interchange their labels; moving/cropping an image transforms its anchor correctly; an unverified portrait never receives an automatic named-person label.
- **Related:** CF-REQ-215, CF-REQ-255, CF-REQ-259

### CF-REQ-261 — Overlay layout and readable animation

- **Description:** Overlay layout shall use measured fonts, explicit layer ordering and the configured platform-safe zones, avoiding subtitles, other overlays, platform controls and protected subject regions.
- **Behaviour:** Contrast is at least 4.5:1. Dwell is at least the greater of `overlays.min_dwell_seconds` and word count divided by `overlays.reading_words_per_second`. Deterministic reflow, relocation or shortening that preserves meaning precedes failure. Entrance/exit animation cannot consume required readable dwell. If the shot cannot accommodate the label, extend/replan within duration bounds or request review; never silently omit essential information.
- **Failure:** Unresolvable geometry/readability produces blocking `caption_quality` with `refs.layer = editorial_overlay` and the cue ID.
- **Acceptance:** Long-name fixtures fit or block; every cue is tested against subtitle and platform-control rectangles for all four platforms; a two-second label with a one-second reveal fails when insufficient readable dwell remains.
- **Related:** CF-REQ-313, CF-REQ-314, CF-REQ-259

### CF-REQ-262 — Purposeful deterministic motion and transitions

- **Description:** The renderer shall support versioned, deterministic keyframe/preset motion for restrained pan, zoom, reframe, label reveals and evidence-backed map/number emphasis.
- **Behaviour:** Cuts are the default. Crossfades, fades and slides are selective, motivated by topic, time, location or viewpoint changes; there is no quota requiring effects on every cut. Keyframes record start/end state, duration and supported easing. Preserve subject framing, reading time and narration continuity; avoid rapid flashes or distracting repeated zooms. Sensitive-story policy suppresses playful/aggressive effects. Generation providers are not used to render basic motion.
- **Acceptance:** Identical plans yield identical motion/filter expressions; all supported transitions preserve video-stream duration within one frame; a static map passes; invalid/out-of-span keyframes fail before FFmpeg.
- **Related:** CF-REQ-252–256, CF-REQ-355, CF-REQ-357

### CF-REQ-263 — Typed, grounded graphics drafts

- **Description:** The existing `write_script` request shall return a typed
  visual draft for each segment, with `kind` equal to `media`, `infographic`
  or `scientific`. A missing `kind` in a retained/legacy draft defaults to
  `media`. A supported template determines its graphics family, so code
  deterministically normalizes a mislabelled draft without an LLM call:
  a non-media `kind` paired with the other family's template takes the
  template's family (`statistic`, `comparison`, `timeline`, `key_date` → `infographic`;
  `function_plot`, `relationship_diagram` → `scientific`), and a `media`
  draft carrying a primary `graphics_spec` but no fallback keeps the media
  route and treats that spec as its declared `fallback_graphics_spec`
  (live Run 829f7db4 failed solely on such a mislabel). A non-media `kind`
  without a primary `graphics_spec` has nothing to render, so code treats it
  as a `media` visual (keeping any declared fallback). A non-media draft with
  a primary spec that also declares a fallback keeps the primary and drops
  the redundant fallback. Neither normalization adds or changes graphics
  content (live Run a50af45d failed outright on such a draft). An unsupported
  template still fails with `unsupported_graphics_template`.
- **Behaviour:** The optional graphics payload is declarative, schema-validated
  data, never executable content. The first supported infographic templates
  are `statistic`, `comparison`, `timeline` and `key_date` (one grounded
  date shown as a calendar card with an optional grounded caption); the
  first scientific templates
  are a bounded `function_plot` and a `relationship_diagram`. Each displayed
  factual label/value/text carries one or more IDs of accepted Claims and is
  checked against their verifiable text. Names, dates and numeric values must
  match normalized text in the accepted Claim/evidence; a Claim ID alone does
  not authorize new facts or paraphrases. Comparison has 2–6 items and
  timeline has 2–8 events; relationship diagrams have 2–12 nodes and at most
  20 edges. Numeric values are finite and bounded to magnitude `10^15`.
  Function plots use only `linear`, `quadratic`, `sine` or `cosine` from a
  finite code-defined enum, finite coefficients bounded to magnitude `1000`
  and an x-domain within `[-100, 100]`. Their fixed definitions are
  `linear: y=a*x+b`, `quadratic: y=a*x^2+b*x+c`,
  `sine: y=a*sin(b*x+c)`, and `cosine: y=a*cos(b*x+c)`; code samples each
  with 256 evenly spaced samples. They represent the declared mathematical
  function, not empirical scientific observations.
  Relationship nodes/edges and all scientific observations use accepted Claim
  references; edge endpoints must refer to declared nodes. A map is supported only when the payload identifies verified,
  versioned geographic geometry by Asset ID; generated coordinates,
  boundaries and locations are forbidden. Unsupported template kinds fail
  validation with `unsupported_graphics_template`, without inventing a
  substitute.
- **Failure:** Unsupported template IDs produce blocking
  `unsupported_graphics_template`; missing/invalid Claim support produces
  blocking `unsupported_statement`; local renderer failures produce
  `graphics_render_failed`. These are not repaired by an LLM call or
  substituted with another rendering/media route. When the missing Claim
  support is detected in the `write_script` response itself, it is a blocking
  `write_script` stage-gate issue (routed per the retry table to a full rewrite
  that names the offending visual) consuming the Run's bounded revision retry
  budget, rather than an immediate Run failure; the ungrounded payload is never
  patched or rendered (live Run 67f69cb4 failed outright on a truncated
  statistic label). The same routing applies when the `write_script` response
  fails typed graphics validation with `unsupported_statement` (for example a
  label rejected as markup): the response is discarded and the rewrite names
  the offending field (live Run 1fb93594 failed outright on a statistic
  title). An unsupported template remains an immediate
  `unsupported_graphics_template` failure.
- **Safety:** The payload cannot contain HTML, SVG, Python, JavaScript,
  arbitrary formulas/code, an executable, or a URL. Labels reject markup and
  code characters (`< > { } \` \\ ; |`), line breaks, URLs and call syntax;
  ordinary factual characters such as currency symbols (`$`, `€`, `₹`) and
  `&` ("AT&T") are allowed because trusted templates HTML-escape every
  label. Model-authored markup or
  code is never passed to a renderer. Templates are trusted, bounded
  implementations selected by an enum. No extra LLM call or loop is added;
  the payload is part of the existing structured `write_script` response.
- **Acceptance:**
  - A legacy draft without `kind` validates as `media`.
  - A statistic, comparison, timeline, key date, bounded function plot and
    Claim-grounded relationship diagram render from valid typed fixtures.
  - Unknown Claim IDs, ungrounded factual text, out-of-bound numeric input,
    arbitrary code/markup/URLs and unsupported templates fail before renderer
    invocation.
  - A function plot fixture is reproducible from its enum/domain and cannot
    accept source code or be presented as measured scientific data.
  - A map without verified geometry is rejected; no geometry is inferred.
- **Related:** CF-REQ-153, CF-REQ-250, CF-REQ-258–259, CF-REQ-215, ADR-019

### CF-REQ-264 — Explicit graphics renderer routing

- **Description:** `select_assets` shall route typed graphics by their
  `VisualPlan` kind to a named local renderer: `infographic` to HyperFrames
  and `scientific` to Manim. `media` continues through the existing
  reuse/acquisition and permitted ImageProvider/VideoProvider generation
  path, including its existing Wan rules.
- **Behaviour:** Graphics routing is explicit code selection and does not
  inspect or follow the Content Profile's `image_providers` or
  `video_providers` order. Graphics use the existing `VideoProvider` request
  with an optional provider-neutral typed graphics specification; no new
  provider port is introduced. The profile's `allow_generated_media` and
  `generate_allowed` permission are required before rendering a new graphics
  Asset. Templates do not create portraits, avatars or other depictions of
  identifiable people; Claim-backed names appear only as text labels. An
  infographic/scientific Visual Segment requests a video Asset, categorized
  `graphic` or `chart` according to the typed template. An exact eligible
  reusable Asset may be reused under the existing
  Asset safeguards. Graphics render failures remain explicit
  `graphics_render_failed`, `unsupported_graphics_template` or
  `unsupported_statement` as applicable;
  they do not fall back to Wan, another generation provider, SVG authoring,
  an FFmpeg-authored graphic, or a placeholder.
- **Acceptance:**
  - Infographic fixtures select only HyperFrames; scientific fixtures select
    only Manim, regardless of provider-list ordering.
  - Media fixtures retain the acquire/Wan route subject to CF-REQ-266.
  - With generated-media permission disabled, no graphics renderer is called.
  - A renderer failure is visible and does not invoke Wan or another adapter.
  - Missing local renderer configuration fails with an actionable explicit
    error; it is not represented as a successful or mock-rendered Asset.
- **Related:** CF-REQ-208, CF-REQ-251, CF-REQ-263, [provider architecture](architecture/provider-architecture.md), ADR-013, ADR-019

### CF-REQ-265 — Safe local graphics render lifecycle

- **Description:** Local graphics outputs shall be produced as video Assets
  by the selected trusted adapter, then pass the existing media validation,
  provenance, import, content-addressed storage and reuse safeguards.
- **Behaviour:** A graphics Asset records rendered provenance identifying
  the renderer, template ID/version and normalized structured input/Claim
  references, with the existing non-empty licence/attribution metadata for
  the renderer/template resources; rendered output is a video at the Content
  Profile output dimensions, `graphics_fps`, and the Visual Segment's planned
  duration. It is reusable only after successful validation/import. Renderer
  subprocesses use configured executable paths and argument arrays (never a
  shell), isolated per-Run/Visual working paths, bounded output/timeout and
  cancellation scoped to the specific child process IDs. Active-render
  watchdog renewal uses the existing silent heartbeat mechanism; watchdog
  heartbeats are not persisted Run Events. Cancellation terminates and reaps
  only the owned renderer subprocess within the configured bound. A valid
  completed Asset is retained by the normal import safeguards even if the
  Run later fails; incomplete/invalid output is not selectable. No graphics
  output can publish or bypass final validation, review or approval.
- **Reuse before render:** Before rendering, select_assets reuses an
  active Asset with the same renderer template/version, normalized graphics
  input, `graphics_fps` and output dimensions when its duration matches the
  planned duration within one frame, or when it is longer and its template's
  bounded entrance animation completes at least 1.0 s before the planned
  duration (composition trims the static tail). Fixed-entrance templates
  (`key_date`: 1.1 s) qualify at any longer duration; duration-scaled
  infographic entrances (statistic, comparison, timeline: up to 0.8 × the
  rendered duration, capped at 0.4 × duration + 1.5 s) qualify only within
  that bound; Manim templates require the one-frame match. A revision retry
  that shortens a graphic segment therefore never renders a duplicate of the
  same card (two identical `key_date` "November 29" Assets, 4.0 s and 2.8 s,
  were rendered in one Run on 2026-10-11).
- **One graphic per Script Segment:** When pacing splits a graphic Script
  Segment into several Visual Segments, only one of them carries the
  graphics spec: the piece whose narration speaks one of the spec's text
  values (for example the date), otherwise the first piece that is not a
  person mention. When the text is spoken only inside a person-mention piece
  (which keeps the portrait), no piece carries the graphic, because showing it
  on an earlier piece would display the card seconds before its date or number
  is heard (Run 8499ba37 showed "October 16" over "Federal Reserve Board
  Chairman" ~10 s before Georgieva's portrait piece spoke the date). The other
  pieces become narration-keyed stock footage
  (`kind = media`, `category = broll`, `reuse_first`). Identical
  deterministic specs render byte-identical output, so repeating the spec
  would show the same card several times and the duplicate import would fail
  the Run (Run f9939b84 failed with `graphics_render_failed` after one
  "1 December 2025" `key_date` segment was split into three pieces). The same
  applies to a media Script Segment's `fallback_graphics_spec`: only the
  anchor piece keeps the fallback graphic and the other pieces become
  narration-keyed footage without one (live Run 8e100c34 failed with
  `graphics_render_failed` after both pieces of a media segment fell back to
  the same "Monday" `key_date` card). A person piece's portrait fallback
  follows the same rule: unless it is the anchor it holds narration-keyed
  footage (or its media search without the fallback graphic), never a second
  copy of the card. If a render nevertheless imports as an Asset already shown
  in the Clip, `select_assets` records a blocking `generation_duplicate` gate
  issue (not the generic `graphics_render_failed`, which remains for actual
  renderer/validation failures) routed to `replan_visuals` for that Visual
  only (CF-REQ-410, 11-evaluation-and-retry). The override is kept in the
  saved plan for the same frozen Script, including when a mixed
  `replan_visuals` retry rebuilds it, and unchanged Visuals keep their
  selections (CF-REQ-412).
- **Progress:** Run progress may report `generation_phase = rendering` and
  `progress_fraction` only when measured from actual rendered-frame counts.
  Unknown progress is indeterminate; watchdog heartbeats never advance the UI
  percentage.
- **Acceptance:**
  - A key_date Script Segment split into three Visual Segments yields one
    graphic, on the piece speaking the date, and two distinct footage pieces.
  - A media Script Segment with a `key_date` fallback graphics spec split into
    two pieces keeps the fallback on one piece only.
  - A key_date Script Segment whose date is spoken only inside a person piece
    yields no graphic piece: the person piece keeps the portrait and the other
    pieces are footage.
  - No person piece's portrait fallback repeats the Script Segment's graphic.
  - A repeated render yields `generation_duplicate` and a targeted
    `replan_visuals` retry, not a terminal `graphics_render_failed`.
  - Real local HyperFrames and Manim integration fixtures are each probed,
    fully decoded and imported as reusable video Assets with
    renderer/template provenance.
  - Import failure retains recovery output/metadata under the existing
    generated-media recovery policy and does not activate the Asset.
  - Cancellation kills/reaps only the matching renderer child process within
    the configured bound; unrelated subprocesses remain alive.
  - A long render with silent watchdog heartbeats can continue beyond the
    initial stage deadline; a stalled render times out and is terminated.
  - UI progress is indeterminate until actual frame measurements exist and
    never displays a fabricated percentage.
  - A retry that shortens a `key_date` segment reuses the existing longer
    render of the identical card instead of rendering a second Asset; a
    longer duration-scaled infographic whose entrance would still be
    animating near the planned end is not reused.
- **Related:** CF-REQ-200–202, CF-REQ-210–211, CF-REQ-604, CF-REQ-656, CF-REQ-850, ADR-019

### CF-REQ-266 — Bounded Wan generation and grounded alternatives

- **Description:** Native Wan generation shall be limited by the adjustable
  `environment.wan_max_generations_per_run`, default 2, range 0–100.
  Zero disables new Wan generation, not reuse of existing Wan Assets.
- **Behaviour:** Count actual generation starts, including failed/cancelled
  calls, durably for the Run ID across revision retries, restart and Continue.
  Reserve each allowance before calling Wan; a skipped/unconfigured provider
  consumes none. Existing persisted Wan start events count toward the cap.
  Lowering the setting below past usage prevents further calls; raising it
  permits only the newly available allowance. Other renderers do not consume
  the Wan allowance. At the cap no additional Wan call or model load occurs.
- **Fallback:** After normal reuse/acquisition fails and Wan is unavailable,
  exhausted or fails, use a suitable bounded, accepted-Claim-grounded graphics
  fallback declared in the existing writing response: infographic templates
  route to HyperFrames, mathematical/scientific templates to Manim. If there
  is no suitable graphics fallback, search configured free media sources with
  up to two distinct refined queries (declared by the writing response or
  derived deterministically from the existing subjects/tags; when the draft
  declares none of these, from the Visual Segment's own narration content
  words without the leading publisher credit). Declared queries come first
  and any remaining slot is filled from the subjects/tags, then from each
  declared query with its capitalized proper nouns removed when at least two
  words remain (for example "Nebraska political rally crowd" also yields
  "political rally crowd", because free catalogues rarely hold place-specific
  footage; live Run 95b4b7b4), and then the narration keywords, so one weak
  declared query does not leave the search one-sided. On a revision Attempt the next distinct pair of this
  deterministic list is used (rotation by Attempt), so a `reselect_asset`
  Retry searches different terms instead of repeating rejected candidates
  (live Run a935dd18). On a revision Attempt a refined search for a `video`
  Visual searches each query for both videos and still images and
  interleaves the eligible results, because free video catalogues are sparse
  and stills always receive motion (live Run 0716cfed exhausted its retries on
  video-only candidates). Retain the
  original Shot Intent and identity, licence, resolution, duplicate-content
  and candidate-review safeguards. Fallback review remains a governed LLM
  call, not an agent loop; group unresolved segments into a bounded batch.
  This adds no separate planning LLM call. A failed typed renderer remains
  explicit, never an unrelated substitute.
- **Permissions:** Generated-media permission and identifiable-person
  restrictions still apply. `acquire_only` may refine searches but never
  render graphics or invoke Wan. A `reuse_first` fallback may render only
  its explicitly declared, validated graphics alternative when generated
  media is allowed. Never fabricate a chart, scientific result, geography,
  plain-colour placeholder or event footage to fill a slot.
- **Progress/failure:** Record Wan reservation/use and cap skips in Run Events
  with current count and limit; show refined-search/graphics fallback choice.
  If all permitted alternatives fail, retain the blocking `missing_asset`
  evaluation and normal targeted Retry; never exceed the cap.
- **Unsourceable intent escalation:** When a Visual Segment is still unmet
  on an Attempt that was itself a `reselect_asset` Retry for that same
  segment, the Shot Intent is treated as unsourceable from free libraries
  (for example a "digital points table showing team numbers"; live Run
  14cc1a24 exhausted ten Attempts re-searching it). The gate then emits the
  blocking issue `unsourceable_visual` (refs: plan `segment_index`,
  `script_segment_index`) routed to `write_script` / `revise_script`, whose
  instructions name the Visual description and ask for that Script Segment's
  visual only to become an ordinary photographable scene likely in free
  stock libraries (place, crowd, building, object, activity) with fresh
  search queries, keeping narration unchanged. A further failure of the
  rewritten visual returns to `reselect_asset` first, so escalation
  alternates and stays bounded by `workflow.max_revision_retries`.
- **Acceptance:**
  - A segment that fails sourcing on a `reselect_asset` Attempt for that
    segment yields `unsourceable_visual` routed to `revise_script`; a first
    failure, or one following a different Action, yields `missing_asset`.
  - With five unmet Visuals and the default cap, at most two actual native
    Wan generation calls occur; remaining Visuals use eligible rendered or
    refined-search Assets, or fail explicitly.
  - Limits 0, 1 and an adjusted value are enforced. Failed/cancelled calls
    count; reuse/unconfigured providers do not.
  - A fresh service for the same Run, Continue and revision Retry retain
    usage, including starts recorded before this requirement was added.
  - Infographic/scientific alternatives route to their existing renderer
    without Wan; unsupported evidence and disabled permissions are rejected.
  - Refined queries differ from the original and one another, remain bounded,
    and only reviewed licensed eligible candidates are imported.
  - A single declared query is completed with a derived query, and the next
    revision Attempt uses a different distinct pair.
  - Settings round-trip the numeric limit and reject invalid values.
- **Related:** CF-REQ-207–210, CF-REQ-215, CF-REQ-218–219, CF-REQ-263–265,
  CF-REQ-653, CF-REQ-759, ADR-019

### CF-REQ-267 — Native Wan reference recipe and isolated manual test

- **Description:** Native Wan 2.1 1.3B shall use an explicit reproducible
  480p inference recipe, independently implemented without OpenMontage as a
  dependency. The owner reference is a five-second paper-boat Asset,
  832x480, 16 FPS, seed 42, produced with 50 steps. Current ClipFactory
  default inference is 25 steps. On 2026-10-08 the owner ran the recovered
  cinematic prompt at 25 steps and accepted its playback quality as matching
  the OpenMontage reference. This verifies that landscape sample, not every
  subject or production portrait shot.
- **Behaviour:** Use explicit guidance 5 and UniPC flow shift 3 for the
  configured checkpoint, the official Wan motion/quality negative prompt,
  CPU seeded noise, BF16 CUDA model weights with FP32 VAE and existing
  sequential offload/tiling. Configuration is in CF-REQ-759 environment
  settings. Bound native dimensions to a long side of 832 and short side of
  480, preserving requested orientation/aspect within 16-pixel alignment;
  Default production portrait requests (720x1280) infer at 464x832; final
  portrait fitting remains CF-REQ-255, not high-resolution denoising.
  Denoise a valid `4k+1` frame count and encode only the requested frame count
  (`round(duration * fps)`, minimum 1), so five seconds means 80 output frames,
  not 81. Encode H.264 yuv420p with explicit CRF 10 (confirmed in the reference
  bitstream) and report actual recipe,
  inference/output frame counts, scheduler and precision in provenance.
- **Prompts:** The existing writing response may carry a separate bounded
  `generation_prompt` describing concrete subject, action, environment,
  lighting and camera. Instruct the writer to supply it for each eligible
  illustrative shot, including reuse-first shots that may need generation,
  with stable subject geometry, restrained motion and framing for the Content
  Profile's output orientation. Keep search keywords separate. For legacy drafts,
  enrich the existing concrete description with a deterministic naturalistic
  moving-shot instruction. Do not prepend policy/disclosure language to
  model prompts; generated provenance/disclosure and no-person restrictions
  remain enforced outside the positive prompt. No extra LLM call.
- **Manual test:** `clipfactory wan-test` invokes only the local Wan adapter,
  never LLM/cloud providers, database migrations/connections, scheduler,
  Run resume, publication or Asset import. CLI recipe overrides are isolated
  from saved settings and Run usage. A `--dry-run` prints the complete recipe
  without model loading/download/inference. A real invocation writes an MP4
  and adjacent JSON recipe/probe manifest only after local probe and full
  decode, refuses existing output/manifest files, and surfaces errors.
  Reuse the common Wan cache; offline mode is default and missing weights
  fail explicitly. `--allow-download` explicitly permits missing weight
  download from the configured model source, never cloud inference.
- **Acceptance:**
  - Mocked inference receives guidance 5, flow shift 3, seed 42, 25 steps,
    832x480 and 81 denoised frames; encoding produces 80 frames at 16 FPS.
  - Portrait 720x1280 requests are bounded before inference and are fitted
    only during final composition; profile output dimensions are unchanged.
  - Updated runtime recipe settings reach a cached pipeline.
  - Primary/legacy generated-media prompts contain concrete shot instructions,
    not disclosure policy or raw infographic/map requests.
  - CLI dry-run has no model/media/provider/application side effects; actual
    CLI tests use fakes and assert recipe/output validation, collision and
    failure handling, and absence of operational Run/database activity.
  - Default production portrait generation uses 464x832, 16 FPS, 25 steps,
    guidance 5 and shift 3, imports the generated video with its actual recipe
    and prompt, and retains the normal quality gate.
  - Owner-approved landscape reference quality does not bypass evaluation of
    new generated Assets or establish live portrait quality.
- **Related:** CF-REQ-153, CF-REQ-208, CF-REQ-255, CF-REQ-266, CF-REQ-759

### CF-REQ-268 — Mentioned public figures shown on screen

- **Description:** Whenever narration names a real public figure, the shot
  covering that mention shall show that person through a freely licensed real
  photograph whose identity is bound by an authoritative source.
- **Behaviour:** The existing writing response lists the real people named in
  the narration (full name plus spoken mention forms); no extra LLM call.
  Because free models sometimes omit that list, the visual planning stage
  also extracts undeclared full-name candidates deterministically: runs of
  two to four capitalized words (leading titles such as "President" or
  "Governor" removed; lowercase surname particles such as "da", "de",
  "von", "der" or "van" may join them, so "Luiz Inacio Lula da Silva" and
  "Ursula von der Leyen" stay whole) from the narration and the Story's
  accepted Claims, kept only when the full name, its surname, its particle
  surname ("von der Leyen") or the word before the particle ("Lula") is
  spoken in the narration (live Run 620a25e1 said only "Lula", and the
  truncated candidate "Luiz Inacio Lula" did not resolve, so Lula was not
  shown); role titles also split a run when hyphenated or military
  ("Secretary-General", "Major General", "spokesman"), lowercase Arabic
  article prefixes such as "al-" stay part of the surname ("Turki al-Malki"),
  and runs containing an institution noun ("Airport", "International",
  "Party", "University", …) are not candidates; a candidate that is only the
  tail of a longer candidate is dropped, at most eight per Run, most-mentioned
  first and, at equal mentions, names directly after a role title first (live
  Run afbd9e62 named Antonio Guterres and President Trump, but the candidate
  "UN Secretary-General Antonio Guterres" did not resolve and Trump was
  ranked below place names past the eight-candidate limit, so neither was
  shown). Each candidate is kept only if
  the same Wikidata identity resolution below finds a human with a portrait;
  single capitalized words are never candidates on their own, so a place
  such as "Washington" cannot become a person (live Run 966e7594 omitted
  Donald Trump and Karen Bass from the list). A bare surname is a candidate
  only in a role or government context: directly after a role title
  ("President Trump", "Prime Minister Starmer") or directly before
  administration/government/presidency/campaign/cabinet/regime ("the Trump
  administration", unless another capitalized word precedes it, e.g. "White
  House administration"), and only when no full-name candidate already ends
  with it (live Run 0cd96d08 said only "the Trump administration" and
  "Trump's", so Trump was not shown). A bare surname resolves through
  Wikidata full-text search restricted to humans (`haswbstatement:P31=Q5`)
  merged with the prefix search, because prefix search alone returned an
  obscure namesake ("Starmer" → William T. Starmer). It is accepted only when
  the most widely linked matching bearer has at least 20 sitelinks and at
  least twice the sitelinks of the next matching entity; otherwise it is
  unresolved (missing a portrait is preferred over showing the wrong person).
  A person declared by the writing response with a single-word name is first
  expanded to the one full name (2–4 capitalized words) in the accepted
  Claims or their evidence excerpts that ends with that word, keeping the
  bare word as a spoken mention; with zero or several such full names the
  declaration is unchanged (live Run 4c29a773 declared "Tarar" while the
  evidence named "Azam Nazeer Tarar", and the surname-only portrait search
  failed). Deterministic code matches mentions as whole words, case-insensitively,
  allowing possessives, and splits the affected Visual Segment at the mention so
  each piece keeps at least three words. A person's piece ends with the
  sentence that names them when at least eight more words follow before the
  next mention or the end of the Script Segment; that remainder returns to
  narration-keyed footage and a later mention shows the person again (live Run
  8499ba37 held Scott Bessent's portrait for about 20 s over narration about
  other finance ministers). The portrait itself covers at most the first 14
  spoken words of a person's piece (about 5–6 s); when at least three words
  remain, the rest of that piece shows the Script Segment's own planned
  visual (narration-keyed footage for graphic segments), and a person piece
  that directly follows a portrait of the same person likewise shows that
  visual instead of the portrait again (live Run c7b99ffb held Andy
  Burnham's portrait for about 11 s and 14 s over single long sentences).
  Identity resolution uses Wikidata: the
  chosen entity must be a human (P31 = Q5) whose label or alias matches the
  name (labels and aliases in English or the language-neutral `mul`, which
  Wikidata uses for many names, e.g. "Abdul El-Sayed"), ranking an exact label
  match above an exact alias match and then preferring the most widely
  linked entity (live Run 0b566a75 resolved "Mike Rogers" of Michigan to the
  alias-matched Mike D. Rogers of Alabama); non-breaking and other Unicode
  hyphens in narration and Claims ("El‑Sayed") are treated as ASCII hyphens
  for candidate extraction and mention matching; its image (P18) is fetched
  from Wikimedia Commons and retained only with an accepted reusable licence
  (CC BY/BY-SA/CC0/public domain, or the UK Open Government Licence v3,
  which is attribution-only and CC BY 4.0-compatible and covers official UK
  ministerial portraits; live Run 03ff57af named Andy Burnham five times but
  his only portrait is OGL 3, so none was shown). A portrait's short side must
  be at least `assets.min_portrait_short_side_px` (default 480) rather than
  the general image minimum, because a Wikidata P18 portrait is often a
  crop (live Run 63197c85 rejected Ryan Gravenberch's 589 × 786 portrait).
  P18 files below that minimum are discarded before import; when none
  remain, Commons files whose structured data depicts the person
  (`haswbstatement:P180=<item>`, bitmap only) are used instead, keeping only
  files whose title contains every token of the person's label, preferring
  upright framing and filtering by the same minimum and licence rules (live
  Run 48c3524d named Sarah Hanson-Young repeatedly but her only P18 files
  were 178 × 207). The Wikidata item is the identity evidence
  (CF-REQ-260); vision review is not required for such portraits. Portraits are
  reusable within a Run without cooldown and rotate when several exist. If the
  person has no freely licensed portrait, or the name does not resolve to a
  human, the shot falls back to the original visual requirement (plain text
  cards remain prohibited; e.g. Katie Zacharia currently has no Commons
  portrait). People are never
  generated (CF-REQ-215) and no automatic name label is drawn on the portrait.
- **Failure:** Transient Wikidata/Commons errors (HTTP 408, 429, 5xx, network)
  are retried up to four attempts with doubling backoff (3 s, 6 s, 12 s); lookup
  errors that remain degrade to the fallback requirement, are logged with the
  candidate name, and never substitute another person's image (live Run
  90f0f2d4 lost "Donald Trump" to a short-lived throttling burst).
- **Acceptance:**
  - A mention of "Trump" in narration produces a person shot bound to the
    human Wikidata entity, not a same-name non-notable entity.
  - A surname mention ("Zelensky") matches the declared full name.
  - A declared "Tarar" with evidence naming "the law minister, Azam Nazeer
    Tarar" becomes "Azam Nazeer Tarar" with the mention "Tarar"; two
    different full names ending in the word leave it unchanged.
  - "The Trump administration" with no full name anywhere yields the
    candidate "Trump", resolved to the dominant human bearer; "Starmer"
    resolves to Keir Starmer via full-text search; a surname with two
    comparably linked bearers ("Smith") or only obscure bearers is
    unresolved; "White House administration" yields no candidate.
  - "UN Secretary-General Antonio Guterres", "Major General Turki al-Malki"
    and "President Trump" next to "King Khalid International Airport" yield
    the candidates "Antonio Guterres", "Turki al-Malki" and "Trump", and no
    airport candidate.
  - An undeclared full name found in narration or a Claim and verified as a
    human is added; places, single words and unverified names are not.
  - A Claim naming "Luiz Inacio Lula da Silva" with narration saying only
    "Lula" yields the full-name candidate, and "Lula" mentions show him.
  - A human without a licensed portrait, a non-human or an unresolved name
    keeps the original requirement.
  - Mentions are not matched inside other words; splitting preserves
    contiguous narration coverage.
- **Related:** CF-REQ-215, CF-REQ-255, CF-REQ-259, CF-REQ-260

### CF-REQ-269 — Persistent Claim-grounded buzz line

- **Description:** Every Clip shall keep a short, punchy, Claim-grounded
  context line on screen throughout the story so viewers keep the context
  (e.g. "Zelensky disagrees with Trump's decision!").
- **Behaviour:** The writing response carries up to eight buzz lines, each
  bound to a segment index and accepted Claim IDs, at most 48 characters and 8
  words. Code drops lines with unknown Claims/segments and
  keeps one per segment, logging why any line was dropped. When fewer than two
  grounded lines survive for a Script with at least two segments (owner
  decision 2026-10-11: one weak label must not cover the whole story), one
  bounded structured repair call asks for buzz lines only, given the segment
  narration, the accepted Claims and the drop reasons; its lines pass the same
  normalization and only fill segments without a kept line. A failed or
  invalid repair is non-fatal and keeps the existing lines. When no line starts
  at segment 0, the social title bound to segment 0's Claims is used: whole if
  it fits, else its leading clause (before `:`, ` - `, ` – `, ` | `) if that
  clause has at least two words and fits, else truncated at a word boundary.
  Buzz lines are shown in the top editorial context panel (CF-REQ-259) for
  segments without their own context cue; a separate mid-screen buzz banner is
  no longer rendered (owner request, superseding the earlier lower-third
  banner). Buzz lines are evidence-bound (CF-REQ-164): emphatic wording is
  allowed, unsupported facts are not.
- **Acceptance:**
  - Unknown Claim IDs or segments are dropped; a missing opening line falls back
    to the grounded title.
  - A draft with fewer than two grounded lines triggers exactly one buzz-line
    repair; repaired lines never replace kept ones, and a repair failure keeps
    the title fallback.
  - A segment without a context cue shows its buzz line in the top panel; no
    mid-screen banner overlay is produced.
  - Saved re-renders replay any recorded buzz overlay timing from older Clips.
- **Related:** CF-REQ-164, CF-REQ-261, CF-REQ-360
