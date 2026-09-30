# 08 — Visual Production

Covers stage `plan_visuals` and the visual rules used by `select_assets` and
`compose_clip`. Entities: `VisualPlan`, `VisualSegment`, `AssetRequirement`
in [04-domain-model.md](04-domain-model.md).

**Rule:** basic motion (pan, zoom, crop, Ken Burns, transitions) is always
deterministic FFmpeg processing. AI generation is used only to create missing
*content*, never to create motion.

## Requirements

### CF-REQ-250 — Visual Plan generation

- **Description:** `plan_visuals` shall produce a Visual Plan with at least
  one Visual Segment per Script Segment, in script order.
- **Behaviour:** The visual plan draft comes from the `write_script` LLM
  request (CF-REQ-153): per segment, visual objective, asset requirement,
  motion and transition suggestions. `plan_visuals` itself is deterministic:
  it validates and normalises the draft (CF-REQ-251, CF-REQ-253), computes
  planned durations from word counts, and splits any Script Segment whose
  estimated duration exceeds `visual.max_segment_seconds`. A `replan_visuals`
  Action re-issues the `write_script` request with the script frozen; code
  verifies the script text is unchanged.
- **Acceptance:**
  - Every Visual Segment references a valid `script_segment_index`.
  - Segments appear in narration order; planned durations sum to the script's estimated duration ± 1 s.
  - `plan_visuals` makes no LLM request.
- **Related:** CF-REQ-251, CF-REQ-256

### CF-REQ-251 — Asset requirements

- **Description:** Each Visual Segment shall contain an `AssetRequirement`
  with media type, category, description, subjects, tags and strategy.
- **Behaviour:** Strategy defaults to `reuse_first`; `generate_allowed` may be
  set only when the profile allows generated media (CF-REQ-208) and never when
  `subjects` include a real, identifiable person (forced to `acquire_only`,
  CF-REQ-215).
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

- **Description:** Still images shall always have motion other than `none`
  (Ken Burns by default); video Assets default to `none`. `motion_intensity`
  scales zoom amount: low 1.05×, medium 1.10×, high 1.20× over the segment.
- **Acceptance:**
  - An image segment with `motion = none` from the LLM is normalised to `ken_burns` by code.

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
