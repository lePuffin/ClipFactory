# 26 — Open Decisions and Known Conflicts

Everything intentionally undecided, and every conflict found between the
project brief, the existing repository and this baseline. Implementation must
not silently resolve these; it must use the stated **provisional choice** (if
any) and keep it behind the stated configuration or provider boundary.

## Open decisions

Format: question · why open · provisional choice · boundary that isolates it · who decides.
Entries marked **Decided** record the owner's answer (2026-09-28 review) and
are reflected in the referenced requirements; they stay here for history.

| OD | Topic | Status |
| --- | --- | --- |
| OD-001 | LLM model | Decided: `google/gemma-4-31b-it:free` (specific free vision model) |
| OD-002 | Target duration | Decided: 70 s |
| OD-003 | News sources | Decided: RSS + starter feed list |
| OD-004 | Media sources | Decided: Pexels, Pixabay, Unsplash, Wikimedia Commons |
| OD-005 | Generation providers | Decided: ComfyUI, native Wan, Higgsfield |
| OD-006 | Google TTS voice | Decided: Chirp 3 HD, `en-US-Chirp3-HD-Leda`, rate 1.0 |
| OD-007 | Whisper | Decided: faster-whisper `large-v3-turbo` (configurable) |
| OD-008 | Timezone | Decided: Europe/Lisbon |
| OD-009 | Publishing integrations | Decided: Instagram/Facebook signed URL; credentials/approvals are setup tasks ([setup guide](../setup/platform-credentials.md)) |
| OD-010 | Revenue | Decided: default RPMs |
| OD-011 | Captions | Decided: 6 % / 88 % / 10 %, 2 lines, centred, bold, box + shadow |
| OD-012 | Smart cropping | Deferred post-v1.0 |
| OD-013 | Music source | Decided: local library from YouTube Audio Library + Mixkit with manifest |
| OD-014 | Multimodal evaluation | Decided: metadata layer + 5 sampled frames |
| OD-015 | Performance targets | Decided: benchmark methodology now, targets from Phase 10 measurements |
| OD-016 | Cost budget | Decided: €1/Clip, €30/month, degrade then fail |
| OD-017 | Coverage thresholds | Decided: categories now, thresholds after baseline (Phase 10) |
| OD-018 | Production host | Decided: WSL2 native, manual start |
| OD-019 | Approval gate | Decided: optional, off, auto-publish after 10 min |
| OD-020 | Provider prices / FX rate | Open (verify in Phase 5) |
| OD-021 | OpenRouter free-tier limits | Open (baseline 20 RPM / 50 per day; verify) |

### OD-001 — LLM model(s)

- **Question:** Which model(s) to use via the OpenAI-compatible endpoint (OpenRouter initially)?
- **Decided:** `google/gemma-4-31b-it:free` — a specific free, vision-capable OpenRouter model (not the `openrouter/free` router) so development is reproducible. Selected from OpenRouter's public model list on 2026-09-28 (free, image input, `response_format` support, 262k context); a live request has not yet been made. Fallback if retired: `qwen/qwen3.8-27b:free`. The model is configuration (`LLM_MODEL`, `LLM_MODEL_EVALUATION`); OpenAI, Luna, Terra or local models are later configuration/adapters behind `LLMProvider` with no application-logic change. Weak free models need schema repair (CF-REQ-758).
- **Boundary:** `LLMProvider`, configuration.

### OD-002 — Target duration

