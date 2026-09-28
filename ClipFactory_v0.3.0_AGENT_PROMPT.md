# ClipFactory v0.3.0 — Multi-Source AI Story → Rough Reel

## Objective

Implement ClipFactory v0.3.0 as the first end-to-end multi-source content generation milestone.

**Hard requirement:** v0.3.0 MUST produce a real, watchable 9:16 MP4 Reel/Short from multiple heterogeneous sources. The purpose is to evaluate the quality of the AI's content understanding, story selection, script generation, and visual selection before moving to later phases.

This is NOT merely an ingestion/analysis milestone.

---

## 1. Existing Context

ClipFactory currently has:

- v0.1.x: local video / YouTube → automatically selected clips
- v0.2.0: dynamic scene-aware Smart Crop / virtual camera

Preserve the existing v0.1.x and v0.2.0 functionality.

Long-term target:

```text
1+ videos + articles + images
        ↓
understand source material
        ↓
decide what story/stories to tell
        ↓
write narration/script
        ↓
AI human-like voice
        ↓
select source footage/images
        ↓
B-roll where useful
        ↓
9:16 composition
        ↓
finished Reel/Short
```

v0.3.0 should establish:

```text
Multiple Sources
      ↓
Source Acquisition
      ↓
Content Extraction
      ↓
Content Analysis
      ↓
Story Selection
      ↓
Script Generation
      ↓
Visual Selection
      ↓
Scene Plan
      ↓
9:16 Rendering
      ↓
ROUGH REEL / SHORT
```

---

## 2. Scope

### Implement

- Multiple local video inputs
- YouTube URLs
- Article URLs
- Pasted article text
- Local images
- Unified source representation
- Content extraction
- Timestamped video transcription
- Article extraction
- Image/vision analysis
- Source-level AI analysis
- Cross-source story grouping
- Story selection
- Short-form script generation
- Script provenance
- Scene/visual planning
- Source video segment selection
- Source image selection
- Existing Smart Crop during video rendering
- Simple readable narration text overlays
- 9:16 MP4 rendering
- Saved machine-readable story/scene JSON
- UI support for the workflow
- Tests and documentation

### Explicitly DO NOT implement

- AI TTS / voice generation
- AI-generated B-roll
- ComfyUI
- social publishing
- authentication/users
- billing
- cloud deployment
- analytics
- timeline editor
- custom ML training
- music generation
- automatic thumbnails
- sophisticated motion graphics
- production subtitle/caption editing

Those belong to later milestones.

---

## 3. Inspect the Repository First

Before modifying code:

1. Inspect the complete repository structure.
2. Understand the current v0.1.x pipeline.
3. Understand the current v0.2.0 Smart Crop implementation.
4. Identify existing:
   - models
   - services
   - pipelines
   - FFmpeg utilities
   - transcription
   - LLM abstraction
   - API
   - frontend
   - job management
   - configuration
   - tests
5. Run the existing test suite.
6. Run a small existing end-to-end example if practical.

Adapt this specification to the existing repository. Do NOT rewrite working architecture unnecessarily.

Do NOT duplicate existing transcription, YouTube acquisition, Smart Crop, or rendering functionality.

---

## 4. Multi-Source Input

A job should accept any combination of:

- local video
- YouTube URL
- article URL
- pasted article text
- local image

Examples that must be possible:

```text
video + video + article + article
```

and:

```text
video + 3 articles + 2 images
```

Do not require every source type.

Extend the existing UI rather than replacing it.

---

## 5. Unified Source Model

Introduce or extend a normalized source abstraction. Adapt names to existing conventions.

Conceptually:

```python
class SourceType(str, Enum):
    VIDEO = "video"
    YOUTUBE = "youtube"
    ARTICLE = "article"
    IMAGE = "image"
    AUDIO = "audio"
```

A source should contain:

```python
class Source:
    id: str
    type: SourceType
    original_location: str | None
    local_path: str | None
    metadata: SourceMetadata
    content: ExtractedContent
    analysis: SourceAnalysis | None
```

