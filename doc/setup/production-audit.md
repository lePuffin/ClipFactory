# Production Requirements Audit

Audit date: 2026-10-05. Canonical scope: all requirements in [specifications](../specifications/README.md), all 25 scenarios in [acceptance criteria](../specifications/24-acceptance-criteria.md), and the [requirement evidence inventory](requirements-evidence.md). This is a gap report, not a v1.0 completion declaration.

## Findings

| Area | Evidence and Finding | Status |
| --- | --- | --- |
| Research and grounding | Research, deterministic evidence verification and persistence executed live. Fixed missing Source IDs, long author persistence and lost key-fact rankings. Full novelty, preferred-source gathering and every research acceptance scenario are not demonstrated. | Partial; exercised live |
| Story Package and script | Reusing the persisted accepted Claims and script. Correcting one incomplete narration clause without adding a fact. Script gates remain enabled. Social metadata and generated-media disclosure need complete acceptance coverage. | Reused; partial coverage |
| Asset acquisition | The old Run path used library-or-card only. Added configured licensed media searches, cross-provider candidate ranking, bounded safe downloads, media validation, external provenance and content-addressed reuse before card fallback. Live API searches succeeded for Pexels, Pixabay and Commons. | Implemented and being verified |
| Generation | ComfyUI, native Wan and Higgsfield adapters, configured provider order, workflow manifests and generation budget checks are absent. No generated depiction of a real person is used in this render. | Missing; not required for licensed-media render |
| Visual production | Added bounded narration-aligned spans. Corrected frame fitting, implemented deterministic pans and intensity, stopped video looping, and compensated transition overlaps. Real mixed image/video rendering tests check the video frame count, not just container duration. | Tested with real FFmpeg |
| Narration | Google Chirp speech executed live. Locale mapping fixed; cache and duration gates tested; actionable revision word counts retained. | Live and tested |
| Transcription | Real faster-whisper transcription verified. PyAV compatibility constrained; automatic missing-CUDA fallback uses CPU/int8 without overriding explicit CUDA. | Live and tested |
| Captions | Installed the configured Noto font. Fixed padded safe-width accounting, font family/size/position serialization and lead-in timing. | Tested; final frames to be inspected |
| Music | Metadata-based selection and mixing exist. No eligible licensed local music Asset was installed; the specification permits narration-only output with a warning. Manifest import and complete mixing acceptance coverage remain incomplete. | Warning; partial implementation |
| Evaluation and approval | Deterministic gates remain enabled. OpenRouter's daily quota prevents a new semantic/frame evaluation. No cached semantic evaluation exists for the new visuals, so automated approval cannot be claimed. | Blocked; no fabricated approval |
| Targeted retries | Durable idempotent counters and revision Actions fixed. Cache reuse exists. All corruption/quarantine and targeted reselection acceptance cases are not verified. | Partial |
| Publishing | Adapters, dry-run records and approval services exist. No live posting is attempted during this render; accounts/approvals and all platform acceptance scenarios are not verified. | Unverified live |
| Analytics | Snapshot scheduling, aggregation and UI code have tests, but real published-platform metrics and all acceptance scenarios are not verified. | Tested with fakes; incomplete live evidence |
| UI and configuration | Dashboard, Runs, Clips, Assets, Profile, Settings and analytics pages exist. Frontend tests/build checks are required; full Playwright, accessibility and mobile acceptance evidence is missing. | Partial; not a UI completion claim |
| Scheduling and operations | Lifecycle, concurrency, setup and preflight have tests. Full process-kill recovery, fresh-host deployment and backup/restore are not demonstrated by this render. | Partial |
| Observability | Stage/provider/progress events exist; media acquisition now records selections and provider failures. Complete persisted LLM audit files and every failure-code scenario are not verified. | Partial |
| Security | SSRF, path and media safety tests exist; authorization is stripped on cross-origin media redirects. Complete architecture/XSS/prompt-injection/live-secret audit remains necessary. | Tested slice; incomplete global evidence |
| Cost and LLM governance | The declared PostgreSQL request ledger, Dragonfly RPM/circuit enforcement, daily/per-Run request budgets and pre-call monetary budget enforcement are not fully wired. A daily quota error was retried instead of opening the specified circuit. This task makes no OpenRouter calls. | Blocking v1.0 gaps |
| Architecture, deployment and non-functional requirements | A test tag is not an architecture review or benchmark. Performance, accessibility, CI, backup recovery and all declared layer constraints require independent evidence. | Not verified complete |