- **Question:** The brief set min 60 s, target 60 s, max 90 s; aiming exactly at the minimum makes small TTS speed variations fail the gate.
- **Decided:** Default `target_seconds = 70` (min 60, max 90 unchanged). See [18-configuration.md](18-configuration.md#content-profile-defaults), CF-REQ-155.
- **Boundary:** `ContentProfile.duration`.

### OD-003 — News sources

- **Question:** Which `NewsSource` implementations and which publishers/feeds?
- **Decided:** `RssNewsSource` with a shipped starter feed list (BBC, Guardian, Al Jazeera, NPR, DW, France 24, NYT, CNN) in [18-configuration.md](18-configuration.md#research), editable in Settings. Feed URLs must be verified in Phase 3. Reuters/AP have no official public RSS; they enter via syndication. No search-capable news API in v1.0, so `gather_sources` relies on the research pool (CF-REQ-110 step 1).
- **Boundary:** `NewsSource`.

### OD-004 — External media sources

- **Question:** Which free/licensed image and B-roll providers?
- **Decided:** Pexels (photos + video), Pixabay (photos + video), Unsplash (photos only), Wikimedia Commons (news subjects and real people; per-file licences). Licence terms and API guidelines of each must be verified during implementation and recorded in the adapter module.
- **Boundary:** `MediaSourceProvider`.

### OD-005 — Image and video generation providers

- **Question:** Which generation services, if any?
- **Decided:** Inspired by OpenMontage (not a dependency): local ComfyUI (workflow templates; images and video, incl. Wan workflows), native local Wan via diffusers (video), Higgsfield cloud (images and video). Order is a Content Profile setting; default `image: [comfyui, higgsfield]`, `video: [comfyui, wan_local, higgsfield]`. Generated media allowed by default, but never of real identifiable people (CF-REQ-215).
- **Still open:** Higgsfield API contract, authentication and pricing (verify in Phase 5, OD-020). Reference GPU (RTX PRO 500 Blackwell laptop, ≈ 4–6 GB VRAM) is likely insufficient for Wan video; local adapters are implemented and tested with mocks/fakes, Higgsfield is the practical video path.
- **Boundary:** `ImageProvider`, `VideoProvider`.

### OD-006 — Google TTS API and voice

- **Question:** Which Google speech API, voice family and default voice?
- **Decided:** Google Cloud Text-to-Speech, Chirp 3 HD, voice `en-US-Chirp3-HD-Leda`, speaking rate `1.0`; changeable in Settings after listening tests. Speaking-rate support and exact price for Chirp 3 HD are verified in Phase 5 (OD-020).
- **Boundary:** `TTSProvider`.

### OD-007 — Whisper implementation

- **Question:** Which local Whisper implementation and model?
- **Decided:** `faster-whisper` with `large-v3-turbo` (configurable for later benchmarking, CF-NFR-030). Known from the prior prototype: CPU CTranslate2 does not accept compute type `auto` (use `default` or `int8`); CUDA auto-selection fails without `libcublas` — fall back to `cpu`/`int8`.
- **Boundary:** `TranscriptionProvider`.

### OD-008 — Schedule timezone

- **Question:** "05:00 daily" in which timezone?
- **Decided:** `Europe/Lisbon` default, editable per profile (IANA name).

### OD-009 — Publishing integrations

- **Question:** Credentials, OAuth flows, token storage, platform approvals and platform constraints for YouTube, Instagram, TikTok and Facebook.
- **Known constraints (unverified):** Instagram and Facebook content publishing (Graph API) fetch video from a publicly reachable URL; TikTok may restrict unaudited apps to private posts; YouTube uploads consume API quota; Facebook posting requires a linked Page and a Page access token.
- **Decided (Instagram, Facebook):** short-lived signed public URL through the owner's reverse proxy, which forwards only `/public/media/*` (CF-REQ-461, CF-NFR-114).
- **Provisional (rest):** Adapters implemented against documented APIs with unit tests on mocked HTTP; OAuth tokens stored as `0600` files under `${DATA_DIR}/secrets/`; publishing mode defaults to `dry_run`.
- **Decided (scope):** Platform credentials and app approvals are deployment/setup tasks, not architectural dependencies; they are documented in [doc/setup/platform-credentials.md](../setup/platform-credentials.md) and supplied via `.env` (template `.env.example`).
- **Boundary:** `Publisher`.
- **Decides:** Owner (accounts, app approvals), implementer (flows).

### OD-010 — Revenue data

- **Question:** Which platforms report revenue via API, and what RPM to assume elsewhere?
- **Decided:** Platform-reported estimates where available; otherwise default RPMs (USD per 1 000 views) youtube 0.05, instagram 0.01, tiktok 0.40, facebook 0.02, editable in Settings (CF-REQ-504).
- **Boundary:** `Publisher.fetch_metrics`, analytics settings.

### OD-011 — Caption layout and style

- **Question:** Caption margins and style for phone-first 9:16.
- **Decided:** Horizontal margin 6 %, maximum text width 88 %, bottom margin 10 %, max 2 lines, centred, bold sans-serif, semi-transparent box plus shadow; all configurable (`captions.*`, CF-REQ-312 – CF-REQ-314).
- **Note:** 10 % bottom margin (128 px at 720×1280) is lower than the area some platforms cover with their own UI; review on devices and raise `bottom_margin_pct` if captions are hidden.
- **Boundary:** `captions.*` settings.

### OD-012 — Smart cropping

- **Question:** Subject-aware cropping (faces/saliency) instead of centre-crop / `fit_blur`?
- **Provisional:** Deterministic centre-crop and `fit_blur` only (CF-REQ-255).
- **Decides:** Post-v1.0.

### OD-013 — Royalty-free music source

- **Question:** Which music library?
- **Decided:** Tracks stored permanently in the local library `${DATA_DIR}/music/` with a metadata manifest (CF-REQ-322), initially sourced manually from YouTube Audio Library and Mixkit. Selection is metadata/tag driven, no LLM (CF-REQ-320); ducking to about −20 dB under narration (CF-REQ-321). Audio files are not committed to Git; per-track licence and platform restrictions must be checked by the owner when adding tracks.

### OD-014 — Multimodal visual evaluation

- **Question:** Should semantic evaluation inspect sampled frames with a vision-capable model?
- **Decided:** Yes, as an optional second layer: one `evaluate_clip` request with metadata/production data (always) plus about 5 representative frames (CF-REQ-405, CF-REQ-415), using the free vision model of OD-001. Falls back to metadata-only if the model rejects images. The evaluation model can later be switched (e.g. Luna or Terra) by configuration.
- **Boundary:** Semantic evaluator input builder, `LLMProvider`.

### OD-015 — Performance targets

- **Question:** What are realistic v1.0 performance targets?
- **Decided:** No targets are invented now. The benchmark methodology is defined (CF-NFR-030 – CF-NFR-033); representative Clips are measured on the production host in Phase 10 and targets are derived from the results through the change process.

### OD-016 — Per-Run cost budget

- **Question:** Should a Run stop when LLM/TTS/generation spend exceeds a budget?
- **Decided:** Record usage and show cost in the UI; never exceed `budget.max_cost_per_clip` (€1.00) or `budget.max_cost_per_month` (€30.00, calendar month); degrade to free options first, then fail with `budget_exceeded` (CF-REQ-661 – CF-REQ-665, CF-REQ-612). Inspired by OpenMontage's estimate-before-spend budget controls.

### OD-017 — Coverage thresholds

- **Question:** Final coverage thresholds.
- **Decided:** No arbitrary percentages now. Required test categories are defined (unit, integration, pipeline, LLM contract, rendering, failure/recovery — [21-testing.md](21-testing.md#required-test-categories)); coverage is reported from Phase 1 and thresholds are set from the measured baseline in Phase 10 (CF-NFR-152).

### OD-018 — Production environment

- **Question:** Where does ClipFactory run?
- **Decided:** The owner's Windows machine under WSL2, native install (no Docker), started manually with `clipfactory serve` ([23-deployment.md](23-deployment.md)). Consequence: the 05:00 Run only happens when WSL2 and the app are running.

### OD-019 — Manual approval before publishing

- **Question:** Should the owner optionally approve Clips before publication?
- **Decided:** Optional gate `publishing.approval_required` (default off). When on, Clips wait for Approve/Reject in the UI and auto-publish after `publishing.auto_publish_after_minutes` (default 10) without a decision (CF-REQ-459, CF-REQ-460, CF-REQ-613).

### OD-020 — Provider prices and currency conversion

- **Question:** Actual prices of paid operations (Higgsfield images/video, Google TTS voice tier, LLM when cost is not reported) and the USD→EUR rate.
- **Provisional:** Price table and `usd_to_currency_rate = 0.92` in [18-configuration.md](18-configuration.md#provider-price-table), editable in Settings. Verify prices during Phase 5; prefer provider-reported costs whenever the API returns them.
- **Boundary:** `budget.*` settings.
- **Decides:** Implementer verifies; owner maintains.

### OD-021 — OpenRouter free-tier limits

- **Question:** Actual request limits of the owner's OpenRouter account for free models.
- **Provisional:** Baseline assumption 20 requests/minute and 50 requests/day (`llm.requests_per_minute`, `llm.requests_per_day`); daily reset at 00:00 UTC. Verify against the account and OpenRouter documentation in Phase 3; update settings, not code.
- **Boundary:** `llm.*` settings, LLM governance wrapper (CF-REQ-666 – CF-REQ-671).
- **Decides:** Implementer verifies; owner confirms.

## Known conflicts

| # | Conflict | Resolution in this baseline | Status |
| --- | --- | --- | --- |
| C-1 | The existing root `README.md` described a different product ("identifies the best moments from long-form videos and turns them into vertical clips" for platform-specific vertical formats), using prohibited terminology. | README rewritten to describe the news-Clip product of the brief; clipping of long-form video is listed as a non-goal. | Resolved — confirmed by owner |
| C-2 | Workspace notes from earlier sessions describe a prior prototype (package `app/`, versions v0.2–v0.5, Python 3.12, "reel"/"story-clip" jobs, Chatterbox/pyttsx3 TTS, OpenCV smart framing). None of that code exists in this repository. | Treated as informative lessons only (see below); not a source of truth. v1.0 follows this specification (Python 3.13+, provider ports, Clip terminology). | Resolved | <!-- terminology:allow -->
| C-3 | The brief places specifications under `docs/`; the owner's instruction requires `doc/specifications/`. | `doc/specifications/` is canonical; no `docs/` tree exists. | Resolved |
| C-4 | The brief's sample tree puts `pyproject.toml` and `package.json` at the root. | Placed in `backend/` and `frontend/` with a root `Makefile` ([22-development-workflow.md](22-development-workflow.md#repository-layout-target-for-v100)). | Resolved — confirmed by owner |
| C-5 | The brief's ADR list (10 ADRs) differs in numbering from the owner's list (14 ADRs). | The owner's list is used (ADR-001 … ADR-014). | Resolved |
| C-6 | The working tree contained an uncommitted change that emptied `.gitignore`. | With owner approval, `.gitignore` was rewritten for Python, Node and ClipFactory data (`.env`, `data/`, `.venv`, `node_modules`, `dist`, caches, coverage) (CF-NFR-106). | Resolved |
| C-7 | The brief's glossary lists `Provider` as a core domain entity. | Kept as a glossary term; modelled as configured adapters, not a persisted entity ([04-domain-model.md](04-domain-model.md#provider-not-an-entity)). | Resolved — confirmed by owner |
| C-8 | Brief duration examples (58 fail, 63 pass, 92 fail) and requirement example (59 fail, 60 pass, 91 fail) | Consistent: bounds are inclusive; all examples are in CF-REQ-401. | No conflict |
| C-9 | Brief: "target 60 s"; owner review: target 70 s. | Owner decision supersedes the brief (OD-002). | Resolved |
| C-10 | Brief: generation optional/undecided and "do not hardcode" providers; owner review: ComfyUI, native Wan and Higgsfield. | Implemented as adapters behind existing ports; order is profile configuration (ADR-013). | Resolved |
| C-11 | Baseline allowed any single Linux host with Docker Compose; owner: WSL2, native, manual start. | Deployment docs rewritten; daily schedule depends on the app running (OD-018). | Resolved |
| C-12 | Owner review suggested Dragonfly could hold distributed rate-limit/usage state; Dragonfly is on the prohibited list and ClipFactory runs as one process. | Not introduced. Rate-limit and usage state live in PostgreSQL + process memory; rationale and revisit condition in [ADR-015](decisions/ADR-015-llm-request-governance.md). | Resolved — owner to confirm |
| C-13 | Target ≤ 4 LLM requests per Clip vs. the earlier design (≈ 9 LLM tasks, one call per Source). | LLM work consolidated into 4 tasks; asset choice, visual-plan normalisation and Manual URL summary made deterministic (CF-REQ-666). | Resolved |
| C-14 | Earlier NFRs contained invented performance targets and coverage thresholds. | Replaced by benchmark methodology and required test categories; values set in Phase 10 (OD-015, OD-017). | Resolved |

`[Derived]` requirements (story novelty, `dry_run` default, disclosure flags,
attributions, reuse cooldown, real-people rule, English UI) were accepted by
the owner on 2026-09-28.

## Informative lessons from the prior prototype

Non-normative; useful when implementing adapters.

- OpenRouter free models are retired without notice; never hard-code a model (OD-001).
- Weak models need bounded schema repair with the validation errors fed back (CF-REQ-758); keep repair separate from HTTP 429 retries, which should honour `Retry-After` (CF-NFR-010).
- faster-whisper on CPU: use `int8`/`default` compute type (OD-007).
- Build FFmpeg caption rendering from files (ASS) rather than inline `drawtext` strings to avoid escaping problems (CF-REQ-314).