Do not blindly copy this model if suitable abstractions already exist.

---

## 6. Provenance Is Mandatory

Every fact, claim, script statement, and visual asset used by the pipeline must be traceable to its source.

Examples:

```text
video_01_seg_031
132.4s → 138.2s
```

or:

```text
article_01_p17
```

or:

```text
article_01_image_02
```

The system must be able to answer:

> Where did this statement in the generated script come from?

Do not create important claims without provenance.

---

## 7. Video Processing

Reuse the existing video acquisition and transcription infrastructure.

For video:

```text
video
 ↓
audio extraction
 ↓
existing transcription
 ↓
timestamped transcript
 ↓
scene information
 ↓
source analysis
```

Preserve timestamps.

Example:

```json
{
  "source_id": "video_01",
  "segments": [
    {
      "id": "video_01_seg_001",
      "start": 132.4,
      "end": 137.8,
      "text": "..."
    }
  ]
}
```

The existing dynamic Smart Crop must be reused when these segments are rendered.

---

## 8. Article Processing

For article URLs:

```text
URL
 ↓
fetch
 ↓
extract main article content
 ↓
metadata
 ↓
images
 ↓
analysis
```

Strip navigation, advertisements, cookie banners, menus, and unrelated page content.

Capture where possible:

- title
- author
- publication date
- main text
- images
- image URLs
- source URL

Keep article paragraphs addressable for provenance.

Pasted text should bypass fetching and go directly through normalization.

Use a minimal, reliable article extraction dependency compatible with the existing project.

---

## 9. Image Processing

For local images:

```text
image
 ↓
metadata
 ↓
vision analysis
 ↓
description / entities / relevance
```

Reuse the existing LLM/provider abstraction where possible.

Analysis should identify:

- what is visible
- relevant entities
- likely topic/story
- whether the image is useful for a short-form scene

Do not hard-code the system to a new provider if the repository already has an abstraction.

---

## 10. Source Analysis

Convert each source into structured information.

Conceptually:

```python
class SourceAnalysis:
    summary: str
    topics: list[str]
    entities: list[Entity]
    claims: list[Claim]
    notable_quotes: list[Quote]
    important_segments: list[SegmentReference]
    assets: list[AssetReference]
```

Identify:

- main topic
- secondary topics
- people
- companies
- organizations
- places
- events
- important facts
- claims
- quotes
- notable moments
- useful visual assets

Use validated structured outputs rather than unstructured LLM prose where possible.

---

## 11. Cross-Source Understanding

This is a core feature.

Given:

```text
Video A
Video B
Article A
Article B
Image A
```

determine:

- which sources discuss the same story
- shared facts
- differing facts
- supporting sources
- useful visuals
- unrelated stories

Pipeline:

```text
Sources
   ↓
Source Analysis
   ↓
Topic/semantic grouping
   ↓
Story Candidates
```

Conceptual output:

```json
{
  "stories": [
    {
      "id": "story_01",
      "title": "Example announcement",
      "topic": "Example topic",
      "importance": 0.94,
      "sources": ["video_01", "article_01", "article_02"],
      "key_points": [
        {
          "text": "...",
          "evidence": ["video_01_seg_014", "article_01_p17"]
        }
      ]
    }
  ]
}
```

If multiple unrelated stories exist, produce multiple candidates.

---

## 12. Story Selection

Automatically select the strongest story for the v0.3.0 Reel.

Consider:

- relevance
- factual support
- source coverage
- visual availability
- short-form interest
- coherence
- amount of usable source footage
- useful images

Do NOT simply choose the first source.

Support multiple story candidates in the data model, even if v0.3.0 renders only the highest-ranked story.

---

## 13. Script Generation

v0.3.0 MUST generate a short-form script.

The script is text only. TTS is deferred.

Default target: approximately 20–60 seconds.

The script should be:

