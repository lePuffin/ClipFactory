# ClipFactory v0.2.0 — Agent Implementation Prompt
## Dynamic, Scene-Aware Smart Crop / Virtual Camera

You are implementing ClipFactory v0.2.0.

ClipFactory is a local-first personal tool that takes either a local video file or a YouTube URL, identifies the best moments, and renders them as vertical 9:16 clips. Version v0.1.x already exists. Improve the existing Smart Crop implementation without unnecessarily rewriting working functionality.

## Primary objective

Upgrade Smart Crop from a mostly/static crop into a dynamic, temporally smoothed, scene-aware smart framing system.

The final vertical clip should behave like a virtual camera that follows the relevant subject smoothly over time:

- At the beginning, the speaker may be centered.
- If the speaker moves left/right, framing follows.
- When a scene changes, tracking is reconsidered/reset.
- A new relevant subject can become the framing target.
- Detection/tracking failures must degrade gracefully instead of producing unstable crops.

The implementation must remain local and must not introduce unnecessary cloud services.

## 1. Before changing code

1. Inspect the existing repository thoroughly.
2. Understand the current v0.1.x pipeline and Smart Crop implementation.
3. Reuse existing abstractions where sensible.
4. Do not rewrite unrelated working components.
5. Preserve the existing public API and UI behaviour unless a change is required.
6. Add tests for the new behaviour.
7. Keep the framing subsystem modular.
8. Never allow LLM output or untrusted input to become shell commands directly.
9. Do not introduce ComfyUI for this feature.
10. Do not add auth, multi-user support, cloud processing, social publishing, captions, B-roll, or unrelated features.

If the repository differs from assumptions below, adapt to its actual architecture.

## 2. Desired architecture

Conceptually:

    Input video
        |
        v
    Scene Detection
        |
        v
    Subject Detection
        |
        v
    Subject Tracking
        |
        v
    Subject Selection
        |
        v
    Camera Path Generation
        |
        v
    Camera Path Smoothing
        |
        v
    9:16 Rendering
        |
        v
    Output MP4

Keep these responsibilities separated where practical:

- scene detection
- subject detection
- subject tracking
- subject selection
- camera trajectory generation
- camera trajectory smoothing
- rendering

Prefer simple, testable components over excessive abstraction.

## 3. Dynamic crop

The crop must no longer necessarily remain fixed for the entire clip.

The virtual camera must be able to change horizontal and, where useful, vertical framing over time.

Represent the framing independently from FFmpeg rendering. Conceptually:

    time -> target position

Example:

    0.0s -> x=920
    5.0s -> x=970
    10.0s -> x=1050
    15.0s -> x=980

The exact internal representation may differ.

## 4. Subject detection

Use an existing suitable local computer-vision dependency if one already exists.

If no suitable detector exists, introduce a lightweight local detector suitable for person/face detection and tracking.

Preferred approach:

- person/face detection
- tracking across frames
- no custom model training

Possible technologies include YOLO + ByteTrack/BoT-SORT or another lightweight equivalent, but inspect the repository first and do not blindly add a large model.

The common talking-head/person-centered case should work reliably.

## 5. Temporal sampling

Do not run expensive full object detection unnecessarily on every frame.

Use configurable detection intervals/sampling.

For example:

    30 FPS source
    detection approximately every 0.25–0.5 seconds
    tracking/interpolation between detections

Keep the interval configurable and use sensible defaults.

## 6. Tracking

The same subject should remain associated across successive detections.

The tracker should tolerate:

- small movements
- detection jitter
- short detection failures
- moderate subject movement

Expose enough tracking information for framing:

- subject identity
- bounding box
- confidence
- timestamp/frame
- tracking validity

Tracking must not randomly switch between people.

## 7. Subject selection

When multiple people/subjects exist, use deterministic heuristics.

At minimum consider:

- detection confidence
- subject size/prominence
- proximity to current camera target
- continuity with the previous tracked subject

Prefer continuity over constantly switching targets.

Use hysteresis or an equivalent mechanism to avoid target thrashing.

If one obvious person exists, select that person.

If no reliable subject exists, fall back gracefully.

## 8. Scene detection

Make framing scene-aware.

A significant scene cut should cause tracking to be reconsidered.

Conceptually:

    Scene 1 -> track Subject A
    CUT
    Scene 2 -> reset tracking -> detect/select again

