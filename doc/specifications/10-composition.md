# 10 — Composition

Covers stage `compose_clip`. FFmpeg is the baseline media-processing tool.
Architecture: [architecture/application-architecture.md](architecture/application-architecture.md#composition),
decision [ADR-007](decisions/ADR-007-720p-mobile-first-output.md).

## Default output

| Property | Value | Configurable via |
| --- | --- | --- |
| Resolution | 720 × 1280 | `ContentProfile.output` |
| Aspect ratio | 9:16, square pixels (SAR 1:1) | fixed in v1.0 |
| Frame rate | 30 FPS constant | `ContentProfile.output.fps` |
| Duration | 60–90 s inclusive by default | `ContentProfile.duration` |
| Container | MP4 with `+faststart` | fixed |
| Video | H.264, `yuv420p`, CRF 23, preset `medium` | `composition.*` |
| Audio | AAC, 128 kb/s, 48 kHz, stereo | `composition.*` |

**Why 720p:** Clips are consumed on phones, where the perceptual difference
between 720p and 1080p is small for this content, while 720p roughly halves
pixel count per frame, reducing encode time, storage and upload size.

## Requirements

### CF-REQ-350 — Composition specification

- **Description:** `compose_clip` shall first build a `CompositionSpec` — a
  pure data structure listing segments (Asset storage keys, time ranges,
  fit mode, motion, transitions), narration, music, caption file, output
  settings — and store its SHA-256 as `Clip.composition_spec_hash`.
- **Behaviour:** Building the spec is pure code with no I/O; rendering
  consumes the spec only.
- **Acceptance:**
  - Identical Story Package version, Assets, narration, captions and settings produce an identical spec hash.
- **Related:** CF-REQ-357

### CF-REQ-351 — Encoding parameters

- **Description:** The final Clip shall be encoded with the `composition.*`
  settings listed in [18-configuration.md](18-configuration.md#composition).
- **Acceptance:**
  - FFprobe of the output reports `h264`, `yuv420p`, `aac`, 48 000 Hz.

### CF-REQ-352 — Output format

- **Description:** The Clip shall be exactly `output.width × output.height`
  with SAR 1:1 at constant `output.fps`, in an MP4 container with the moov
  atom at the start.
- **Acceptance:**
  - Probe reports 720×1280, `r_frame_rate = 30/1`, `avg_frame_rate = 30/1`.
- **Related:** CF-REQ-402

### CF-REQ-353 — Safe FFmpeg execution

- **Description:** FFmpeg and FFprobe shall be invoked only through a single
  runner module that passes argument lists (never a shell), restricts
  protocols to local files, enforces a timeout, and captures stderr.
- **Acceptance:**
  - No code path calls `subprocess` with `shell=True` (architecture test).
  - A concat list containing `http://` entries is rejected by the runner.
- **Related:** CF-NFR-102

### CF-REQ-354 — Clip timing

- **Description:** Clip duration shall equal
  `lead_in_seconds + narration_duration + tail_seconds` (± one frame);
  narration starts at `lead_in_seconds`.
- **Acceptance:**
  - 70.0 s narration with defaults yields a 71.3 s Clip (± 0.034 s).
- **Related:** CF-REQ-304

### CF-REQ-355 — Segment rendering and transitions

- **Description:** Each Visual Segment shall be rendered to an intermediate
  file at output resolution and FPS (fit mode, motion), then joined with the
  planned transitions; transition overlaps are compensated so segment
  boundaries match CF-REQ-256.
- **Acceptance:**
  - A 3-segment spec with two 0.4 s crossfades produces a Clip whose duration equals the narration-based duration.
- **Related:** CF-REQ-254, CF-REQ-255

### CF-REQ-356 — Loudness

- **Description:** Narration shall be loudness-normalised to
  `composition.narration_loudness_lufs` (default −14 LUFS integrated, true
  peak ≤ −1.5 dBTP) before mixing with music.
- **Acceptance:**
  - Measured integrated loudness of the final Clip is within ±1.5 LU of the target.

### CF-REQ-357 — Reproducibility

- **Description:** Rendering the same `CompositionSpec` with the same FFmpeg
  version shall produce the same FFmpeg command lines and a Clip with
  identical probe metadata (dimensions, FPS, codecs, duration ± one frame).
- **Rationale:** Byte-identical output across machines is not guaranteed by
  encoders; command-level determinism is.
- **Acceptance:**
  - Unit test: the command builder returns identical argument lists for identical specs.

### CF-REQ-358 — Atomic output

- **Description:** The final Clip shall be written to a temporary name in the
  Run work directory and moved to its storage key only after FFmpeg exits
  successfully and the file is probed.
- **Acceptance:**
  - A killed render leaves no file under the Clip storage key.

### CF-REQ-359 — Composition failures

- **Description:** When FFmpeg fails while rendering a segment, the offending
  Asset shall be quarantined and issue `asset_render_failed` shall route to
  `reselect_asset` for that segment. Any other FFmpeg failure fails the stage
  with `composition_failed` and the last 50 lines of stderr (secret-free) in
  the Run Event.
- **Acceptance:**
  - A corrupt fixture image causes quarantine and reselection, not a Run failure, while retries remain.
- **Related:** CF-REQ-410

### CF-REQ-360 — Layered news composition contract

- **Description:** The immutable CompositionSpec shall include ordered visuals, editorial Overlay Cues, subtitles, narration/music/SFX Audio Cues, motion/keyframe presets, template versions and platform-safe layout identifiers.
- **Behaviour:** Deterministic rendering consumes this contract only; basic graphics use local fonts/assets and FFmpeg, not generation providers. Required credits/disclosures remain intact. Every output records Story Package and render revision, input hashes and composition hash; deterministic planning does not create an external overlay-provider abstraction.
- **Acceptance:** The same saved inputs yield the same command/spec hash; missing referenced media blocks rendering; changing an overlay updates the composition hash without changing narration bytes.
- **Related:** CF-REQ-259–262, CF-REQ-324–325, CF-REQ-350, CF-REQ-357

### CF-REQ-361 — Saved-package preview and targeted rerender

- **Description:** The application shall expose an in-repository use case, API and CLI for previewing and rerendering a retained Story Package without repeating unchanged research, script, TTS or transcription calls.
- **Behaviour:** Revisions preserve immutable prior inputs, record changed fields, validate dependencies and regenerate only affected outputs. Presentation-only edits may create new visual judgments/render output but not new research or narration. Script edits invalidate narration/alignment; changed media/identity invalidates affected reviews; any material output change invalidates approval. A failed original Run remains failed; a new render is not a fabricated successful Run.
- **Optional brand mark:** A revision may reference an active, licensed imported image Asset as a brand mark. The renderer shall preserve its aspect ratio and alpha, fit it within 112 × 112 px at 720 px output width, and place it 24 px from the top and right edges for the entire Clip. The rendered revision records the Asset hash and remains pending review; the base Clip and its output are unchanged.
- **Card background photo:** A revision may replace the plain background of a fallback text card with an active, licensed image Asset. The card keeps its original text, the photo covers the frame with its upper part visible, and a darkening gradient keeps the text readable above the subtitles. The photo's attribution joins the revision credits. A photo of a real person must come from a source that identifies that person (CF-REQ-215, CF-REQ-260).
- **Acceptance:** Label-only rerender makes zero research/write-script/TTS/transcription requests; corrected script produces new audio only when its text changed; previous video remains retrievable; the workflow runs without temporary driver scripts.
- **Acceptance:** A logo-only revision with an active PNG Asset places its visible pixels within the specified top-right bounds across the full timeline, preserves transparent pixels, changes the composition hash, leaves narration unchanged, makes zero provider calls, preserves the original Clip, and returns `pending_review`.
- **Related:** CF-REQ-152, CF-REQ-220, CF-REQ-302, CF-REQ-412

### CF-REQ-362 — Platform-safe presentation variants

- **Description:** A Clip may have versioned presentation variants for YouTube, Instagram, TikTok and Facebook, bound to the same grounded content and explicit platform/template settings.
- **Behaviour:** Safe-zone/layout or supported metadata changes are not new facts. Each published file references the exact reviewed revision, layout version and hash. Platform-control masks are owner-reviewed versioned data; they are not assumed permanently correct. Variant edits invalidate affected review; quality work and storage/compute costs remain attributable to the Clip.
- **Acceptance:** Every variant passes its configured overlay/subtitle masks at the declared resolution; publishing cannot select an unreviewed variant hash; unavailable platform capability is reported rather than emulated.
- **Related:** CF-REQ-261, CF-REQ-360–361, CF-REQ-451
