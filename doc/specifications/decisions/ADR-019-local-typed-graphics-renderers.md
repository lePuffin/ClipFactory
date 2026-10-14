# ADR-019 — Local typed renderers for infographic and scientific graphics

- **Status:** Accepted; owner-authorized direction, 2026-10-08.

## Context

ClipFactory needs useful authored infographic and mathematical/scientific
visual Assets. The existing plan only specifies acquired/generated media and
deterministic FFmpeg composition; it has no safe typed contract or local
template renderer for these graphics. Executable model-authored graphics
content would cross a security boundary, and routing graphics through
provider-order fallback could silently turn a chart request into unrelated
generated media.

Owner refinement (2026-10-08): CF-REQ-266 caps native Wan calls per Run.
A media Visual may carry a separate bounded graphics fallback in the existing
writing response. Runtime may select that accepted-Claim-grounded alternative
after acquisition/Wan is exhausted, routing its typed template to the same
renderer. This does not permit arbitrary conversion of footage to a chart,
unverified science, executable content, or fallback from a failed graphics
renderer to Wan.

## Decision

- Use local HyperFrames for the finite infographic templates and local Manim
  for the finite mathematical/scientific templates. Route by the typed
  `VisualPlan` kind in code; do not use `VIDEO_PROVIDERS`/`IMAGE_PROVIDERS`
  ordering for graphics.
- Keep media Assets on their existing reuse/acquisition/allowed-generation
  path, including native Wan behavior. Do not fall back from a graphics
  renderer failure to Wan, another media generator, a placeholder, authored
  SVG, or FFmpeg-authored graphics.
- Extend the existing `VideoProvider` request with an optional
  provider-neutral, typed graphics specification. Do not add a provider port.
  Adapters invoke trusted bounded templates only; no model-authored HTML,
  SVG, Python, JavaScript, arbitrary code/formulas or remote URLs are passed
  to a renderer.
- First useful templates: statistic, comparison and timeline infographics;
  bounded function plots and relationship diagrams for mathematics/science.
  A map is permitted only against supplied, verified geometry; no inferred or
  invented geography. Factual labels, values and observations cite accepted
  Claims. A plotted code-defined mathematical function is explicitly not
  empirical data.
- Preserve `allow_generated_media` and the `generate_allowed` strategy as
  required permission for a new graphics render; preserve the ban on generated
  depictions of identifiable real people.
- Treat output as a rendered video Asset and use existing validation, probe,
  provenance, import, content-addressed persistence, reuse and failure
  recovery. Do not publish directly from a renderer. FFmpeg remains the final
  assembly/probe tool and may be used internally by a renderer for encoding;
  it is not an authoring fallback.
- Keep HyperFrames as a pinned local Node package, isolated from backend
  Python dependencies. Keep Manim in an optional `graphics-manim` Python
  dependency group so ordinary install remains lightweight. Executable paths,
  graphics FPS and bounded renderer timeout are canonical runtime
  configuration.
- Use the existing silent watchdog renewal for active rendering. Optional
  UI progress is based only on measured rendered frames; watchdog heartbeat is
  neither a persisted event nor user-visible progress. Cancellation is bounded
  and scoped to the specific renderer subprocess. A failed renderer never
  creates a successful Asset or publication.

## Consequences

`write_script`'s existing structured response and `VisualPlan` gain a typed
graphics payload; this adds no LLM request. `select_assets` makes deterministic
adapter selection and retains the existing media path. The adapters and
trusted templates live in infrastructure, while the domain carries only
provider-neutral typed values. Local setup must install the pinned Node
package and optional Manim group for real rendering. Missing executable,
unsupported template, invalid evidence or renderer failure is explicit;
integrations are not claimed validated until exercised.

This supersedes only ADR-017's renderer decision for authored infographic and
scientific graphic Assets. ADR-017's FFmpeg final composition, overlays,
motion/transitions, audio mixing, review and publication decisions remain
unchanged.

## Alternatives considered

- Use FFmpeg filters/SVG strings as the graphic authoring system: rejected;
  they do not provide the requested trusted typed template boundary.
- Send model-authored HTML, SVG, Python or JavaScript to a renderer: rejected
  as unsafe and non-deterministic.
- Route graphics through ordinary provider order or fall back to Wan: rejected
  because it obscures intent and can substitute unrelated video.
- Add a new renderer port: rejected because the existing `VideoProvider`
  request has a concrete consumer and can carry the optional neutral
  specification.
