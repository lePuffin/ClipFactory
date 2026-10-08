# 11 — Evaluation and Retry

Covers stages `validate_clip`, `evaluate_clip`, `plan_retry`, and the stage
gates. Decision: [ADR-008](decisions/ADR-008-evaluation-and-targeted-retry.md).
Diagram: [architecture/diagrams/evaluation-retry-flow.puml](architecture/diagrams/evaluation-retry-flow.puml).
Entity: `Evaluation`, `Issue`, `Action` in [04-domain-model.md](04-domain-model.md#evaluation).

## Principles

- A Clip is never published because composition succeeded. It is published
  only when it is `approved`, i.e. deterministic validation **and** semantic
  evaluation of that Clip produced no blocking issues.
- The output of evaluation is **what to change**, not a score. Scores are
  recorded as metrics only.
- Deterministic checks are code. The LLM is used only for semantic judgement.
- Routing from an issue to the stage that must be revised is a fixed code
  table (below), not an LLM decision.

## Layers

| Layer | When | Implementation |
| --- | --- | --- |
| Stage gates | End of `write_script` (CF-REQ-158), after `generate_narration` (CF-REQ-303, CF-REQ-304), start of `compose_clip` (CF-REQ-257) | Code |
| Deterministic validation | `validate_clip`, after composition | Code + FFprobe/FFmpeg |
| Semantic evaluation | `evaluate_clip`, only if deterministic validation passed | One structured LLM request with two input layers: (1) metadata/production data, always present; (2) optional sampled video frames (CF-REQ-415) — plus code post-processing |

## Issue routing table (canonical)

| Issue code | Layer | Target stage | Action type |
| --- | --- | --- | --- |
| `script_segment_count`, `hook_too_long`, `hook_ungrounded`, `segment_ungrounded`, `unknown_claim`, `missing_attribution`, `script_too_short`, `script_too_long`, `forbidden_content` | stage gate | `write_script` | `revise_script` |
| `narration_too_short`, `narration_too_long` | stage gate | `write_script` | `revise_script` |
| `narration_invalid` | stage gate | `generate_narration` | `regenerate_narration` |
| `narration_mismatch` | deterministic | `generate_narration` | `regenerate_narration` |
| `missing_asset`, `asset_too_short`, `asset_render_failed`, `asset_unavailable`, `asset_license_missing` | gate / deterministic | `select_assets` | `reselect_asset` |
| `segment_too_short`, `segment_too_long`, `visual_timing_drift` | gate / deterministic | `plan_visuals` | `replan_visuals` |
| `caption_out_of_bounds` | deterministic | `write_script` | `revise_script` (rephrase the offending text) |
| `duration_out_of_range` | deterministic | `write_script` | `revise_script` |
| `resolution_mismatch`, `aspect_ratio_mismatch`, `fps_mismatch`, `stream_missing`, `codec_mismatch`, `media_corrupt` | deterministic | `compose_clip` | `recompose` (once; repeated ⇒ `composition_defect`) |
| `metadata_invalid`, `attribution_missing` | deterministic | `write_script` | `revise_script` |
| `claim_not_supported`, `unsupported_statement` | semantic | `write_script` | `remove_claim` |
| `insufficient_grounding` | semantic | `gather_sources` | `gather_more_sources` |
| `weak_hook`, `poor_script_quality`, `editorial_quality` | semantic | `write_script` | `revise_script` |
| `visual_irrelevant`, `misleading_generated_media` | semantic | `select_assets` | `reselect_asset` |
| `poor_pacing` | semantic | `plan_visuals` | `replan_visuals` |
| `narration_quality` | semantic | `generate_narration` | `regenerate_narration` |
| `caption_quality` | semantic | — | warning only in v1.0 |
| `story_unsuitable` | semantic | — | `abort` |
| `composition_defect` | deterministic | — | `abort` |

Adding an issue code requires adding a row here.

## Requirements

### CF-REQ-400 — Evaluation result structure

- **Description:** Every gate, validation and evaluation shall produce an
  `Evaluation` with `passed`, `issues`, `warnings`, `actions`, `metrics`.
  `passed` is true iff `issues` (blocking) is empty. Every issue has a code
  from the routing table and an actionable message with measured values.
- **Acceptance:**
  - An `Evaluation` with one blocking issue has `passed = false` and ≥ 1 Action.
  - Example message: `narration is 7.0 s longer than the visual plan` with Action `replan_visuals` / `revise_script` instructions.
- **Related:** CF-REQ-407

### CF-REQ-401 — Duration validation

- **Description:** Deterministic validation shall fail a Clip whose probed
  duration is outside the profile `[min_seconds, max_seconds]` (inclusive).
- **Acceptance (defaults 60–90 s):**
  - 58 s fail; 59 s fail; 60 s pass; 63 s pass; 74 s pass; 75 s pass; 89 s pass; 90 s pass; 91 s fail; 92 s fail.
  - Changing the profile to 30–45 s makes 40 s pass and 60 s fail without code changes.
  - Validation occurs before any publication.

### CF-REQ-402 — Technical media validation

- **Description:** Deterministic validation shall verify, by FFprobe and a
  full decode pass, that the Clip: matches output width/height (issue
  `resolution_mismatch`), 9:16 display aspect (`aspect_ratio_mismatch`),
  constant FPS (`fps_mismatch`), has exactly one video and one audio stream
  (`stream_missing`), uses configured codecs (`codec_mismatch`), and decodes
  without errors (`media_corrupt`); and that every `CaptionCue` box lies in the
  safe area (`caption_out_of_bounds`).
- **Acceptance:**
  - Fixture files for each failure produce exactly the corresponding code.
  - A truncated MP4 fixture yields `media_corrupt`.

### CF-REQ-403 — Asset and metadata validation

- **Description:** Deterministic validation shall verify that every
  `AssetUsage` references an existing `active` Asset (`asset_unavailable`)
  with licence and required attribution (`asset_license_missing`,
  `attribution_missing`), and that
  social metadata satisfies CF-REQ-160 limits (`metadata_invalid`).
- **Acceptance:**
  - A Clip using an Asset with `attribution_required = true` whose attribution is absent from the description fails with `attribution_missing`.

### CF-REQ-404 — Narration and timing validation

- **Description:** Deterministic validation shall compute narration WER
  against the Script (`narration_mismatch` when > `evaluation.max_narration_wer`)
  and the drift between each Visual Segment's planned and reconciled duration
  (`visual_timing_drift` when > `evaluation.max_segment_duration_drift_seconds`
  and the segment's Asset is a video that cannot cover it).
- **Acceptance:**
  - WER 0.2 with max 0.15 ⇒ `narration_mismatch`.

### CF-REQ-405 — Semantic evaluation

- **Description:** When deterministic validation passes and
  `evaluation.semantic_enabled` is true, `evaluate_clip` shall perform exactly
  one structured LLM request (task `evaluate_clip`, model
  `LLM_MODEL_EVALUATION`) covering: factual grounding, source
  consistency, script quality, hook, visual relevance, pacing, narration,
  captions and overall editorial quality.
- **Inputs (layer 1 — metadata/production, always present):** Script with
  cited Claims and evidence, Visual Plan with Asset descriptions, tags,
  subjects and provenance, timing and WER metrics, caption layout summary,
  social metadata, deterministic validation metrics.
- **Inputs (layer 2 — visual, optional):** sampled frames per CF-REQ-415 when
  `evaluation.visual_enabled` is true.
- **Behaviour:** The LLM returns issues with codes from the routing table,
  severity, evidence and optional per-criterion scores (0–1, metrics only).
  Unknown codes are rejected by schema validation. The request goes through
  `LLMProvider` only, so the evaluation model can be switched (e.g. to a Luna
  or Terra model) by configuration without code changes.
- **Quality-mode override:** Required semantic/visual evidence may not be disabled or replaced by metadata-only approval. If a model rejects images, retain a pending visual review rather than asserting the frames were checked. Every final shot needs the bounded coverage contract of CF-REQ-416.
- **Failure:** Outside quality mode, if `semantic_enabled` is false, a `warning` Run Event
  `semantic_evaluation_skipped` is emitted and approval relies on deterministic
  validation only. If the model rejects image input, the request is repeated
  once without frames (layer 1 only) and a `warning` `visual_evaluation_unavailable`
  is emitted. If the LLM is unavailable (circuit open or request budget
  exhausted, CF-REQ-671), the Clip is **not** approved and the Run fails with
  `llm_unavailable`; the Clip file is retained for a later manual Run.
- **Acceptance:**
  - A fake evaluator returning `weak_hook` (blocking) causes a revision retry targeting `write_script`.
  - Per-criterion scores alone never change `passed`.
  - Switching `LLM_MODEL_EVALUATION` requires no code change (contract test with two fake model names).
  - Outside quality mode, a fake rejecting images completes metadata-only with a warning; in quality mode it retains a pending visual review and cannot approve.
- **Related:** CF-REQ-408, CF-REQ-415, OD-014

### CF-REQ-406 — Factual grounding evaluation

- **Description:** The semantic evaluation input shall include the Script with
  cited Claim IDs, the Claims with verified evidence excerpts and publishers.
  Statements not supported by the cited evidence produce
  `claim_not_supported` or `unsupported_statement` with segment references.
- **Acceptance:**
  - A script segment stating a number absent from all evidence (fake evaluator configured accordingly) produces a blocking issue referencing that segment.
- **Related:** CF-REQ-153

### CF-REQ-407 — Deterministic issue routing

- **Description:** Actions and target stages shall be derived by code from the
  issue routing table. LLM-proposed actions are kept only as free-text
  instructions attached to the table-derived Action.
- **Acceptance:**
  - Unit tests cover every row of the routing table.

### CF-REQ-408 — Scores are not the decision

- **Description:** No numeric threshold on an LLM score alone shall approve
  or reject a Clip.
- **Acceptance:**
  - A semantic result with all scores 0.1 and no blocking issues passes (warnings recorded); a result with all scores 1.0 and one blocking issue fails.

### CF-REQ-409 — Evaluation persistence

- **Description:** All Evaluations (gates, deterministic, semantic) shall be
  persisted with Run, Attempt and Clip, and exposed through the Run detail API.
- **Acceptance:**
  - The Run detail response lists Evaluations per Attempt in order.
- **Related:** CF-REQ-604

### CF-REQ-410 — Targeted revision

- **Description:** On a failed gate or evaluation with retries remaining,
  `plan_retry` shall select as re-entry point the **earliest** target stage
  among the blocking issues (pipeline order) and re-run from there, passing
  all Actions as revision instructions.
- **Behaviour:** Stages after the re-entry point run again but reuse
  artefacts whose inputs are unchanged (CF-REQ-412). Earlier stages are not
  re-run.
- **Acceptance:**
  - Issues targeting `select_assets` and `build_captions` ⇒ re-entry at `select_assets`; no `write_script` call.
  - A `reselect_asset` for segment 2 only re-selects segment 2; other segments keep their Assets.
  - A failed `select_assets` gate enters `plan_retry` before narration or
    composition; successful reselection records a passing gate for that Attempt.
- **Related:** ADR-008

### CF-REQ-411 — Bounded revision retries

- **Description:** A Run shall perform at most `workflow.max_revision_retries`
  revision retries (default 3, i.e. at most 4 Attempts).
- **Failure:** When exhausted, the Run fails with
  `failure_code = evaluation_failed_after_retries`, the last Evaluation linked,
  and no Publication is created. `abort` Actions fail the Run immediately with
  the issue code.
- **Acceptance:**
  - A fake evaluator that always fails yields exactly 4 Attempts and a failed Run with zero Publications.
  - With `max_revision_retries = 0`, the first failure fails the Run.

### CF-REQ-412 — Artefact reuse on retry

- **Description:** Revision retries shall reuse unchanged artefacts:
  narration (CF-REQ-302), selected Assets for unchanged Visual Segments, and
  rendered segment intermediates keyed by their segment spec hash.
- **Acceptance:**
  - A retry that changes only segment 2's Asset re-renders only segment 2's intermediate and makes no TTS or transcription calls.
- **Related:** CF-REQ-159, CF-REQ-302

### CF-REQ-413 — Failed results are never published

- **Description:** Publishing shall require `Clip.status = approved`; the
  publishing service and the `Publication` repository both refuse any other
  status.
- **Acceptance:**
  - Calling the publishing use case with a `rejected` Clip raises a domain error and creates no Publication.
- **Related:** CF-REQ-450

### CF-REQ-414 — Call retries are separate from revision retries

- **Description:** Transient provider failures shall be retried per
  `providers.max_call_retries` inside the stage and shall not consume revision
  retries. Permanent provider failures fail the stage without call retries.
- **Acceptance:**
  - A fake TTS failing twice transiently then succeeding leaves `revision_retries_used = 0`.
- **Related:** CF-NFR-010

### CF-REQ-415 — Visual frame sampling

- **Description:** For visual evaluation, the system shall extract
  `evaluation.visual_frame_count` (default 5) representative frames from the
  Clip deterministically, downscale them to `evaluation.visual_frame_width_px`
  (JPEG), and attach them to the single `evaluate_clip` request with, per
  frame, its timestamp, Visual Segment index, Asset ID and the caption text
  visible at that time. Frames are never sent one request per frame.
- **Behaviour:** Frames are taken at the midpoint of distinct Visual Segments,
  choosing segments evenly across the Clip (always including segment 0, the
  hook); if there are fewer segments than frames, remaining frames are taken
  at evenly spaced times. Frame extraction uses FFmpeg via the media runner.
  The evaluator may return `visual_irrelevant`, `misleading_generated_media`
  or `caption_quality` issues referencing the frame's segment.
- **Acceptance:**
  - For an 8-segment Clip, exactly 5 frames are extracted, including segment 0, and identical inputs give identical timestamps.
  - The `evaluate_clip` request contains 5 images and counts as one LLM request.
  - A `visual_irrelevant` issue on the frame from segment 3 routes to `reselect_asset` for segment 3.
- **Related:** CF-REQ-405, OD-014

## News-explainer quality review

The legacy sparse-frame count in CF-REQ-415 is not evidence that unsampled shots, animation or audio are acceptable. Quality mode uses the following coverage and approval contracts.

### CF-REQ-416 — Complete bounded output review

- **Description:** Quality evaluation shall cover every final Visual Segment, its editorial overlays and the complete audio/video timeline before automatic publication is eligible.
- **Behaviour:** Deterministic checks include geometry/collisions, licences, identity references, cue times, transitions, actual video duration/frame count and final mixed-audio limits. The one initial `evaluate_clip` request includes representative evidence for every shot up to `evaluation.quality_max_review_images`; sample overlay/transition boundaries where relevant. Images are supplied in one bounded request, not one request per shot. Insufficient capacity leaves explicit uncovered IDs pending owner review. Full playback/listening review is required during rollout; still frames do not prove temporal/audio quality.
- **Failure:** Any uncovered required evidence remains pending. Canonical issue codes route factual, visual, caption, pacing and audio problems to targeted revisions; scores alone do not approve.
- **Acceptance:** A 13-shot fixture never reports all shots checked from five images; an obscured person label blocks; a shortened video stream fails even when container duration is correct; boundary/audio defects are visible in review.
- **Related:** CF-REQ-259–261, CF-REQ-325, CF-REQ-402–405, CF-REQ-415

### CF-REQ-417 — Version-bound Quality Review

- **Description:** Quality Review shall distinguish deterministic validation, candidate/model review, owner playback review and publication eligibility, bound to the exact content/template/render hash.
- **Behaviour:** Persist review status, evidence coverage, unresolved issues, actor/model/policy versions and decision time. Quota/cost/modality failure preserves artifacts and records pending reasons; it never creates a passing Evaluation. Changed factual text, identity, media, overlays, audio or output invalidates affected review and publication approval. Owners may resolve documented uncertainty with evidence but cannot bypass blocking factual, security or licence checks. Original failed Run history remains intact.
- **Acceptance:** An unreviewed revision cannot inherit approval from an older file; quota exhaustion makes zero extra calls and preserves the preview; owner approval cannot publish an unresolved wrong-person fixture.
- **Related:** CF-REQ-220, CF-REQ-361–362, CF-REQ-408, CF-REQ-671

### CF-REQ-418 — Reference-set quality benchmark

- **Description:** Before enabling automatic quality-mode publication, a versioned reference set shall pass the approved editorial, visual, audio and safety rubric and be accepted by the owner.
- **Behaviour:** Use `quality.reference_story_count` frozen diverse Stories, including sensitive reporting, place/person ambiguity and long-label cases. Render through repository entry points using fakes or recorded outputs in ordinary tests. Compare original/improved outputs with full playback; record findings and actual live/mock/fake evidence. No numerical attention/virality score alone decides approval. Brand/template approval and benchmark provenance are retained.
- **Acceptance:** Automatic publication is unavailable without the accepted benchmark version; a fixture set includes unrelated coffee versus Mokha and wrong-person labels; all outputs satisfy media/decode/layout/audio checks and owner review.
- **Related:** CF-REQ-164, CF-REQ-260–262, CF-REQ-323–325, CF-REQ-417
