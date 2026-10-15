# ADR-020 — Local portrait framing

## Status

Accepted direction (owner requested face-centred portraits on 2026-10-14).

## Context

Centre-cropping verified person stills puts faces beneath the existing top
information banner. The owner requests centred faces without changing that
banner, for Football and World (CF-REQ-255). Source dimensions cannot locate
faces reliably.

## Decision

Use `opencv-python-headless` only in infrastructure to detect a confident,
dominant frontal face using its packaged Haar cascade. No network, downloaded
model or identity inference is involved. Normalized validated bounds are
source-hash-bound positioning evidence in the composition contract.

Owner feedback refinement (2026-10-14): prefer face-safe edge-to-edge cover
cropping; exact face-centred contain scaling looks like an inset rectangle.
Use the active top banner's bounds to retain headroom above the whole face
in the upper-middle frame. Bound enlargement to 60% output width and 32%
output height. When cover is unsafe, use only necessary blurred padding,
preferring sharp full-width imagery instead of side margins, with feathered
top/bottom edges outside the face bounds to avoid a hard inset seam. Keep portrait
shots still so motion cannot undo the crop. Keep editorial overlays unchanged.
Version this policy in the render hash. Normal Runs and saved rendering share the same
framing helper. Owner correction (2026-10-15): missing or ambiguous detection
fits the complete sharp portrait below the active banner over blurred padding,
without motion, and records an explicit warning rather than inventing bounds.
This prevents a detector miss from reverting to the face-obscuring centre crop.

## Consequences

A concrete CF-REQ-255 consumer justifies the local OpenCV dependency. Haar
detection can miss profiles/occluded faces; this is surfaced, not reported as
successful centring. Existing approved media is not overwritten.

## Alternatives considered

- Fixed vertical offsets: cannot reliably position varying source photos.
- LLM or remote face analysis: unnecessary cost, variability and disclosure
  for deterministic positioning.
- Full video tracking: outside the owner-requested still-image scope.
