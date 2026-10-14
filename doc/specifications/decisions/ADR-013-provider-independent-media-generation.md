# ADR-013 — Provider-independent media generation; deterministic motion

- **Status:** Proposed

## Context

Generated images/video can fill gaps in stock media, but providers change
quickly and generation is costly. Basic motion (pan, zoom, Ken Burns,
transitions) is trivial to render deterministically.

## Decision

- Generation only through `ImageProvider` / `VideoProvider`. v1.0 adapters
  (owner decision, OD-005): local **ComfyUI** (owner-supplied workflow
  templates, images and video, including Wan workflows), local **Wan** via
  diffusers (video), and **Higgsfield** cloud (images and video), plus `fake`.
- The order in which providers are tried is a Content Profile setting
  (`generation`); the asset manager implements fallback and budget-driven
  degradation (CF-REQ-208, CF-REQ-664).
- Generation is used only when the profile allows it and no reused or
  acquired Asset fits; generated Assets store `GenerationInfo`, are marked for
  disclosure, and must not depict real identifiable people or pose as event
  footage — real people appear only through licensed real media (CF-REQ-215).
- Heavy local dependencies (PyTorch, diffusers) live in an optional
  dependency group so the default install stays light.
- All motion and transitions are FFmpeg filters with fixed formulas (CF-REQ-252).

## Consequences

- The workflow does not care which provider produced an Asset.
- Suitable stock media keeps generation optional. If both stock and permitted
  generation fail, missing shots remain blocking; automatic plain cards are
  prohibited by the owner revision of CF-REQ-209.
- Owner revision (2026-10-07): native Wan video may fill either shot type and
  lazily downloads missing official weights into a local cache outside Git.
  `reuse_first` permits this native fallback after stock selection fails;
  `acquire_only` and named-person restrictions remain enforced.
- The reference host's small GPU makes local video generation slow or
  impossible for larger models; Higgsfield is the practical video path, local
  generation is best-effort.

## Alternatives considered

- AI video for motion effects: expensive and non-deterministic for no gain.
- A single generation vendor: rejected; the owner wants local and cloud options.
- Depending on OpenMontage's tool registry and scored provider selector: it
  inspired the provider list and budget governance, but it is AGPL-licensed,
  agent-driven and far broader than needed; a profile-ordered fallback list is
  sufficient.