Do not let tracking from the previous scene force the crop onto an unrelated subject.

Reuse existing scene detection if available. Otherwise use a lightweight local approach compatible with the project, such as FFmpeg, OpenCV, PySceneDetect, or another appropriate solution.

Avoid heavy dependencies unless necessary.

## 9. Camera trajectory

Convert tracking data into a virtual camera trajectory.

Keep the subject comfortably inside the 9:16 frame rather than exactly on an edge.

For talking heads, allow reasonable headroom and side margin.

Do not overreact to tiny bounding-box changes.

The camera should move only when necessary.

## 10. Camera smoothing

This is critical.

Raw tracking coordinates MUST NOT be applied directly to the crop.

Use temporal smoothing, for example:

- exponential moving average / low-pass filtering
- interpolation between keyframes
- velocity limiting
- or a combination

Example:

Raw:
    920, 925, 918, 940, 930, 965

Smoothed:
    920, 922, 921, 927, 928, 935

Expose sensible parameters for:

- smoothing strength
- maximum camera movement speed
- minimum movement threshold

Avoid visible jitter.

## 11. Dead zone

Implement a small framing dead zone.

If the subject moves only slightly, the virtual camera should not move.

Conceptually:

    movement < threshold -> keep current camera position
    movement >= threshold -> smoothly follow

Make the threshold configurable.

## 12. Camera constraints

The crop window must never leave source-image bounds.

Clamp final crop coordinates to valid bounds.

Handle source aspect ratios correctly while maintaining the existing output requirements:

- 9:16
- 1080x1920 where supported
- MP4
- H.264
- AAC

Do not regress existing rendering behaviour.

## 13. Fallback behaviour

Recommended hierarchy:

    reliable tracked subject
        -> dynamic smart framing

    tracking temporarily uncertain
        -> retain last reliable target
        -> hold/reduce camera movement

    no reliable target
        -> static crop using best available position

    no subject information
        -> center crop

Never produce invalid crop coordinates.

Never fail the whole job merely because tracking failed for part of a clip.

## 14. Scene transitions

After a scene cut:

1. Detect/select the new target.
2. Establish new desired framing.
3. Transition in a controlled way where practical.
4. Avoid excessive animation.

For very different compositions, a relatively fast transition is acceptable, but it must not visibly jitter.

## 15. Rendering

Inspect the existing renderer first.

Prefer integrating the camera trajectory into the current FFmpeg rendering pipeline.

Possible approaches include:

- FFmpeg crop expressions
- generated keyframes
- segmented rendering
- another deterministic method

Choose the simplest robust solution.

Do not render thousands of tiny segments unless necessary.

The renderer should consume framing/camera data; detection and tracking logic should not live inside the renderer.

## 16. Configuration

Use the project's existing configuration mechanism.

At minimum consider configurable:

- output width/height
- detection interval
- detection confidence threshold
- tracking confidence threshold
- smoothing strength
- dead-zone threshold
- maximum camera movement speed
- scene-change threshold
- fallback behaviour

Provide sensible defaults so manual configuration is not required.

## 17. Performance

Target the user's laptop-class hardware with an NVIDIA RTX PRO 500 Black GPU and approximately 6 GB VRAM.

Priorities:

1. correctness
2. visual quality
3. stability
4. reasonable processing time
5. optimisation

Do not use ComfyUI/WAN for smart crop.

Do not require an NPU.

GPU acceleration may be optional. Keep a CPU-compatible fallback where reasonably practical.

## 18. Testing

Add unit tests for:

### Camera trajectory
- stationary subject
- movement left
- movement right
- movement back and forth
- crop boundary clamping

### Smoothing
- jittery input
- small movements inside dead zone
- large movement
- maximum velocity limiting

### Subject selection
- one subject
- multiple subjects
- confidence differences
- continuity preference
- temporary detection loss

### Scene changes
- target reset after scene cut
- stale target not carried into new scene

### Fallback
- no detection
- intermittent detection
- invalid/empty tracking data

Extend existing rendering tests if present.

## 19. Integration

Keep the existing end-to-end flow:

    Local video / YouTube URL
        ->
    source acquisition
        ->
    transcription
        ->
    AI clip selection
        ->
    smart framing
        ->
    FFmpeg rendering
        ->
    vertical clips

Do not rewrite the AI clip-selection subsystem.