- concise
- coherent
- factually grounded
- based only on supplied sources
- suitable for a Reel/Short
- structured for visual storytelling

Include:

- hook
- main information
- supporting information
- conclusion/takeaway where appropriate

Keep the style controlled by prompts/configuration rather than deeply hard-coded logic.

---

## 14. Script Provenance

Every script section must reference supporting source material.

Example:

```json
{
  "id": "narration_03",
  "text": "The company expects...",
  "evidence": [
    {
      "source_id": "article_02",
      "segment_id": "article_02_p14"
    }
  ]
}
```

For video:

```json
{
  "source_id": "video_01",
  "segment_id": "video_01_seg_031",
  "start": 241.2,
  "end": 246.7
}
```

This must remain available to future storyboard and visual-selection stages.

---

## 15. Scene / Visual Planning

Convert the script into a scene plan.

This is the bridge between story generation and rendering.

Conceptually:

```python
class Scene:
    id: str
    duration: float
    narration: str
    visual_type: str
    visual_reference: str
    source_id: str | None
    start: float | None
    end: float | None
```

Supported visual types:

```text
source_video
source_image
article_image
text_card
```

Do NOT implement generated B-roll.

---

## 16. Visual Selection

Select actual source visuals for each scene.

Preference order:

1. relevant source video
2. relevant source image
3. relevant article image
4. text card fallback

Do not randomly select footage.

The visual should match the narration semantically.

For example, narration about a specific person should preferentially use footage/image containing that person when available.

---

## 17. Video Segment Selection

Map story/script requirements to timestamped source video segments.

Example:

```text
Narration:
"CEO John Smith said..."

Visual:
video_02
243.2s → 248.7s
```

Reuse the existing Smart Crop implementation.

Do not duplicate or replace Smart Crop.

---

## 18. Scene Timing

Timing does not need to be perfect in v0.3.0.

A sensible first approach is:

```text
scene duration ≈ narration reading duration
```

with reasonable minimum/maximum bounds.

Handle:

- source clips shorter than required
- invalid timestamps
- missing assets
- scene durations
- transitions/cuts

Do not produce black frames or invalid media.

---

## 19. Rough Reel Renderer

The primary deliverable is a real MP4.

Output:

```text
1080x1920
9:16
H.264
MP4
```

Reuse existing FFmpeg infrastructure.

Support:

- source video scenes
- image scenes
- text cards
- scene sequencing
- basic cuts/transitions
- dynamic Smart Crop on source video

Keep visual effects intentionally simple.

The goal is to evaluate content quality, not cinematic polish.

---

## 20. Narration Text Overlay

Because TTS is deferred, represent generated narration visually.

Implement a simple readable text overlay.

This is NOT a full subtitle/caption editor.

Requirements:

- readable on a phone
- reasonable font size
- line wrapping
- safe margins
- consistent placement
- avoid obscuring important content where practical

The overlay must allow the user to judge:

> Is this what I would want the future AI voice to say?

---

## 21. Output

A successful job should produce:

```text
output/
└── <job_id>/
    ├── story_01.mp4
    └── story_01.json
```

The JSON should contain the complete machine-readable story and scene plan.

Example:

```json
{
  "story": {
    "id": "story_01",
    "title": "Example story",
    "hook": "Something just happened...",
    "duration": 38
  },
  "scenes": [
    {
      "id": "scene_01",
      "duration": 5.2,
      "narration": "Something just happened...",
      "visual": {
        "type": "source_video",
        "source_id": "video_01",
        "start": 132.4,
        "end": 137.6
      }
    },
    {
      "id": "scene_02",
      "duration": 4.8,
      "narration": "The biggest change is...",
      "visual": {
        "type": "source_image",
        "source_id": "article_01",
        "asset_id": "image_02"
      }
    }
  ]
}
```

---

## 22. UI

Extend the current UI.

The user must be able to:

