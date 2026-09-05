# ClipFactory v0.3.0 Implementation Plan

## AI-Generated News Reels from Multi-Source Input

### Executive Summary

Transform ClipFactory from a "clip extraction" tool (v0.2) to a "reel generation" tool (v0.3) that accepts multiple video/article sources, synthesizes an AI voice-over narration, and composes vertical reels using source clips as b-roll with AI-generated visuals as filler.

**Key Constraint:** Local-first, single-user, no external publishing. Balanced quality for production evaluation.

---

## 1. Current State Analysis (v0.2.0)

### What Works

- **Source acquisition:** YouTube URLs + local video files
- **Transcription:** Whisper-based, timestamp-aligned
- **Clip selection:** LLM-driven intelligent moment detection
- **Smart framing:** Face detection + scene-aware camera tracking
- **Rendering:** FFmpeg vertical (9:16) MP4 output
- **Pipeline architecture:** Clean separation (services → pipelines → API)

### What's Missing for v0.3

- Multi-source input coordination (articles + videos)
- Article text extraction and ingestion
- Script generation from diverse sources
- Text-to-speech synthesis with proper timing
- B-roll assembly (source clips + AI-generated placeholders)
- Audio/video composition and mixing
- Reel assembly pipeline (stitch components into final video)

---

## 2. Proposed v0.3.0 Architecture

### High-Level Pipeline

```
Multiple Sources (videos/articles)
  ├── Video sources → extract key moments (v0.2 logic)
  ├── Article sources → extract text
  └── Combine → synthesize master narrative
                 ↓
        Generate script (LLM: narrative + timing)
                 ↓
        Generate AI voice (TTS: local open-source)
                 ↓
        Assemble B-roll
        ├── Primary: source video clips (reuse v0.2 moments)
        ├── Secondary: AI-generated visuals (placeholder/simple first)
        └── Combine with timing
                 ↓
        Compose & mix (audio + video)
                 ↓
        Render final reel (9:16 vertical MP4)
```

### Scope for v0.3.0

**IN:**

- Multiple video inputs (YouTube/local)
- Multiple article inputs (text paste or URL extraction)
- Local TTS (e.g., pyttsx3 or gTTS)
- Source video clip b-roll (clips extracted via v0.2 logic)
- Placeholder/simple AI visuals (solid colors, text overlays)
- Balanced composition (good enough for evaluation)

**OUT (defer to v0.4+):**

- Advanced AI image/video generation (ComfyUI, Stable Diffusion)
- Sophisticated video effects and transitions
- Captions/subtitles
- Dynamic thumbnails
- Social publishing
- Multiple output formats (keep 9:16 only)

---

## 3. Implementation Phases & Milestones

### Phase A: Input & Data Model (Milestone 1)

**Goal:** Accept and normalize multiple sources; build unified data model

**Tasks:**

- A1: Define `Source` model (video/article type, metadata, storage)
- A2: Add article ingestion service (text extraction, basic parsing)
- A3: Create `Job` model that coordinates multiple sources
- A4: Extend UI to accept multiple inputs (drag-drop, paste text)
- A5: Write tests for multi-source validation

**Deliverable:** CLI/API accepts articles + videos, normalizes them into internal Job format

---

### Phase B: Script Generation (Milestone 2)

**Goal:** Convert diverse sources into coherent, timed narration script

**Tasks:**

- B1: Define `Script` model (sentences, timestamps, metadata)
- B2: Create script-generation service (LLM orchestration)
  - Prompt: synthesize narrative from multiple sources
  - Enforce: sentence-level granularity, estimated durations
  - Output: structured JSON with timing hints
- B3: Validate script coherence and timing (Pydantic)
- B4: Write tests with fixed LLM responses (mock OpenRouter)

**Deliverable:** Given articles + video transcripts, produce timed script in ~2-5 minute range

---

### Phase C: TTS & Audio Generation (Milestone 3)

**Goal:** Convert script to human-quality voice with proper timing

**Tasks:**

- C1: Integrate local TTS (pyttsx3 or similar)
- C2: Create TTS service (script → WAV audio file)
  - Sentence-by-sentence with silence padding
  - Voice speed/pitch tuning
  - Fallback for errors
- C3: Generate audio metadata (timestamps, durations)
- C4: Write tests with synthetic audio samples

**Deliverable:** Given script, produce aligned audio file with timing markers

---

### Phase D: B-Roll Assembly (Milestone 4)

**Goal:** Extract and organize source video clips for composition

**Tasks:**

- D1: Extend v0.2 clip extraction to multi-source context
  - Extract key moments from each source video
  - Label by source + semantic meaning
- D2: Build `BRollClip` model (video segment, duration, source, metadata)
- D3: Create B-roll selection service
  - Allocate clips to script sentences
  - Pad with placeholders (solid colors, text overlay) if insufficient clips
- D4: Write tests with fixture video segments

**Deliverable:** Given script + source videos, produce ordered list of b-roll segments ready for composition

---

### Phase E: Composition & Rendering (Milestone 5)

**Goal:** Assemble audio + video into final 9:16 reel

**Tasks:**

- E1: Design composition strategy
  - Audio-driven timeline (script + TTS)
  - B-roll placed over audio
  - Placeholder visuals fill gaps
  - Simple transitions (fade/cut)
- E2: Create FFmpeg composition service
  - Build complex filter graph (audio, video, concat)
  - Render to 1080×1920 H.264/AAC MP4
- E3: Validate output (duration, resolution, codec)
- E4: Write integration tests (end-to-end with fixtures)

**Deliverable:** Given script + audio + b-roll, produce final 9:16 MP4 reel

---

### Phase F: Pipeline Integration & Refinement (Milestone 6)