## 20. Observability/debugging

For each clip, make it possible to understand:

- whether dynamic framing was used
- subjects detected
- scene changes detected
- fallback mode used
- tracking failures
- relevant configuration

Use the existing logging system. Do not log every frame by default.

If practical, add a debug mode that exports framing/tracking metadata.

Conceptually:

    {
      "scene": 2,
      "time": 12.5,
      "subject_id": 1,
      "confidence": 0.91,
      "target_x": 1032,
      "camera_x": 1001,
      "mode": "tracked"
    }

The exact schema may differ.

## 21. API/UI

Do not redesign the UI.

The current workflow must continue to work.

If useful, expose a minimal status such as:

    Smart framing: Dynamic

or:

    Smart framing: Fallback

Only make UI changes useful for validating the feature.

## 22. Backward compatibility

Existing clips must continue to render.

If dynamic smart framing cannot be used for a video, fall back to the previous/static behaviour.

Do not break the v0.1.x pipeline.

## 23. Acceptance criteria

Version v0.2.0 is complete when:

1. Existing ClipFactory workflows still work.
2. A person moving horizontally through a clip is followed by the 9:16 framing.
3. Camera movement is visibly smooth.
4. Small tracking jitter does not create visible crop jitter.
5. Scene cuts cause tracking to be reconsidered.
6. The camera does not randomly jump between multiple people.
7. Crop boundaries are always valid.
8. Temporary detection failures do not break rendering.
9. Videos with no detectable person still render using fallback framing.
10. Unit tests cover the new framing logic.
11. The implementation is modular enough for future improvements.
12. No ComfyUI dependency is introduced.
13. No unrelated ClipFactory functionality is changed.

## 24. Implementation workflow

### Step 1 — Inspect

Inspect:

- current Smart Crop code
- video processing
- FFmpeg integration
- configuration
- dependencies
- tests
- job/pipeline architecture

Identify exactly where Smart Crop currently occurs.

### Step 2 — Plan

Create a concise implementation plan based on the actual repository:

- files to modify
- files to add
- dependencies
- integration points
- testing strategy

### Step 3 — Implement

Implement incrementally:

1. subject detection abstraction
2. tracking
3. scene awareness
4. camera trajectory
5. smoothing/dead zone
6. renderer integration
7. fallback behaviour
8. logging/debug information
9. tests

Adapt this order if the existing architecture suggests a better one.

### Step 4 — Validate

Run:

- unit tests
- existing test suite
- lint/type checks if configured
- real end-to-end video test

Use a video containing:

- a talking person
- movement during the clip
- ideally at least one scene change

### Step 5 — Inspect output

Do not consider the feature complete merely because tests pass.

Visually inspect generated clips and verify:

- subject remains visible
- framing is smooth
- camera follows naturally
- scene changes do not cause incorrect tracking
- no black borders or invalid crops
- output remains 9:16

### Step 6 — Document

Update documentation with:

- Smart Crop architecture
- configuration
- dependencies
- fallback behaviour
- known limitations
- debug procedure

### Step 7 — Version

Update project version to:

    0.2.0

Only do this once implementation is complete, unless the repository's versioning workflow requires otherwise.

## 25. Engineering judgement

Do not over-engineer this.

ClipFactory is a personal local tool, not a SaaS platform.

The goal is:

    "Good automatic vertical framing"

not:

    "Build a production-grade computer vision platform."

Prefer a simple robust implementation.

If an existing library provides reliable tracking, use it.

If a simpler algorithm works for the current use cases, use it.

Avoid unnecessary databases, queues, microservices, cloud APIs, custom model training, or distributed processing.

## 26. Future compatibility

Keep interfaces extensible enough that later versions could add:

- speaker-aware framing using transcript/speaker diarization
- better multi-person composition
- face priority
- object-aware framing
- B-roll
- captions
- manual crop overrides
- per-scene framing policies

These are NOT part of v0.2.0.

## Final instruction

Implement ClipFactory v0.2.0 as a focused upgrade of the existing Smart Crop subsystem.

The key result must be a smooth, scene-aware virtual camera that dynamically follows the relevant subject throughout each generated vertical clip, while retaining robust fallback behaviour and the existing ClipFactory workflow.

Before modifying anything, inspect the existing implementation and adapt this specification to the repository's actual architecture.