1. add multiple sources
2. see the sources in the current job
3. start processing
4. see progress/current stage
5. see the selected story
6. inspect the generated script
7. inspect scene/visual choices
8. preview the generated MP4
9. download the MP4
10. download the JSON plan

The generated video is the primary deliverable.

---

## 23. Job Pipeline

Extend the existing job state machine.

Possible stages:

```text
CREATED
→ ACQUIRING
→ EXTRACTING
→ ANALYZING
→ STORY_SELECTING
→ SCRIPTING
→ PLANNING
→ RENDERING
→ COMPLETED
```

Existing states may be extended instead of replaced.

Failures must remain explicit:

```text
FAILED
```

A partial source failure should not necessarily destroy the entire job if enough material remains.

---

## 24. LLM Architecture

Reuse the existing LLM abstraction.

Use structured outputs and validation.

The LLM should handle:

- source analysis
- cross-source interpretation
- story selection
- script generation
- visual planning

Prefer a deterministic pipeline:

```text
extract
→ analyze
→ group
→ select
→ script
→ plan
→ render
```

Do not introduce an agent framework merely for this feature.

If the existing project uses OpenAI-compatible APIs/OpenRouter, preserve that architecture.

---

## 25. Prompt Design

Keep prompts separate from Python/business logic where appropriate.

At minimum, separate prompts for:

```text
source_analysis
story_grouping
story_selection
script_generation
visual_planning
```

Prompts must explicitly instruct the model to:

- use only supplied source information
- not invent facts
- preserve provenance
- distinguish fact from interpretation
- select visuals relevant to narration
- return the requested structured schema

---

## 26. Error Handling

Handle partial source failures where practical.

Examples:

```text
article_02:
Unable to extract article content.
```

or:

```text
video_02:
Transcription failed.
```

Continue with remaining sources if a meaningful story can still be generated.

Fail the job when there is insufficient material for a meaningful Reel.

---

## 27. Testing

Preserve all existing tests.

### Unit tests

Add coverage for:

- source normalization
- source types
- article extraction/normalization
- transcript mapping
- provenance
- story grouping
- story ranking
- script schema
- scene validation
- visual references
- duration calculation
- renderer input validation

### Integration tests

Create deterministic fixtures representing:

```text
2 related video/transcript sources
+
2 article/text sources
+
1 image analysis source
```

Verify:

```text
sources
→ analysis
→ story
→ script
→ scenes
```

Mock the LLM in deterministic tests.

### Rendering test

Use a small synthetic/fixture video and verify:

- FFmpeg succeeds
- MP4 exists
- output is valid
- resolution is 1080x1920
- expected scenes are present

---

## 28. Mandatory End-to-End Acceptance Test

This is non-negotiable.

Create/use a small reproducible dataset containing:

- at least two related sources
- at least one video
- at least one article/text source

Run the complete pipeline.

The result MUST be a real MP4.

Validate:

### Content

- selected story is coherent
- script reflects the source material
- claims have provenance
- unrelated source material is not mixed into the story

### Visuals

- selected visuals are relevant
- video timestamps are valid
- source images are relevant
- Smart Crop works on selected source video

### Video

- real MP4
- 1080x1920
- 9:16
- no corrupted frames
- no unexplained black sections
- scenes in correct order
- readable narration overlays

### Regression

- v0.1.x still works
- v0.2.0 Smart Crop still works
- existing tests pass

---

## 29. Quality Evaluation Is Part of the Feature

Expose enough intermediate information to determine why a Reel is good or bad.

For each result show:

```text
Story
Why it was selected
Sources used
Script
Scenes
Visual choices
Final video
```

This allows diagnosis of failures in:

```text
source extraction
→ analysis
→ story selection
→ script
→ visual selection
→ rendering
```

The goal is not merely to make the pipeline execute.

The goal is to determine whether ClipFactory's core content intelligence is good enough to justify proceeding to TTS and more advanced visual generation.

---

## 30. Architecture for Future Versions

Do not implement the entire pipeline as one monolithic function.

