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
