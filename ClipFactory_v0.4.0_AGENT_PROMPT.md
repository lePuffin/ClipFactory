# ClipFactory v0.4.0 — AI Editorial Engine: Story, Angle & Script

## Objective

Implement **ClipFactory v0.4.0** as the editorial intelligence milestone.

v0.3.0 established the multi-source pipeline and produces a real rough 9:16 Reel. v0.4.0 must substantially improve the intelligence behind that Reel:

> Given the analyzed source material, ClipFactory should decide what story is actually worth telling, choose the strongest editorial angle, and produce a compelling, fact-grounded short-form script with explicit provenance and visual intent.

The output must still be a **real rendered MP4**, so the improvement can be evaluated directly against v0.3.0.

The focus is **editorial quality**, not TTS, B-roll generation, or cinematic polish.

---

## 1. Existing Context

Roadmap:

```text
v0.1.x  Video → clips
v0.2.0  Dynamic Smart Crop
v0.3.0  Multi-source → rough Reel
v0.4.0  AI editorial engine → better story/script
v0.5.0  AI human-like voice
v0.6.0  AI visual/storyboard planning
v0.7.0  Source footage + images + B-roll selection
v0.8.0  Advanced automatic composition
v0.9.0  Quality/reliability/refinement
v1.0.0  End-to-end automatic Reel/Short generation
```

Preserve all working v0.3.0 functionality.

---

## 2. Inspect the Repository First

Before changing code:

1. Inspect the repository structure.
2. Read the existing v0.3.0 implementation.
3. Understand source models, provenance, story/script models, scene models, LLM abstraction, prompts, renderer, Smart Crop, API, frontend, jobs, configuration, and tests.
4. Run the existing test suite.
5. Run the v0.3.0 pipeline if possible.
6. Inspect at least one generated v0.3.0 JSON and MP4 if available.

Adapt to the existing architecture. Do not rewrite working infrastructure unnecessarily.

---

## 3. Definition of v0.4.0

v0.4.0 is an **AI Editorial Engine**.

Transform:

```text
Sources
 ↓
Analysis
 ↓
Story
 ↓
Basic Script
 ↓
Rough Reel
```

into:

```text
Sources
 ↓
Analysis
 ↓
Story Candidates
 ↓
Editorial Evaluation
 ↓
Best Story
 ↓
Best Angle
 ↓
Hook
 ↓
Narrative Structure
 ↓
Fact-grounded Script
 ↓
Visual Intent
 ↓
Rough Reel
```

The renderer remains intentionally simple. The intelligence should improve.

---

## 4. Core Requirements

Implement:

1. Multiple story candidates when appropriate.
2. Candidate evaluation.
3. Strongest story selection.
4. Multiple editorial angles.
5. Strongest angle selection.
6. Dedicated hook generation.
7. Structured short-form narrative.
8. Fact-grounded script generation.
9. Provenance throughout.
10. Visual-aware scripting.
11. Scene planning compatible with the existing renderer.
12. Real rendered rough Reel.
13. Direct comparison with v0.3.0.

---

## 5. Editorial Quality

Optimize story selection for:

- importance
- novelty
- relevance
- audience interest
- storytelling potential
- factual support
- source coverage
- available visuals
- coherence

Do not optimize purely for clickbait.

The strongest angle must be the strongest **truthful** story.

---

## 6. Story Candidates

Do not assume one possible story.

Possible angles include:

```text
What happened?
Why it matters
What changes
Surprising implication
Conflict/disagreement
Consequence
Explainer
```

Candidates should contain, conceptually:

```python
class StoryCandidate:
    id: str
    title: str
    summary: str
    source_ids: list[str]
    key_points: list[KeyPoint]
    evidence: list[EvidenceReference]
    editorial_scores: EditorialScores
    overall_score: float
```

Adapt to existing models.

---

## 7. Editorial Scoring

Use explicit structured scoring rather than one opaque LLM decision.

Possible dimensions:

```text
importance
novelty
audience_interest
clarity
storytelling_potential
factual_support
visual_potential
source_coverage
```

Normalize scores to 0–1 and use configurable weights.

An LLM-assisted structured evaluation plus deterministic weighted scoring is sufficient. Do not build a machine-learning ranking system.

Expose scores for debugging/evaluation.

---

## 8. Editorial Angle Generation

For the selected story, generate multiple possible editorial angles.

Each angle should include:

- angle
- rationale
- audience-interest rationale
- supporting evidence
- visual opportunities
- score

Then select the strongest angle.

Do not use unsupported sensationalism.

---

## 9. Hook Generation

Generate a dedicated hook and, where useful, multiple candidates before selecting one.

A hook should:

- create curiosity quickly
- communicate relevance
- avoid unnecessary setup
- be truthful
- lead naturally into the story

Never invent claims for a stronger hook.

---

## 10. Narrative Structure

Use explicit structure such as:

```text
HOOK
 ↓
CONTEXT
 ↓
DEVELOPMENT
 ↓
KEY REVELATION
 ↓
IMPLICATION
 ↓
ENDING
```

Not every story needs every section.

Represent structure in the data model.

Conceptually:

```python
class ScriptSection:
    id: str
    type: ScriptSectionType
    text: str
    evidence: list[EvidenceReference]
    visual_intent: str
```

---

## 11. Script Generation

Generate a short-form script targeting approximately **20–60 seconds**, configurable.

The script must be:

- concise
- conversational
- natural when spoken aloud
- factually grounded
- easy to understand
- visually compatible
- free of filler and repetition

Avoid article-like prose, generic introductions, long sentences, unsupported claims, and weak endings.

The future v0.5.0 TTS engine will read this script directly, so optimize it for speech.

---

## 12. Fact Grounding

Use only supplied source material.

Distinguish:

```text
FACT
SOURCE CLAIM
INFERENCE
OPINION
```

If sources disagree, do not silently merge them. Resolve through evidence or explicitly attribute the disagreement.

Every substantive statement needs supporting evidence.

---

## 13. Provenance

Every script section must retain evidence references.

Example:

```json
{
  "id": "section_03",
  "type": "key_revelation",
  "text": "The company expects...",
  "evidence": [
    {"source_id": "article_02", "segment_id": "article_02_p14"}
  ]
}
```

For video evidence retain exact timestamps.

This must remain machine-readable for future storyboard and visual-selection stages.

---

## 14. Visual-Aware Scriptwriting

The editorial engine should know what useful visuals are available, but v0.4.0 must NOT become the full B-roll engine.

For each script section provide, conceptually:

```text
visual_intent
preferred_visual_type
supporting_asset_references
```

Example:

```json
{
  "text": "The company revealed a new vehicle...",
  "visual_intent": "Show the newly announced vehicle.",
  "preferred_visual_type": "source_image",
  "candidate_assets": ["article_01_image_03", "video_02_seg_041"]
}
```

---

## 15. Do Not Implement B-roll

Do NOT integrate:

- ComfyUI
- WAN
- AI video generation
- stock-media search

If no suitable visual exists, record the visual intent and use an existing simple fallback in the renderer.

---

## 16. Scene Planning

Improve the existing scene plan to reflect editorial structure.

Conceptually:

```python
class Scene:
    id: str
    script_section_id: str
    duration: float
    narration: str
    visual_type: str
    visual_reference: str | None
    source_id: str | None
    start: float | None
    end: float | None
    visual_intent: str
```

Follow repository conventions rather than copying this literally.

---

## 17. Renderer

Keep rendering simple.

Use:

- source video
- source images
- text-card fallbacks
- existing Smart Crop
- simple cuts/transitions
- narration text overlays

Output:

```text
1080x1920
9:16
H.264
MP4
```

The objective is to compare v0.4.0 editorial quality against v0.3.0, not to build cinematic polish.

---

## 18. Make Comparison Easy

Expose:

```text
Selected story
Story score
Selected angle
Angle score
Why selected
Hook
Script
Sources/evidence
Scene plan
Final MP4
```

This must make it possible to diagnose editorial decisions.

---

## 19. UI

Extend the existing UI.

The result should expose at least:

```text
Story
Title
Summary
Selected angle
Why selected

Script
Hook
Sections...

Sources
...

Scenes
...

[ VIDEO PREVIEW ]

[ Download MP4 ]
[ Download JSON ]
```

Do not build a manual editor.

---

## 20. LLM Pipeline

Prefer a deterministic pipeline:

```text
SourceAnalysis
      ↓
StoryCandidateGeneration
      ↓
StoryEvaluation
      ↓
StorySelection
      ↓
AngleGeneration
      ↓
AngleEvaluation
      ↓
AngleSelection
      ↓
HookGeneration
      ↓
ScriptGeneration
      ↓
ScriptValidation
      ↓
VisualIntent / ScenePlanning
      ↓
Rendering
```

Do not introduce a general autonomous agent.

Reuse the existing LLM abstraction and OpenAI-compatible/OpenRouter architecture if already present.

---

## 21. Prompt Architecture

Keep editorial prompts separate from business logic.

At minimum:

```text
story_candidate_generation
story_evaluation
angle_generation
angle_evaluation
hook_generation
script_generation
script_validation
visual_intent
```

Prompts must explicitly instruct the model to:

- use only supplied source information
- not invent facts
- preserve evidence references
- distinguish fact from interpretation
- optimize for short-form storytelling
- avoid unsupported sensationalism
- write naturally for speech
- consider available visuals

---

## 22. Script Validation

Before rendering validate:

- schema
- duration estimate
- evidence references
- unsupported/missing claims
- duplicate information
- empty sections
- invalid source references
- visual references where required

Retry or repair invalid structured output through a controlled path. Never silently accept malformed output.

---

## 23. Duration

Estimate spoken duration from word count using a configurable words-per-minute value, e.g. approximately 145–170 WPM.

Use the estimate to keep the script within the configured target.

Exact timing can be refined in v0.5.0 once TTS exists.

---

## 24. Multiple Stories

Keep multiple story candidates in the architecture.

For v0.4.0:

- select the strongest story by default
- render one Reel by default
- do not remove the ability to generate multiple stories later

---

## 25. Testing

Preserve all existing tests.

### Unit tests

Add coverage for:

- story scoring
- deterministic ranking
- angle scoring
- hook validation
- script validation
- provenance/evidence validation
- unsupported-claim detection
- duration estimation
- visual-intent validation

### Integration tests

Use deterministic fixtures and mocked LLM responses.

Verify:

```text
sources
→ story candidates
→ story selection
→ angle selection
→ script
→ scene plan
```

Verify provenance survives every stage.

### Regression

Verify the v0.3.0 workflow still works.

---

## 26. Mandatory End-to-End Acceptance Test

The full pipeline MUST produce a real MP4.

Use a reproducible fixture containing:

- at least two related sources
- at least one video
- at least one article/text source

Run:

```text
sources
→ analysis
→ story candidates
→ story selection
→ angle selection
→ script
→ scene plan
→ rendering
```

Verify:

- MP4 exists
- 1080x1920
- 9:16
- valid media
- no black/unrendered scenes
- script text is visible
- selected visuals correspond to the story
- Smart Crop works
- provenance is present
- existing tests pass

---

## 27. Editorial Quality Acceptance

The implementation is not complete merely because the pipeline executes.

Review the generated Reel and assess:

### Story

- Is the selected story actually the most interesting/useful one?
- Does it make sense given all supplied sources?
- Does it avoid mixing unrelated topics?

### Angle

- Does the angle give the viewer a reason to care?
- Is it supported by evidence?
- Is it stronger than a generic summary?

### Hook

- Does the opening create curiosity quickly?
- Is it truthful?
- Does it lead naturally into the story?

### Script