## Output Policy

The replacement video must use real licensed photographs and B-roll rather than an all-card fallback, retain source and media credits, mark archive/illustrative footage, meet the profile's encoding/duration/caption gates, and pass full decode and frame inspection. Its content is assembled from the retained research and script without new OpenRouter requests. The original failed Run remains failed; a new render is not proof of a completed or approved Run. Publication stays disabled unless the required approval is obtained.

## Verified Render

The reviewed replacement is [final.mp4](../../database/clipfactory-data/clips/a63a03c8-59a4-428b-a1fa-a37e6dc33393/final.mp4), with a [provenance manifest](../../database/clipfactory-data/clips/a63a03c8-59a4-428b-a1fa-a37e6dc33393/final.json) and [source/media credits](../../database/clipfactory-data/clips/a63a03c8-59a4-428b-a1fa-a37e6dc33393/final.description.txt). It reuses the retained research and corrected grounded script, cached narration and transcription, and makes zero OpenRouter calls. Exact Commons location files were inspected in a contact sheet; ambiguous coffee, food, interior and mislabelled flag Assets were quarantined. Archive location imagery and illustrative shipping footage carry visible labels. The final timeline has no repeated Asset IDs. Probe and full decode verified the video duration, 720x1280 H.264/yuv420p at 30 FPS, SAR 1:1, and 48 kHz stereo AAC; narration plus lead-in/tail is approximately 72.58 seconds. Representative final frames were inspected for correct imagery, labels and caption readability. No eligible local music track was available; narration-only output is permitted by CF-REQ-320.

Frontend lint, typecheck, all 14 tests and build passed during the audit. Automated semantic approval, publication and complete v1.0 acceptance remain unverified; the original failed Run was not relabelled as successful.

## Validation Results

- Backend: Ruff lint and formatting checks passed, Pyright reported zero errors, and the full pytest suite passed 240 tests with three existing resource warnings. Measured combined coverage was 77 percent.
- Frontend: lint, TypeScript checks, all 14 Vitest tests and production build passed.
- Media: the delivered file probes as 72.600 seconds, 720x1280 H.264/yuv420p, constant 30 FPS, SAR 1:1 and 48 kHz stereo AAC. Full decode passed. ISO BMFF inspection found `moov` before `mdat` (fast-start).
- Audio: measured integrated loudness was -15.34 LUFS and true peak -4.14 dBTP, inside the specified tolerance and peak limit.
- Visual review: 13 unique licensed Assets, including three B-roll shots; sampled final frames and the exact-location contact sheet were inspected. Misleading stock results were quarantined. Captions and archive/illustrative labels are visible.
- OpenRouter: zero calls during replacement production. Automatic semantic approval remains pending; no publication was attempted.

## Completion Boundary

Quality implementation update (2026-10-06): [news-quality-rendering.md](news-quality-rendering.md) records the new repository CLI/API/review UI, durable pending render revisions, independent evidence-bound editorial graphics, licensed audio manifests and timed SFX/music mixing, and the complete 72.6-second test. It supersedes the prior reliance on temporary rendering drivers for this delivered slice. The original audit metrics above remain historical; they are not the new release results. Automatic beat/candidate review, full paid-call governance, identity-confirmation editing and engagement analytics remain incomplete; no pending render was published or relabelled automatically approved.

ClipFactory does not currently satisfy every v1.0 acceptance scenario. The full requirement inventory deliberately records missing test evidence. Generation, request/cost governance, full E2E coverage and live publishing/analytics cannot be declared implemented or verified merely because a media file can be rendered.
