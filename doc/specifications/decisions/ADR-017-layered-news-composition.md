# ADR-017 — Layered deterministic news composition

- **Status:** Accepted direction; owner authorized the modern news-explainer quality plan and implementation on 2026-10-06. Exact branding and numeric creative defaults await reference-set review.

## Context

Narration-driven splitting, generic stock matching and subtitle-only composition do not provide the requested editorial labels, meaningful animation, sound effects or coherent news storytelling. The existing native FFmpeg workflow already renders and validates media; changing frameworks is not justified merely to draw labels or mix cues.

## Decision

- Extend the existing writing draft with evidence-bound Narrative Beats and Shot Intent. Code validates/normalizes plans and reconciles word timing; it does not infer facts or call a model per graphic/sound cue.
- Keep FFmpeg as the deterministic renderer. Extend CompositionSpec with independent editorial-overlay and audio-cue tracks, versioned keyframe/style presets, verified identity anchors and platform-safe layout identifiers.
- Separate spoken-word captions from person/place/source/quote/number labels. Measure fonts, enforce contrast/collisions/readable dwell, retain mandatory attribution and clearly label archive/illustrative media.
- Add licensed local SFX metadata/import and timed cues, reusing Asset provenance/storage. Mix narration/music/SFX into one stereo AAC stream, with smooth bounded fades/ducking and final output measurements. Never present illustrative effects as actual event recordings.
- Provide in-repository retained-package preview/rerender with explicit input-hash invalidation and durable revision/review history. Do not replace it with temporary drivers or fabricate successful Runs.
- No new external overlay provider, second durable database, microservice or runtime agent framework is required. A future alternate motion renderer requires a measured limitation and a separate approved ADR.

## Consequences

Domain value objects, persisted revisions, review UI and composition tests must evolve together. Static reading-focused graphics are valid; more effects do not imply higher quality. Approval binds to the exact output and is invalidated by material changes.

## Alternatives Considered

- Subtitle-only slides and constant Ken Burns: insufficient explanatory hierarchy and editorial intent.
- Generated badges/one LLM call per effect: unnecessary cost and coupling for deterministic work.
- Immediate renderer/framework migration: adds complexity before demonstrating a concrete limitation.
