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
   └─4─► deterministic title card (rendered) ──────────────────────────────────► fallback_card
```

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
  - A generated Asset without `GenerationInfo` raises a domain error.
- **Related:** ADR-011

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

- **Description:** When the library has no suitable Asset, the system shall
  query configured `MediaSourceProvider`s with the requirement's description,
  subjects and media type, request up to `assets.candidates_per_search`
  candidates each, and download only the chosen candidate.
- **Behaviour:** Candidates carry provenance fields from the provider
  (URL, author, licence, attribution, media type, dimensions, duration).
  The chosen candidate is determined in code (no LLM): score =
  term overlap between the requirement (subjects, tags, description) and the
  candidate's provider metadata, plus bonuses for portrait-friendly shape
  (height ≥ width or short side ≥ 720 px), required media type, and the
  provider's own relevance rank.
- **Failure:** Provider errors are recorded and the next provider or step is tried.
- **Acceptance:**
  - With a fake provider returning 3 candidates, only the chosen one is downloaded.
  - A provider raising a transient error is retried per call-retry policy, then skipped.
- **Related:** CF-REQ-210, [provider-architecture](architecture/provider-architecture.md#mediasourceprovider)

### CF-REQ-208 — Media generation

- **Description:** When no library or external Asset is chosen, the system
  may generate an image or video through `ImageProvider` / `VideoProvider`
  only if the Content Profile `visual_style.allow_generated_media` is true
  and the requirement strategy is `generate_allowed`.
- **Behaviour:** Providers are tried in the order of the Content Profile
  `generation.image_providers` / `generation.video_providers`, skipping
  providers not enabled in the environment or not reachable (`is_configured()`
  false, or ComfyUI server down). Before each paid call the budget check of
  CF-REQ-662/CF-REQ-663 applies; a provider whose estimated cost would exceed
  a limit is skipped (degradation, CF-REQ-664). If every provider fails or is
  skipped, the segment falls through to CF-REQ-209. The generated Asset stores
  `GenerationInfo` (provider, model, prompt, parameters, seed; plus workflow
  name for ComfyUI).
- **Acceptance:**
  - With `allow_generated_media = false`, no generation fake is called.
  - With profile order `[comfyui, higgsfield]` and ComfyUI unreachable, Higgsfield is called once and the Asset records `provider = higgsfield`.
  - With order `[higgsfield, comfyui]` and a remaining per-Clip budget below the Higgsfield estimate, ComfyUI is used and a `warning` event `budget_degraded` is emitted.
- **Related:** CF-REQ-215, CF-REQ-217, CF-REQ-664, ADR-013

### CF-REQ-209 — Deterministic fallback card

- **Description:** When no Asset can be reused, acquired or generated for a
  segment, the system shall render a title card (styled background, key text
  of the segment) deterministically, stored as an Asset with `origin = rendered`.
- **Acceptance:**
  - A plan where all providers return nothing still composes a valid Clip using title cards.
  - The same text and style produce a byte-identical card image.
- **Related:** CF-REQ-252

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