Prefer explicit stages:

```text
Source
  ↓
ExtractedContent
  ↓
SourceAnalysis
  ↓
StoryCandidate
  ↓
Story
  ↓
Script
  ↓
ScenePlan
  ↓
RenderedVideo
```

Future milestones should be able to replace individual stages:

```text
v0.4.0 → better Story → Script
v0.5.0 → Script → TTS Audio
v0.6.0 → Script → Visual Storyboard
v0.7.0 → Storyboard → source/B-roll selection
v0.8.0 → ScenePlan + Audio + Visuals → polished composition
```

---

## 31. Do Not Overengineer

This is a personal/local application.

Do not introduce:

- Redis
- Celery
- Kafka
- Kubernetes
- microservices
- distributed workers
- cloud storage
- authentication systems

unless already present and genuinely required.

Prefer the existing local architecture and:

```text
Python
FastAPI
Pydantic
existing LLM abstraction
existing transcription
FFmpeg
local filesystem
SQLite if already used
```

---

## 32. Hardware

Development machine:

```text
NVIDIA RTX PRO 500 Black
~6 GB VRAM
```

Keep local models lightweight.

Do not introduce a large local multimodal model merely because it is possible.

Prefer the existing API-based multimodal capability where appropriate.

---

## 33. Security

Article and YouTube URLs are external input.

- Validate URLs where appropriate.
- Never concatenate untrusted input into shell commands.
- Use safe subprocess argument arrays/APIs.
- Do not execute downloaded content.

---

## 34. Documentation

Update documentation for v0.3.0:

- purpose
- supported sources
- pipeline
- source model
- provenance
- story model
- scene model
- output format
- how to run
- how to inspect JSON
- how to evaluate the generated Reel

Update version metadata to `0.3.0` where appropriate.

---

## 35. Change Discipline

Follow:

```text
inspect
→ test
→ plan
→ implement
→ test
→ review
```

Do not make unrelated refactors.

Preserve v0.1.x/v0.2.0 behavior.

At the end report:

- files changed
- architecture added
- tests added
- commands run
- how to run v0.3.0
- output location
- known limitations

---

# 36. Definition of Done

v0.3.0 is complete only when:

- [ ] multiple heterogeneous sources can be supplied
- [ ] local videos work
- [ ] YouTube sources work
- [ ] article URLs work
- [ ] pasted article text works
- [ ] local images work
- [ ] sources have normalized representations
- [ ] extracted content has provenance
- [ ] videos are transcribed with timestamps
- [ ] articles are cleaned/normalized
- [ ] images can be analyzed
- [ ] sources are analyzed
- [ ] related sources can be grouped
- [ ] strongest story can be selected
- [ ] short-form script is generated
- [ ] script sections retain provenance
- [ ] visual scenes are planned
- [ ] source video segments can be selected
- [ ] source images can be selected
- [ ] existing Smart Crop is used
- [ ] a real 9:16 MP4 is rendered
- [ ] output is 1080x1920
- [ ] narration is represented by readable text overlays
- [ ] story/scene JSON is saved
- [ ] UI previews the result
- [ ] MP4 can be downloaded
- [ ] JSON can be downloaded
- [ ] existing tests pass
- [ ] new tests cover the new pipeline
- [ ] end-to-end test produces a real MP4
- [ ] documentation is updated
- [ ] version is 0.3.0

---

# 37. Final Acceptance Criterion

The decisive test is:

> Give ClipFactory multiple related source materials and receive a vertical MP4 that tells a coherent short-form story using relevant excerpts/images from those sources.

Then ask:

> **If I watched this rough Reel, would I trust ClipFactory's understanding of the source material enough to move on to AI voice generation and more sophisticated visual generation?**

If that cannot be evaluated from the generated MP4, v0.3.0 is not complete.

**Do not stop at JSON, database records, API responses, or an internal storyboard.**

**The rendered video is the v0.3.0 deliverable.**
