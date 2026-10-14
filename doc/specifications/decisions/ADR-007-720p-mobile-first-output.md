# ADR-007 — 720×1280, 30 FPS mobile-first output

- **Status:** Proposed

## Context

Clips are consumed on phones in vertical format. Higher resolution increases
render time, storage and upload size.

## Decision

Default output is 9:16, 720 × 1280, 30 FPS constant, H.264/AAC MP4. Width,
height and FPS are Content Profile settings; the 9:16 ratio is fixed in v1.0.

## Consequences

- Roughly half the pixels of 1080 × 1920: faster rendering and smaller files.
- Little expected perceptual difference on phones for news content made of
  photos, B-roll and captions.
- Source media must have short side ≥ 720 px (CF-REQ-210).
- Moving to 1080p later is a configuration change plus re-validation of
  caption sizes and performance targets.

## Alternatives considered

- 1080 × 1920: more processing and storage without a demonstrated benefit for this use case.
- 60 FPS: unnecessary for mostly still/slow-motion news visuals.
