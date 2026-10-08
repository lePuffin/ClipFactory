# 24 — Acceptance Criteria (v1.0.0 Definition of Done)

ClipFactory v1.0.0 is complete when **every** scenario below passes, all
quality gates pass (CF-NFR-153), and the traceability report shows every
`Test`-verified requirement covered by a tagged test
([traceability.md](traceability.md)). This is the final checklist of the
implementation session ([25-roadmap.md](25-roadmap.md#phase-10--final-validation)).

Unless stated otherwise, scenarios run with all providers set to `fake`,
PostgreSQL, Dragonfly and FFmpeg real, publishing mode `dry_run`.

## Checklist

### CF-AC-001 — Research

- Given the fixture news set (≥ 40 references incl. the Reuters/AP/BBC/CNN/Blog set, a blocked publisher, stale items), when a Run starts, then at most `max_candidate_articles` articles are fetched, blocked/stale items are excluded, exact duplicates are stored once and the Blog copy is marked syndicated of Reuters.
- **Requirements:** CF-REQ-100–104, CF-REQ-118
- **Verified by:** integration + E2E-1

### CF-AC-002 — Story selection

- The syndication set forms one Story candidate with `article_count = 5`, `independent_source_count = 4`; selection is deterministic for fixed fake ratings; excluded topics and recently covered Stories are rejected with reasons visible in Run detail.
- **Requirements:** CF-REQ-105–109, CF-REQ-111
- **Verified by:** unit + E2E-1

### CF-AC-003 — Source grounding

- Additional Sources are gathered up to the preferred count; every accepted Claim has verified verbatim evidence; fabricated excerpts are unverified; support levels are correct; single-source Claims are attributed in the script; a Story with < 3 accepted Claims falls back to the next candidate.
- **Requirements:** CF-REQ-110, CF-REQ-112–117
- **Verified by:** unit + integration

### CF-AC-004 — Story Package and script

- A versioned Story Package exists; the script is in the profile language, within the word budget, 4–8 segments, hook ≤ 5 s, every segment cites accepted Claims; each script-gate failure code triggers a revision; social metadata contains source and asset attributions and disclosure flags.
- **Requirements:** CF-REQ-150–162
- **Verified by:** unit + E2E-1

### CF-AC-005 — Visual planning and asset reuse

- Each Script Segment has Visual Segments with asset requirements, deterministic motion and transitions; a second Run needing the same subject reuses the library Asset without external calls; a retired Asset is never selected; the same Asset is not used twice in one Clip.
- **Requirements:** CF-REQ-204–206, CF-REQ-211–213, CF-REQ-250–257
- **Verified by:** unit + E2E-8

### CF-AC-006 — Media acquisition, generation and provenance

- Valid generated media is imported independently of Run outcome, including
  timeout/graceful cancellation. Failed validation/import preserves recovery
  files and metadata without making invalid output selectable.
- Wan reuses complete cached weights offline after restart; missing files
  trigger download fallback. Settings / Environment controls FPS and inference
  steps for new and continued Runs without redownloading loaded weights.

- Native Wan can fill a missing media image or video shot with generated video when
  allowed, including `reuse_first` shots after stock selection fails but
  excluding `acquire_only` and named-person shots; missing model weights download into the local cache on first use,
  loaded weights are reused, and failures remain explicit without placeholders.
- Missing media is acquired from a `MediaSourceProvider` with full provenance; invalid, oversized and low-resolution media are rejected; ordinary media generation is used only when allowed, in the profile's provider order, with fallback when a provider is unreachable; real identifiable people come only from licensed real media; ComfyUI templates are validated and filled correctly; when no suitable reviewed media is available, a segment-specific blocking issue enters bounded reselection instead of generating a plain-colour text card; every Asset has a licence; attribution-required Assets appear in the description. Typed infographic/scientific graphics are covered separately by CF-AC-033 and never use the media-provider fallback.
- **Requirements:** CF-REQ-200–203, CF-REQ-207–210, CF-REQ-214–217
- **Verified by:** unit + contract + integration

### CF-AC-007 — Narration, transcription and captions

- Narration is produced via `TTSProvider` (Google Chirp 3 HD, voice `en-US-Chirp3-HD-Leda` in live tests), stored as a non-reusable Asset, cached by text hash; duration gate produces actionable word deltas; transcription uses `large-v3-turbo` by default; captions use Script spelling with transcription timing, 2 centred lines within 6 % side margins, 88 % text width and 10 % bottom margin, readable box/shadow, and hostile caption text renders literally; music is selected from the local manifest-described library by metadata (no LLM), respects platform restrictions, ducks to −20 dB under narration, and its absence is only a warning.
- **Requirements:** CF-REQ-300–305, CF-REQ-310–314, CF-REQ-320–322
- **Verified by:** unit + integration

### CF-AC-008 — Evaluation and targeted retry

- Quality evaluation supplies bounded per-shot evidence in one initial final-review request; missing visual evidence remains pending. A targeted irrelevant-shot issue revises only affected media, reusing unchanged narration/transcription/script; approval follows only complete review.
- **Requirements:** CF-REQ-400, CF-REQ-405–410, CF-REQ-412, CF-REQ-414–417
- **Verified by:** unit + E2E-2

### CF-AC-009 — Bounded retries and no publication of failures

- A Run never exceeds its revision limit or eight total LLM requests. With enough request budget, three retries produce four Attempts and `evaluation_failed_after_retries`; reaching the request cap earlier stops with `llm_budget_exhausted`. Neither path creates a Publication; final issues and limiting reason are visible.
- **Requirements:** CF-REQ-411, CF-REQ-413, CF-REQ-450, CF-REQ-655, CF-REQ-666
- **Verified by:** E2E-3

### CF-AC-010 — Publishing

- Dry-run makes no platform calls; partial failure and idempotent resume behave as specified; disclosure flags are mapped. Human-review mode waits for explicit Approve/Reject indefinitely, including after ten minutes. Timeout publication requires eligible opt-in automatic mode. URL-pull platforms receive the signed expiring URL for the exact reviewed file.
- **Requirements:** CF-REQ-451–457, CF-REQ-459–461, CF-REQ-613, CF-NFR-114
- **Verified by:** unit + integration + E2E-1, E2E-10

### CF-AC-011 — Analytics

- A published Publication gets tasks at 1 h/6 h/24 h/48 h/7 d/30 d; with a fake clock, snapshots are captured once each; missing metrics are null and shown as "n/a"; revenue is labelled estimated with its basis, or null when no basis exists.
- **Requirements:** CF-REQ-458, CF-REQ-500–506, CF-REQ-603
- **Verified by:** integration + E2E-9

### CF-AC-012 — Composition output

- The approved Clip is 720×1280, SAR 1:1, 30 FPS constant, H.264/AAC MP4 with faststart, duration = lead-in + narration + tail within 60–90 s; boundary durations 59/60/90/91 s behave as specified; the composition spec hash is stable; a corrupt Asset is quarantined and reselected.
- **Requirements:** CF-REQ-350–359, CF-REQ-401–404
- **Verified by:** unit + integration (real FFmpeg) + E2E-1

### CF-AC-013 — Dashboard and live progress

- Starting Run Now from the UI shows stage-by-stage progress via SSE without reload, survives a reconnect without duplicate/missing events, and the dashboard shows recent Runs, 7-day totals with "Estimated revenue", and the next scheduled Run.
- **Requirements:** CF-REQ-600–602, CF-REQ-608, CF-REQ-852
- **Verified by:** E2E-6 (Playwright)

### CF-AC-014 — Settings and Content Profile

- The owner edits the Content Profile and application settings; invalid values are rejected with field errors; credential status is visible without secrets; edits affect only subsequent Runs.
- **Requirements:** CF-REQ-550–555, CF-REQ-606–607, CF-REQ-750–754
- **Verified by:** E2E-7 + integration

### CF-AC-015 — Manual URL

- Submitting a valid fixture URL runs `ingest_url` then the normal pipeline to an approved Clip; private/loopback/non-HTTP URLs are rejected with 422; excluded-topic warnings do not block.
- **Requirements:** CF-REQ-609, CF-REQ-700–703
- **Verified by:** E2E-4

### CF-AC-016 — Scheduling and Runs

- After correcting an operational error, Continue Run resumes the failed
  checkpoint with current settings without repeating completed stages.
  Active-run conflicts, missing checkpoints, exhausted retries and publication
  failures are rejected explicitly; failure history and costs are retained.
- Stop cancels queued/running work without killing the Run worker, retains
  imported Assets, records `owner_stopped`, and rejects active publication.

- With a fake clock, a Run starts at 05:00 in the profile timezone exactly once; a missed schedule within grace runs at startup; concurrent triggers produce one Run and a 409; a process kill after `write_script` resumes at `plan_visuals`; stage timeouts fail the Run with `stage_timeout`.
- **Requirements:** CF-REQ-650–660
- **Verified by:** integration + E2E-5

### CF-AC-017 — Observability ("Why did today's Clip fail?")

- Run detail embeds stage-based progress and a current-stage bubble in Execution
  (no separate Live Progress panel); its Event Stream shows newest events first.
  Execution includes live/frozen elapsed time and snapshotted LLM models;
  generation reports loading/download, actual inference steps, encoding,
  validation and completion/failure without fabricated download percentages.
  Native Wan inference advances Execution progress within asset selection;
  worker heartbeats renew the stage timeout without advancing the percentage.
- For each failure code in CF-REQ-655, the Run detail page shows the failing stage, code, actionable message, the events leading to it, and relevant Evaluations; logs carry `run_id`/`stage`; LLM exchanges are auditable; health reports each dependency.
- **Requirements:** CF-REQ-604, CF-REQ-850–856
- **Verified by:** integration + E2E-3

### CF-AC-018 — Security

- SSRF, path traversal, hostile media, command-injection-shaped filenames, XSS-shaped titles, prompt-injection article text and secret-in-log tests all pass; non-loopback binding requires a token.
- **Requirements:** CF-NFR-100–114, CF-REQ-611
- **Verified by:** unit + integration

### CF-AC-019 — Testing and quality gates

- `make check` passes; CI is green; all six test categories (unit, integration, pipeline, LLM contract, rendering, failure/recovery) exist for every applicable stage; coverage is reported and the owner has set thresholds from the measured baseline; no default test needs network or credentials; every `Test`-method requirement has a tagged test.
- **Requirements:** CF-NFR-150–157
- **Verified by:** CI

### CF-AC-020 — Architecture conformance

- Architecture tests pass (layering, provider isolation, subprocess confinement, prohibited dependencies); runtime infrastructure is one native app process, Compose-managed PostgreSQL and Dragonfly, FFmpeg and the data directory; Dragonfly keys are limited to namespaced rolling LLM RPM/circuit state; switching any provider to `fake` requires configuration only.
- **Requirements:** CF-NFR-001–003, CF-NFR-020–024, CF-REQ-751
- **Verified by:** unit (architecture tests) + review

### CF-AC-021 — Non-functional measurements

- The benchmark (CF-NFR-030) has been run on the production host for the benchmark set; the Phase 10 report contains the measurements, the derived v1.0 targets have been added to [03](03-non-functional-requirements.md) through the change process, and accessibility results meet CF-NFR-040; UI is usable at 390 px width.
- **Requirements:** CF-NFR-010–013, CF-NFR-030–033, CF-NFR-040–041, CF-NFR-050–052
- **Verified by:** measurement + review

### CF-AC-022 — Deployment and documentation

- A fresh WSL2/Linux host following [23-deployment.md](23-deployment.md) runs PostgreSQL and Dragonfly in Compose and the backend natively as one process; backup/restore works once without Dragonfly backup; `python3 scripts/check_docs.py` passes; specifications, ADRs and code agree (reviewer agent report has no open blocking findings).
- **Requirements:** CF-NFR-001, CF-NFR-051, CF-REQ-755–757
- **Verified by:** manual + review

### CF-AC-023 — Cost governance

- Every paid call records a cost entry (reported or estimated); Run and monthly totals are correct; a call that would exceed €1.00 per Clip or €30.00 per month is not made; generation degrades to free providers or suitable reviewed stock media with a `budget_degraded` warning, never an automatic plain-colour text card; a refused LLM/TTS call fails the Run with `budget_exceeded`; scheduled Runs are skipped once the monthly limit is reached; the UI shows cost per Run/Clip and month-to-date versus limits.
- **Requirements:** CF-REQ-612, CF-REQ-661–665, CF-NFR-052
- **Verified by:** unit + integration + E2E-10

### CF-AC-024 — LLM request governance

- An uncached quality Run makes five initial requests (four for Manual URL), never more than eight total. Cache hits reduce counts and are visible. RPM/daily/cost checks precede dispatch and survive restart; start thresholds are trigger-specific. Permanent/daily/credit errors are not retried; exhaustion opens the circuit and retains pending artifacts. Dragonfly unavailability fails closed; durable usage/domain/workflow data remain in PostgreSQL.
- **Requirements:** CF-REQ-666–671, CF-REQ-758
- **Verified by:** unit + integration + pipeline + failure/recovery tests

### CF-AC-025 — Local operations

- On a fresh supported WSL2/Linux host, `clipfactory setup` idempotently starts healthy pinned PostgreSQL and Dragonfly Compose services, migrates and seeds without starting the backend; `clipfactory doctor` is read-only, redacts secrets and returns 0 only when all required checks pass; `clipfactory run` starts one native backend process with one worker, and refuses to start when either dependency is unavailable.
- **Requirements:** CF-REQ-755–757, CF-NFR-001
- From the repository root, `uv run clipfactory` runs the same startup as
  explicit `run`, with Manim and Wan installed by the locked root runtime
  without project or group flags; explicit operational subcommands remain.
- An unavailable `PUBLIC_MEDIA_DIR` does not block startup or setup, neither
  of which accesses or creates it. `doctor` reports its unavailability as
  `WARN` and exits 0 if required checks pass. `DATA_DIR` remains required.
- **Verified by:** integration + manual

## News-explainer quality extension

The following scenarios extend the baseline by owner direction on 2026-10-06. They are additional completion gates, not evidence that the application already passes them.

### CF-AC-026 — Grounded news-explainer storytelling

- The existing script request returns a coherent grounded narration and ordered Narrative Beats. The hook states a supported development, the Story explains its significance without inventing consequences, uncertainty is preserved, and the ending is complete. Clipped sentences, misleading questions and unsupported headlines fail review. At most one optional invitation appears under the configured policy; sensitive-story and invitation-disabled fixtures omit it. A hook-only revision preserves unaffected segments.
- **Requirements:** CF-REQ-153, CF-REQ-155, CF-REQ-157, CF-REQ-159, CF-REQ-163–165, CF-REQ-406
- **Verified by:** unit + integration + owner reference-set review

### CF-AC-027 — Grounded labels and mobile-safe overlays

- A Clip includes independently timed person, place and Source labels with evidence bindings. A wrong-person fixture blocks approval; long names reflow or request review rather than overlap faces, subtitles or platform controls. All four platform-safe variants pass measured bounds and contrast checks. Archive and illustrative labels remain visible; media-author credits are distinct from news-source attribution. Static reading-focused graphics are permitted.
- **Requirements:** CF-REQ-161, CF-REQ-203, CF-REQ-258–261, CF-REQ-313–314
- **Verified by:** unit + real render integration + mobile frame review

### CF-AC-028 — Purposeful animation and licensed sound

- A versioned storyboard renders restrained keyframed motion and motivated transitions with contiguous timing and exact video duration. Licensed music and SFX follow reconciled beat/word anchors, use bounded fades and ducking, and mix with narration into one stereo stream. Final loudness and peak checks pass; no cue masks speech. Sensitive-story fixtures suppress inappropriate cues, and missing optional audio is reported. No provider is called to generate basic motion or a text label.
- **Requirements:** CF-REQ-262, CF-REQ-323–325, CF-REQ-351, CF-REQ-354–357
- **Verified by:** unit + real FFmpeg integration + complete playback/listening review

### CF-AC-029 — Relevant licensed-media review and cache

- Bounded permitted previews from multiple providers enter one candidate-review request with scene IDs and evidence. True location media wins over ambiguous coffee/food/flag matches; uncertain identity is held for review. Only selected full media is downloaded and validated. An unchanged review input reuses its cached judgment; a changed identity or template cannot reuse stale approval. Quota/cost/modality failure retains work without approving unseen media.
- **Requirements:** CF-REQ-207, CF-REQ-210, CF-REQ-218–220, CF-REQ-260, CF-REQ-666–671
- **Verified by:** unit + mocked HTTP/LLM contracts + integration

### CF-AC-030 — Reproducible retained-content revision

- The repository's preview/rerender path reads saved versioned inputs and produces a new render revision, without temporary scripts. Label/transition-only changes reuse research, script, narration and transcript; script edits invalidate audio/alignment; media edits invalidate relevant judgments. Prior output remains retrievable. Approval is tied to the exact reviewed hash and is invalidated by material changes. The original failed Run is not relabelled successful.
- An optional owner-provided logo Asset retains its transparency and aspect ratio, stays within 112 × 112 px at 720 px output width, and appears 24 px from the top/right edges for the entire revision. The logo-only revision leaves the original file and narration intact, adds no provider calls, and is pending review.
- **Requirements:** CF-REQ-152, CF-REQ-220, CF-REQ-302, CF-REQ-360–362, CF-REQ-412
- **Verified by:** integration + E2E + zero-provider-call assertions

### CF-AC-031 — Complete quality review and explicit publication control

- Every rendered shot, overlay identity and required temporal/audio check has review evidence or an explicit pending reason. Quota failure preserves artifacts without false approval. Exact-hash approval is invalidated by material edits. Human-review mode cannot publish after any timeout; automatic publication is available only after a versioned owner-accepted reference benchmark and explicit opt-in. No owner action bypasses unresolved factual/security/licensing issues.
- **Requirements:** CF-REQ-405, CF-REQ-416–418, CF-REQ-459–460, CF-REQ-666–671
- **Verified by:** unit + integration + E2E + reference-set playback review

### CF-AC-032 — Honest engagement and creative-version reporting

- Supported retention, watch time, comments, shares and attributable follows/subscriptions display definitions, source, age, denominator and unavailable fields. Account-level follower delta is not labelled per-Clip conversion. Comparisons link exact creative versions, match platform/capture age, disclose sample size/confounders and distinguish observation from actual randomized experiments. Results never guarantee growth or automatically change editorial policy.
- **Requirements:** CF-REQ-164, CF-REQ-500, CF-REQ-502, CF-REQ-505, CF-REQ-507–508
- **Verified by:** unit + contract + UI tests

### CF-AC-033 — Typed local infographic and scientific graphics

- A legacy VisualDraft without `kind` defaults to `media`; current `write_script` returns a typed `media`, `infographic` or `scientific` draft in its existing single structured request. Factual text/values cite accepted Claims. Supported infographic templates are statistic, comparison and timeline; scientific templates are a bounded enum-based function plot and Claim-grounded relationship diagram. Maps fail unless supplied with verified, versioned geometry. Arbitrary code, HTML/SVG, URLs, unknown templates/Claims, fabricated observations and generated depictions of identifiable people are rejected before rendering; a person name may appear only as a supported text label, not a generated likeness.
- Infographics route only to local HyperFrames and scientific graphics only to local Manim, independent of profile video-provider ordering. Media uses acquisition/Wan subject to the cap and explicitly declared alternatives in CF-REQ-266. Primary graphics rendering requires `allow_generated_media` and `generate_allowed`; failures are explicit (`unsupported_graphics_template`, `unsupported_statement`, `graphics_render_failed`) and never fall back to Wan, another provider, SVG or FFmpeg authoring. The existing VideoProvider request carries the optional provider-neutral graphics specification; there is no new provider port or planning LLM request.
- A real local HyperFrames and Manim integration fixture produces target-sized video at configured graphics FPS and planned segment duration. FFprobe and full decode pass; the imported reusable Asset retains renderer/template/input/Claim provenance and normal content-addressed persistence. Failed import retains recovery output without activation. Exact reusable graphics may be reused safely. Missing executable, unsupported templates and renderer failures cannot create an Asset, approve a Clip or publish.
- Installation uses an exact-version-pinned local HyperFrames Node package lock and optional isolated `graphics-manim` Python group. Runtime paths/FPS/timeout follow [18-configuration.md](18-configuration.md); run settings are snapshotted. Cancellation is bounded to the owned subprocess and leaves unrelated processes alive. Silent watchdog heartbeats renew the stage deadline but do not appear as Run Events or progress. Rendering UI is indeterminate until measured frame counts support a progress fraction.
- FFmpeg remains final assembly/probe and renderer-internal encoding remains allowed; no SVG or FFmpeg graphics-authoring fallback exists.
- **Requirements:** CF-REQ-153, CF-REQ-201, CF-REQ-208, CF-REQ-251, CF-REQ-263–265, CF-REQ-604, CF-REQ-655–656, CF-REQ-750–751, CF-REQ-756, CF-REQ-760, CF-REQ-850, CF-NFR-001, CF-NFR-003, CF-NFR-012, CF-NFR-102, CF-NFR-112
- **Verified by:** unit + real local renderer integration + API/UI E2E + fixture review. External/live integrations are not presumed validated.

### CF-AC-034 — Wan cap and suitable alternatives

- Settings exposes a numeric per-Run Wan limit, default 2, allowing 0–100.
  Saving 0 disables new Wan starts but not reusable generated Assets.
  Invalid, fractional and out-of-range values are rejected visibly.
- Five unmet media Visuals cause at most two native Wan generation starts.
  Failed/cancelled starts count durably, including historical events; Retry,
  restart and Continue do not reset the same Run's allowance. Unconfigured
  skipped providers and Asset reuse consume no allowance. Adjusting the limit
  uses existing usage, never a fresh counter.
- Remaining Visuals use a suitable accepted-Claim-grounded declared graphics
  alternative (HyperFrames infographic or Manim science/math) or up to two
  different refined queries on configured free media sources. Candidate review,
  licence, identity, resolution, duplicate avoidance and generated-media
  permission are preserved. Unresolved alternatives remain blocking
  `missing_asset`; unsupported graphics fail explicitly, without fabricated
  observations, placeholders or extra Wan calls.
- **Requirements:** CF-REQ-207–210, CF-REQ-215, CF-REQ-263–266, CF-REQ-606, CF-REQ-653, CF-REQ-759
- **Verified by:** unit + repository/API integration with fakes + UI tests.
  Real provider quality and live end-to-end production remain separate checks.