- Does it sound natural when spoken?
- Is it concise?
- Does every section add information?
- Is there unnecessary filler?
- Is there a meaningful ending?

### Visuals

- Do visuals support what is being said?
- Are source segments relevant?
- Are source images relevant?

### Overall

Ask:

> Would I actually watch this Reel to the end?

and:

> Is the editorial decision clearly better than the v0.3.0 version?

If not, diagnose the responsible stage rather than adding random complexity.

---

## 28. Architecture Principle

Keep editorial intelligence separate from rendering.

Prefer:

```text
Content Analysis
      ↓
Editorial Engine
      ↓
Story
      ↓
Angle
      ↓
Script
      ↓
Scene Plan
      ↓
Renderer
```

The renderer must not decide what story to tell.

The LLM must not directly manipulate FFmpeg.

Use explicit typed inputs/outputs between stages.

---

## 29. Future Compatibility

Design outputs for:

```text
v0.5.0: Script → TTS Audio
v0.6.0: Script + Audio → Visual Storyboard
v0.7.0: Storyboard → Source assets + B-roll
v0.8.0: Audio + Visuals + Scene Plan → polished composition
```

Do not prematurely implement those stages.

---

## 30. Hardware / Complexity

Development environment has approximately:

```text
NVIDIA RTX PRO 500 Black
~6 GB VRAM
```

Do not introduce unnecessarily large local models or heavyweight infrastructure.

Prefer the existing API/LLM infrastructure.

---

## 31. Security

External URLs remain untrusted input.

- validate URLs where appropriate
- use safe subprocess invocation
- never interpolate untrusted input into shell commands
- do not execute downloaded content

---

## 32. Documentation

Update documentation for v0.4.0:

- editorial engine architecture
- story candidate generation
- editorial scoring
- angle selection
- hook generation
- script structure
- provenance
- visual intent
- output format
- evaluation workflow

Update version metadata to `0.4.0` where appropriate.

---

## 33. Change Discipline

Follow:

```text
inspect
→ run existing tests
→ run v0.3.0
→ plan
→ implement
→ test
→ generate Reel
→ inspect result
→ review
```

Do not make unrelated refactors.

Do not replace working v0.3.0 functionality without a concrete reason.

At completion report:

- files changed
- architecture added
- prompts added/changed
- tests added
- commands run
- how to run v0.4.0
- generated output location
- known limitations
- comparison against v0.3.0

---

## 34. Definition of Done

v0.4.0 is complete only when:

- [ ] v0.3.0 functionality remains operational
- [ ] story candidates can be generated
- [ ] candidates can be evaluated
- [ ] strongest story can be selected
- [ ] editorial scoring is inspectable
- [ ] multiple editorial angles can be generated
- [ ] strongest angle can be selected
- [ ] hook is explicitly generated
- [ ] script has explicit narrative structure
- [ ] script is short-form optimized
- [ ] script is natural when spoken
- [ ] substantive script statements have evidence
- [ ] source conflicts are handled safely
- [ ] script has visual intent
- [ ] scene plan reflects editorial structure
- [ ] existing Smart Crop is reused
- [ ] real 9:16 MP4 is produced
- [ ] output is 1080x1920
- [ ] narration is visible as readable text
- [ ] story/angle/script/scene JSON is saved
- [ ] UI exposes editorial decisions
- [ ] existing tests pass
- [ ] new tests cover editorial logic
- [ ] end-to-end test produces a valid MP4
- [ ] documentation is updated
- [ ] version is 0.4.0

---

## 35. Final Acceptance Criterion

The decisive question is:

> **Given the exact same source material, is the v0.4.0 Reel clearly more compelling, coherent, and editorially intelligent than the v0.3.0 Reel?**

v0.3.0 proves ClipFactory can understand sources and assemble a rough video.

v0.4.0 must prove ClipFactory can **make a good editorial decision about what story to tell and how to tell it**.

Do not stop at improved JSON or a better prompt.

**The rendered Reel remains the primary v0.4.0 deliverable.**
