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
  verifies the script text is unchanged.
- **Acceptance:**
  - Every Visual Segment references a valid `script_segment_index`.
  - Segments appear in narration order; planned durations sum to the script's estimated duration ± 1 s.
  - `plan_visuals` makes no LLM request.
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
- **Acceptance:**
  - A 1920×1080 photo produces a 720×1280 frame whose central 720×405 band contains the whole photo.
- **Related:** OD-012

### CF-REQ-256 — Timing reconciliation

- **Description:** After captions are built, each Visual Segment's
  `start_seconds`/`end_seconds` shall be set from the word timings of its
  Script Segment (split segments share the Script Segment's span
  proportionally to planned durations). The first segment starts at 0 and
  includes `lead_in_seconds`; the last ends at Clip end including `tail_seconds`;
  there are no gaps.
- **Failure:** A video Asset shorter than its segment is extended by holding
  its last frame for at most 1.0 s; beyond that, issue `asset_too_short`
  routes to `reselect_asset` for that segment.
- **Acceptance:**
  - Segment boundaries are contiguous and cover `[0, clip_duration]`.
- **Related:** CF-REQ-311, CF-REQ-404

### CF-REQ-257 — Plan gate

- **Description:** Before composition, a deterministic gate shall verify that
  every Visual Segment has a selected, `active`, available Asset, and that
  each reconciled duration is within
  `[visual.min_segment_seconds, visual.max_segment_seconds]`.
- **Failure:** Issues `missing_asset`, `segment_too_short`,
  `segment_too_long` route to `select_assets` or `plan_visuals`.
- **Acceptance:**
  - A plan with one segment lacking an Asset never reaches `compose_clip`.
- **Related:** CF-REQ-410

### CF-REQ-258 — Beat-aware Shot Intent

- **Description:** Each Visual Segment shall record the Narrative Beat it supports, Shot Intent, requested shot type, accepted Claim references, timing anchors and whether its media is current event footage, archive/location context, illustrative media or a geographic/data graphic.
- **Behaviour:** Shots support explanation and evidence, not merely keyword decoration. A shot change, hold or transition has a recorded editorial reason. The existing writing request provides the draft; deterministic planning validates coverage and normalizes timing without another request. Source dates and uncertainty shall not be disguised by editing.
- **Acceptance:** Every segment maps to a beat in narration order; an archive location photograph cannot be labelled footage of the reported event; splitting an oversized narration span preserves intent and references.
- **Related:** CF-REQ-163, CF-REQ-250, CF-REQ-256

### CF-REQ-259 — Grounded Editorial Overlays

- **Description:** The Visual Plan shall support timed Editorial Overlays distinct from spoken-word captions: headline, person name/role, location/date, Source publisher, attributed quote, supported key number and archive/illustrative disclosure.
- **Behaviour:** Each Overlay Cue records its displayed shot, content, source/Claim or metadata reference, start/end anchors, visual hierarchy and style/template version. Names, roles, places, dates, quotes and numbers must be supported by the Story Package or verified Asset provenance. Source publisher labels and media-author credits remain distinct. Mandatory licence attribution and disclosure are never removed for aesthetics.
- **Failure:** Unsupported overlay facts produce blocking `unsupported_statement`; missing required attribution produces `attribution_missing`. Unknown references are repaired or held for review, never guessed.
- **Acceptance:** A factual label with an unknown Claim fails; a Source badge uses the cited publisher rather than the stock-media provider; subtitle changes do not change an independently timed person label.
- **Related:** CF-REQ-161, CF-REQ-203, CF-REQ-406

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
  `media`.
- **Behaviour:** The optional graphics payload is declarative, schema-validated
  data, never executable content. The first supported infographic templates
  are `statistic`, `comparison` and `timeline`; the first scientific templates
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
  substituted with another rendering/media route.
- **Safety:** The payload cannot contain HTML, SVG, Python, JavaScript,
  arbitrary formulas/code, an executable, or a URL. Model-authored markup or
  code is never passed to a renderer. Templates are trusted, bounded
  implementations selected by an enum. No extra LLM call or loop is added;
  the payload is part of the existing structured `write_script` response.
- **Acceptance:**
  - A legacy draft without `kind` validates as `media`.
  - A statistic, comparison, timeline, bounded function plot and
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
- **Progress:** Run progress may report `generation_phase = rendering` and
  `progress_fraction` only when measured from actual rendered-frame counts.
  Unknown progress is indeterminate; watchdog heartbeats never advance the UI
  percentage.
- **Acceptance:**
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
  derived deterministically from the existing subjects/tags). Retain the
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
- **Acceptance:**
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
  - Settings round-trip the numeric limit and reject invalid values.
- **Related:** CF-REQ-207–210, CF-REQ-215, CF-REQ-218–219, CF-REQ-263–265,
  CF-REQ-653, CF-REQ-759, ADR-019
