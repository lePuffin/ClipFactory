# 07 — Asset Management

Covers the Asset library and stage `select_assets`.
Entity: `Asset`, `Provenance`, `GenerationInfo`, `AssetUsage` in
[04-domain-model.md](04-domain-model.md). Decision:
[ADR-011](decisions/ADR-011-asset-reuse-and-provenance.md),
[ADR-013](decisions/ADR-013-provider-independent-media-generation.md).
Storage: [architecture/storage-architecture.md](architecture/storage-architecture.md).

## Selection order per Visual Segment

```text
AssetRequirement
   │
   ├─1─► search library (PostgreSQL full-text + filters) ── match ≥ threshold ──► reuse
   │
   ├─2─► MediaSourceProvider(s) search → download → validate → store ──────────► acquired
   │
   ├─3─► ImageProvider / VideoProvider in profile order (only if allowed, budget permitting) → validate → store ─► generated
   │
  └─4─► missing reviewed media ──────────────────────────────────────────────► bounded reselection / owner review
```

This reuse/acquisition/provider-order path is for `kind = media`. Typed
infographic and scientific segments use the explicit local renderer route in
[08-visual-production.md](08-visual-production.md#cf-req-264--explicit-graphics-renderer-routing);
they do not enter media-provider fallback.

## Requirements

### CF-REQ-200 — Asset library

- **Description:** Every stored media file used or produced by ClipFactory
  shall be an `Asset` record with the metadata in the domain model.
- **Acceptance:**
  - Every file under the storage `assets/` prefix has exactly one Asset row, and vice versa (verified by an integration test).

### CF-REQ-201 — Mandatory provenance

- **Description:** An Asset shall not become `active` without `Provenance`
  containing origin, provider, licence and, for external Assets, source URL.
- **Failure:** A candidate whose provider response lacks a licence is discarded
  with reason `unknown_license`.
- **Acceptance:**
  - Storing an external Asset with empty `license` raises a domain error.
  - A generated Asset, or a graphics renderer Asset with
    `origin = rendered`, without `GenerationInfo` raises a domain error.
  - A rendered graphics Asset records its named renderer, template/version,
    normalized typed input and Claim references, and is not active until the
    normal media validation/import checks pass.
- **Related:** CF-REQ-265, ADR-011, ADR-019

### CF-REQ-202 — Content-addressed storage

- **Description:** Asset files shall be stored under a key derived from their
  SHA-256; storing identical content twice shall reuse the existing Asset.
- **Acceptance:**
  - Downloading the same image from two URLs yields one file and one active Asset row.
- **Related:** [storage-architecture](architecture/storage-architecture.md)

### CF-REQ-203 — Attribution capture

- **Description:** When a licence requires attribution, the Asset shall
  store `attribution_required = true` and an `attribution_text` built from
  author, title/source and licence.
- **Acceptance:**
  - A CC BY 4.0 fixture yields attribution text containing author, licence name and source URL.
- **Related:** CF-REQ-161

### CF-REQ-204 — Reuse first

- **Description:** For every Visual Segment, `select_assets` shall search the
  library before contacting any external or generation provider.
- **Acceptance:**
  - When a suitable library Asset exists, no `MediaSourceProvider`, `ImageProvider` or `VideoProvider` call is made for that segment (verified with fakes counting calls).
- **Related:** CF-REQ-205

### CF-REQ-205 — Library matching

- **Description:** Library search shall retrieve candidates with PostgreSQL
  full-text search over description, tags and subjects, filtered by
  `status = active`, `reusable = true`, media type, category and minimum
  resolution, and rank them with a deterministic match score.
- **Behaviour:** `match = 0.5 × subject_overlap + 0.3 × tag_overlap + 0.2 × text_rank_normalised`
  (overlaps are Jaccard on normalised terms). The highest-scoring candidate
  with `match ≥ assets.reuse_min_match_score` (default 0.6, Provisional) is
  chosen deterministically (ties: higher `quality_score`, then least recently
  used). Asset selection makes no LLM request; relevance is judged later by
  evaluation (CF-REQ-405, CF-REQ-415).
- **Acceptance:**
  - A library Asset tagged `["parliament","uk"]` with subject `UK Parliament` matches a requirement with the same subject above threshold.
  - A retired Asset is never returned.
- **Related:** CF-REQ-204, CF-REQ-251

### CF-REQ-206 — Reuse variety [Derived]

- **Description:** An Asset shall not be used twice in the same Clip and
  shall not be reused if it appeared in an approved Clip within
  `assets.reuse_cooldown_days` (default 3), unless no alternative passes
  matching.
- **Acceptance:**
  - With two equal candidates, the one not used in the last 3 days is chosen.

### CF-REQ-207 — External media acquisition

- **Description:** When reuse has no suitable Asset, query configured media providers with the requirement's description, subjects and media type, up to `assets.candidates_per_search` candidates each; fetch only bounded licensed previews for quality review and download only chosen full media.
- **Behaviour:** Provider metadata includes URL, author, licence, attribution, media type, dimensions and duration. Code preliminarily ranks candidates using term overlap, portrait suitability, required media type and provider relevance rank. In quality mode, the batched review of CF-REQ-219 supplies evidence-backed eligibility judgments; code makes the final deterministic selection from eligible candidates. Metadata relevance alone is not visual proof.
- **Failure:** Transient provider errors follow the call-retry policy; failures are recorded and the next provider is tried. If no valid reviewed candidate is available, try permitted generation or enter bounded reselection and owner review with the reason recorded, not a fabricated relevance judgment or a plain-colour card.
- **Acceptance:** A fake returning three candidates downloads only the selected full file; preview downloads stay separately bounded; a transient failure is retried then skipped under policy.
- **Related:** CF-REQ-210, CF-REQ-218–219, [provider-architecture](architecture/provider-architecture.md#mediasourceprovider)

### CF-REQ-208 — Media generation

- **Description:** When no library or external Asset is chosen, the system
  may generate an image or video through `ImageProvider` / `VideoProvider`
  only if the Content Profile `visual_style.allow_generated_media` is true
  and the requirement strategy is `generate_allowed`. Native Wan video
  fallback is also permitted for `reuse_first` after suitable stock media
  has been exhausted; `acquire_only` never permits generation. Typed
  infographic/scientific graphics are routed separately under CF-REQ-264 and
  never enter this provider-order fallback.
- **Behaviour:** Providers are tried in the order of the Content Profile
  `generation.image_providers` / `generation.video_providers`, skipping
  providers not enabled in the environment or not reachable (`is_configured()`
  false, or ComfyUI server down). Before each paid call the budget check of
  CF-REQ-662/CF-REQ-663 applies; a provider whose estimated cost would exceed
  a limit is skipped (degradation, CF-REQ-664). If every provider fails or is
  skipped, the segment falls through to CF-REQ-209. The generated Asset stores
  `GenerationInfo` (provider, model, prompt, parameters, seed; plus workflow
  name for ComfyUI).
- **Owner revision (2026-10-07):** When no suitable image or video can be
  selected, `wan_local` may supply a generated video for either shot type,
  subject to profile permission and a `generate_allowed` or `reuse_first`
  strategy. Named-person restrictions still apply. The
  selected plan records video media type and generated provenance; it is not
  presented as real event footage and still requires final visual review.
  Missing `WAN_MODEL` weights download on first use from the configured
  Hugging Face model source into `${DATA_DIR}/models/wan`, outside Git;
  subsequent calls reuse cached weights. A local model directory may also
  be configured. Loading/inference run off the event loop with serialized
  access. Missing optional dependencies, unavailable CUDA, download failures
  and generation failures are recorded explicitly; no placeholder is used.
  Run Events report generation start, model loading (including possible
  download), inference step counts, frame saving, encoding, validation and
  completion or failure, with provider and model where available.
  Model weights are shared infrastructure files, not media Assets. On process
  restart or continuation, loading first uses `local_files_only=True` from
  the persistent cache; only missing/incomplete local files trigger an online
  load to fetch required files. Events distinguish cache loading from actual
  download fallback. No Run cleanup deletes the shared model cache.
  Completed valid generation is imported as a reusable Asset independently
  of Run success. A timeout or graceful cancellation waits for in-flight
  generation and import to settle before propagating cancellation. Generated
  output is deleted from staging only after successful library import.
  Failed validation or import retains the output and generation metadata in
  `${DATA_DIR}/generated-media/pending/`, outside disposable Run work; failure
  events identify the recovery storage key. Invalid media remains unavailable
  for selection. Forced process termination can interrupt import and cannot
  guarantee completed output; saved staging files remain for recovery.
  Explicit owner Stop overrides graceful completion: generation is cancelled
  at a safe interruption point and unfinished output may be lost, as confirmed
  by the owner. Assets already imported are never deleted by Stop.
  Native Wan starts are limited per Run (default 2); at the cap selection uses
  the grounded graphics/refined free-media alternatives in CF-REQ-266.
- **Acceptance:**
  - Cancelling generation or import still saves valid output to the library
    before cancellation propagates; a later Run failure does not delete it.
  - Rejected media is not selectable but its output and metadata remain saved.
  - Missing or rejected stock media in a `reuse_first` shot invokes native
    Wan when permitted; accepted stock media does not invoke generation.
  - `acquire_only` shots and named-person shots never invoke generation.
  - With `allow_generated_media = false`, no generation fake is called.
  - With profile order `[comfyui, higgsfield]` and ComfyUI unreachable, Higgsfield is called once and the Asset records `provider = higgsfield`.
  - With order `[higgsfield, comfyui]` and a remaining per-Clip budget below the Higgsfield estimate, ComfyUI is used and a `warning` event `budget_degraded` is emitted.
  - With no suitable media and generation allowed, a fake video generator
    supplies either an image or video shot; provenance retains model, prompt,
    seed and parameters and the plan uses video.
  - Mocked local generation downloads missing weights into the cache and
    reuses its loaded pipeline on subsequent calls. Failed loading/inference
    produces an actionable provider failure and ultimately `missing_asset`.
- **Related:** CF-REQ-215, CF-REQ-217, CF-REQ-264–265, CF-REQ-664, ADR-013, ADR-019

### CF-REQ-209 — Deterministic fallback card

- **Description:** Owner revision (2026-10-07): normal Runs shall not fill missing media with text on a plain-colour background. Each shot uses relevant licensed media accepted by candidate review; existing plain title-card Assets are excluded from automatic selection and cannot pass the composition gate.
- **Failure:** If no suitable media can be selected, persist a blocking `missing_asset` issue with the Visual Segment index, retain the selected media for other shots, and route to bounded reselection. If retries are exhausted, the Run remains unsuccessful and its retained work is available for owner review; no plain card or unreviewed substitute is silently rendered or approved.
- **Retained-edit boundary:** Deterministic card rendering remains available to explicit saved-content revisions, including photo-backed cards under CF-REQ-361. Such revisions do not alter this automatic Run policy or inherit approval.
- **Acceptance:**
  - When all providers return nothing, the affected shot has a blocking `missing_asset` evaluation and no fallback card is created.
  - A rejected or unavailable candidate is not replaced by an unreviewed library image; other selected shots are retained during reselection.
  - Legacy title-card Assets are not selected automatically and fail the composition gate if referenced by a retained plan.
  - The same text and style produce a byte-identical card image.
- **Related:** CF-REQ-219, CF-REQ-252, CF-REQ-257, CF-REQ-361, CF-REQ-407, CF-REQ-411

### CF-REQ-210 — Downloaded media validation

- **Description:** Every downloaded or generated file shall be validated
  before being stored as `active`.
- **Behaviour:** Enforce size limits (`assets.max_*_bytes`) while streaming;
  detect type from content (magic bytes + FFprobe), ignoring the remote
  `Content-Type`; reject undecodable media; require images with short side
  ≥ `assets.min_image_short_side_px` and videos with height ≥
  `assets.min_video_height_px`, duration > 0 and a decodable video stream.
- **Failure:** Rejected files are deleted and the reason recorded; nothing is stored.
- **Acceptance:**
  - A `.jpg` URL returning HTML is rejected as `invalid_media`.
  - A 400×300 image is rejected as `resolution_too_low`.
  - A response exceeding the size limit is aborted before completing the download.
- **Related:** CF-NFR-104, CF-NFR-105

### CF-REQ-211 — Store for future reuse

- **Description:** Acquired and generated Assets that pass validation shall be
  stored with `reusable = true`, a description, normalised tags and subjects
  (from provider metadata and the asset requirement), and an initial
  `quality_score`.
- **Acceptance:**
  - An Asset acquired in Run 1 is found by library search in Run 2 for the same requirement without external calls.

### CF-REQ-212 — Usage tracking

- **Description:** When a Clip is approved, `AssetUsage` records shall be
  final and `usage_count` / `last_used_at` of each used Asset updated.
- **Acceptance:**
  - Assets used only by rejected Clips keep `usage_count` unchanged.

### CF-REQ-213 — Asset status management

- **Description:** The user shall be able to set an Asset's status to
  `quarantined` or `retired` and edit its tags and description. Only `active`
  Assets are selectable.
- **Acceptance:**
  - After retiring an Asset via API, library search never returns it.
- **Related:** CF-REQ-605

### CF-REQ-214 — Retention of working files

- **Description:** Per-Run working files shall be deleted
  `retention.work_dir_retention_days` after the Run finishes, and rejected
  Clip files `retention.rejected_clip_retention_days` after rejection.
  Reusable Assets and approved Clips are never deleted automatically.
- **Acceptance:**
  - A cleanup task with a fake clock removes an 8-day-old work directory and leaves reusable Assets intact.

### CF-REQ-215 — Real people and generated media [Derived]

- **Description:** Real, identifiable people (e.g. a public figure named in
  the Story) may appear only through real, licensed external or imported
  media (photos/footage with provenance). Generated media shall be used only
  as illustrative or abstract visuals and shall not depict real, identifiable
  people or be presented as footage of the reported event.
- **Rationale:** Owner decision (2026-09-28). Realistic synthetic depictions of
  real people are a deepfake risk and are restricted by platform policies.
- **Behaviour:** Asset requirements whose subjects include a named person use
  strategy `acquire_only` (library/external media, never generation);
  generation prompts include the constraint; semantic evaluation checks it
  (issue `misleading_generated_media`); generated Assets are tagged
  `generated` and set the disclosure flag (CF-REQ-162).
- **Acceptance:**
  - A requirement with subject `Elon Musk` never calls an `ImageProvider`/`VideoProvider`; a licensed Wikimedia Commons photo is acceptable.
  - The generation prompt template contains the constraint (unit test).
  - A fake evaluator issue `misleading_generated_media` routes to `reselect_asset`.
- **Related:** CF-REQ-251, CF-REQ-406

### CF-REQ-216 — Manual asset import

- **Description:** The system shall import local media files (e.g. a
  royalty-free music library) with user-supplied provenance (licence
  mandatory) via API upload and a CLI command.
- **Acceptance:**
  - Importing a directory of 3 MP3 files with a licence creates 3 `music` Assets with `origin = imported`.
  - Importing without a licence is rejected.
- **Related:** CF-REQ-320

### CF-REQ-217 — ComfyUI workflow generation

- **Description:** The ComfyUI adapters shall generate images and videos by
  submitting owner-supplied workflow JSON templates (exported from ComfyUI in
  API format) from `COMFYUI_WORKFLOWS_DIR` to the local ComfyUI
  server, filling documented placeholders, polling for completion, and
  downloading the output.
- **Behaviour:** Each template has a sidecar manifest
  (`<name>.workflow.json` + `<name>.manifest.json`) declaring media type
  (`image`/`video`), output node, and which node inputs receive `prompt`,
  `negative_prompt`, `width`, `height`, `seed`, `duration_seconds`/`frames`.
  Templates are validated at startup; invalid templates are reported and
  ignored. Wan models may run inside ComfyUI templates or through the native
  `wan_local` adapter (diffusers), which is an independent provider.
  Local generation runs outside the event loop and is bounded by
  `workflow.stage_timeout_seconds`.
- **Failure:** Server unreachable ⇒ transient `ProviderError`; out-of-memory
  or node errors ⇒ permanent `ProviderError` (`generation_failed`), and the
  next provider in the profile order is tried.
- **Acceptance:**
  - With a mocked ComfyUI HTTP API, a template with placeholders produces a request whose node inputs contain the prompt, size and seed.
  - A template missing its manifest is reported at startup and never used.
- **Related:** CF-REQ-208, OD-005, [provider-architecture](architecture/provider-architecture.md#imageprovider--videoprovider)

### CF-REQ-218 — Bounded licensed media previews

- **Description:** Candidate review shall use provider-permitted thumbnails and representative video previews, subject to `visual_review.*` limits and safe HTTP/media validation.
- **Behaviour:** Previews retain candidate/scene IDs, provenance and timestamps, remain separate from selected full Assets, and respect provider download/tracking/licence rules. Deterministic downselection preserves required scene coverage. A missing permitted preview, unsupported modality or exhausted evidence limit is explicit; no hidden unbounded download or extra review loop is allowed.
- **Acceptance:** Only permitted bounded preview bytes are fetched before selection; a preview exceeding the limit is aborted; full video is not downloaded merely to review every search result.
- **Related:** CF-REQ-201, CF-REQ-207, CF-REQ-210

### CF-REQ-219 — Batched visual-candidate review

- **Description:** Quality-mode `select_assets` shall make one structured `review_media_candidates` request for the bounded candidate set, using the configured image-capable review model through `LLMProvider`.
- **Behaviour:** Input binds previews, scene/Claim intent and candidate IDs. Output records evidence-backed relevance, location/identity consistency, archive/illustrative status and framing suitability, with uncertainty. The review is not a source of new facts or authoritative identity. Code rejects unknown IDs and chooses eligible candidates deterministically. Missing evidence requires owner review; review failures do not approve unseen media.
- **Failure:** Output errors follow bounded repair policy; quota, modality or cost failure preserves work and marks quality review pending. Every request counts against request and monetary limits.
- **Acceptance:** True Mokha location imagery beats coffee for the Mokha fixture; an irrelevant first-provider result loses to a relevant later result; an unverified person remains pending; all candidate previews enter one initial request, not one request per image.
- **Related:** CF-REQ-260, CF-REQ-666, CF-REQ-668–671

### CF-REQ-220 — Versioned reusable media judgments

- **Description:** Candidate judgments shall be cached with content/metadata hashes, intent/evidence references, model, prompt and review-policy versions.
- **Behaviour:** Unchanged inputs reuse valid evidence without another paid call. Changed identity, media, intent or review policy invalidates only affected judgments. Owner-confirmed judgments record actor, evidence and time separately from model judgments; neither is silently substituted for the other.
- **Acceptance:** An unchanged saved-package rerender makes zero candidate-review requests; changed person identity cannot reuse a stale approval; cache hits and misses are visible in Run Events and budget accounting.
- **Related:** CF-REQ-219, CF-REQ-412