**Goal:** Wire all phases together; optimize for quality and user feedback

**Tasks:**

- F1: Create unified `GenerateReel` pipeline orchestrator
  - Coordinate phases A–E
  - Error recovery and logging
  - Progress reporting
- F2: Extend UI to show reel generation status
- F3: Test end-to-end flow (article + video → reel)
- F4: Refinement loop
  - Evaluate output quality
  - Tune TTS timing, composition, b-roll selection
  - Address user feedback

**Deliverable:** Full v0.3.0 flow working via web UI; downloadable reel for evaluation

---

## 4. Technical Decisions

### TTS Choice

- **Selected:** Local open-source (pyttsx3 or gTTS)
- **Rationale:** No API keys, cost, or latency; good enough for v0.3 evaluation
- **Future:** Can swap for ElevenLabs, Google Cloud TTS in v0.4 if quality demands it

### B-Roll Strategy

- **Selected:** Mixed (source clips first, placeholders for filler)
- **Rationale:** Reuses v0.2 extraction logic; enables end-to-end flow without external AI generation
- **Future:** Add ComfyUI integration in v0.4 for sophisticated AI visuals

### Composition Approach

- **Selected:** Balanced (clean, functional, not fancy)
- **Rationale:** Focus on core feature (reel generation) vs. visual polish
- **Future:** Add transitions, effects, dynamic cropping in v0.4

### Storage & Job Management

- **Extend existing:** Reuse `data/jobs/<job-id>/` structure for reel jobs
- **Add:** Artifact tracking (audio files, b-roll clips, composition config)
- **Cleanup:** Post-job cleanup as in v0.2

---

## 5. Development Flow

### Recommended Sequence

1. **Start with Phase A:** Input model + multi-source UI (fast feedback loop)
2. **Parallel B & C:** Script generation + TTS (core AI components)
3. **Phase D:** B-roll selection (leverages v0.2)
4. **Phase E:** Composition (where pieces come together)
5. **Phase F:** Integration & polish (refinement based on output)

### Testing Strategy

- **Unit tests:** Each phase independently (mock LLM, audio, FFmpeg)
- **Integration tests:** Phase boundaries (e.g., script → audio timing)
- **End-to-end:** Full flow with fixture inputs → download + evaluate

### Quality Gates

- Script coherence (no nonsensical transitions)
- Audio timing accuracy (±200ms tolerance)
- Video output (correct resolution, duration, codec)
- No runtime errors on valid inputs

---

## 6. Deliverables & Success Criteria

### v0.3.0 Release

- **Functional:** Accept 1 article + 1 video → generate 1 reel (2–5 min vertical)
- **Quality:** Balanced composition; human-understandable narration; no major artifacts
- **Testable:** Downloadable MP4; can evaluate in normal video player
- **Code:** Clean pipeline; testable; documented

### Evaluation Metrics

- Reel plays end-to-end without errors
- Voice narration is clear and synchronized
- B-roll clips are meaningful and relevant
- No visual glitches or audio dropouts
- Renders in <10 min for typical 10-min source video + 5-min article

---

## 7. Open Questions & Risks

### Questions to Clarify During Development

- TTS voice: Which voice/gender/accent? (pyttsx3 limitation: basic options)
- Pacing: How long should each sentence's b-roll play? (algorithmic or manual tuning?)
- Placeholders: Solid colors, gradients, text overlays, or something else?
- Multi-video: How to prioritize clips when multiple sources are present?

### Risks

- **TTS quality:** pyttsx3 sounds robotic; may need API swap earlier than v0.4
- **Timing sync:** Audio/video drift; needs robust validation
- **B-roll availability:** Articles have no b-roll; placeholder quality matters
- **LLM script generation:** May produce misaligned sentences or nonsensical transitions

### Mitigation

- Early prototype with actual TTS output; decide on v0.3 vs. v0.4 boundary
- Strict timing validation in composition (fail fast)
- Diverse placeholder strategies (test multiple)
- Fixed test prompts for LLM; validate script structure rigorously

---

## 8. Files & Services to Create/Modify

### New Services (app/services/)

- `article_ingestion.py` – Extract text from URLs or paste
- `script_generation.py` – LLM orchestration for narrative synthesis
- `tts.py` – Text-to-speech wrapper (pyttsx3)
- `broll_selection.py` – Choose + order video clips
- `composition.py` – FFmpeg filter graph generation

### New Models (app/models/)

- `Source` – Video/Article with metadata
- `Script` – Timed narration (sentences + durations)
- `BRollClip` – Video segment reference
- `ReelJob` – Multi-source reel generation job

### New Pipelines (app/pipelines/)

- `generate_reel.py` – Orchestrate A→B→C→D→E phases

### Modified Services

- `clip_extraction.py` – Adapt for multi-source context
- `source_acquisition.py` – Potentially expand for articles

### UI Changes (app/static/)

- Add multi-input form (video + article fields)
- Show reel progress (phases, timestamps)
- Preview reel before download

### Tests (tests/)

- `test_article_ingestion.py`
- `test_script_generation.py`
- `test_tts.py`
- `test_broll_selection.py`
- `test_composition.py`
- `test_reel_pipeline_integration.py`

---

## 9. Success Definition

A successful v0.3.0 release means:

- ✅ **End-to-end flow:** Article + video → reel works via web UI
- ✅ **Downloadable output:** MP4 plays in any standard video player
- ✅ **Evaluation ready:** Quality is "balanced" (not perfect, but coherent and usable)
- ✅ **Testable:** Unit + integration tests pass; can reproduce errors
- ✅ **Documented:** Code is readable; pipeline is clear; TTS/composition choices are justified
