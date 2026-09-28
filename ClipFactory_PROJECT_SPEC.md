# ClipFactory — Product & Technical Specification

## 1. Project Overview

**Project name:** ClipFactory

**Description:**  
AI-powered personal tool that automatically identifies the best moments from long-form videos and turns them into vertical clips suitable for YouTube Shorts, Instagram Clips, and similar short-form formats.

**Primary goal:**  
Take a local video file or a YouTube URL, analyze the content, identify several self-contained/high-value moments, and generate vertical 9:16 MP4 clips.

**Important scope constraint:**  
This is a personal-use application for a single user. It does not need authentication, multi-user support, billing, subscriptions, public deployment, collaboration, social-media publishing, or enterprise infrastructure.

The application should optimize for:

- simplicity
- local execution
- low operating cost
- maintainability
- fast iteration
- good output quality

Do NOT over-engineer the first version.

---

## 2. V1 User Experience

The user should be able to:

1. Open the ClipFactory web interface.
2. Provide either:
   - a local video file via drag-and-drop/file picker, OR
   - a YouTube URL.
3. Start processing.
4. See processing progress.
5. Receive a list/grid of generated vertical clips.
6. Preview each clip.
7. Download/use the resulting MP4 files manually.

The application does NOT need to:

- publish to YouTube
- publish to Instagram
- publish to TikTok
- edit clips manually
- provide a timeline editor
- manage social accounts
- generate thumbnails
- generate descriptions
- generate captions/subtitles for V1
- generate AI B-roll for V1
- generate music
- provide team features

The output is simply a set of good vertical clips that the user can take into another application and edit however they want.

---

## 3. Core Pipeline

The intended pipeline is:

    Local video / YouTube URL
              |
              v
       Acquire source video
              |
              v
       Extract metadata/audio
              |
              v
          Transcription
              |
              v
       Analyze transcript
              |
              v
     Identify candidate moments
              |
              v
       Rank/select best clips
              |
              v
       Determine clip framing
              |
              v
       Generate 9:16 clips
              |
              v
          Output MP4s

The AI should primarily be responsible for deciding WHICH parts of the video are worth turning into clips.

Traditional video tools should be responsible for cutting, cropping, resizing, and encoding.

---

## 4. Input

### 4.1 Local file

Supported initially:

- MP4
- MOV
- MKV
- WebM
- other common FFmpeg-compatible formats

The frontend should allow drag-and-drop and file selection.

The backend should validate:

- extension
- MIME type where possible
- file size
- ability to decode with FFmpeg

Do not unnecessarily impose an aggressive file-size limit for personal use.

### 4.2 YouTube URL

Use `yt-dlp` to acquire the video.

The system should:

- validate that the URL is a supported YouTube URL
- download the best practical video/audio combination
- store it in a temporary working directory
- clean up temporary source files when processing is complete, unless retention is intentionally configured

Do not implement a custom YouTube downloader.

---

## 5. Clip Selection

This is the most important AI component of V1.

The system should not simply split a video into equal-length chunks.

It should identify moments that are suitable for short-form content.

### Desired characteristics

Prefer clips with:

- a strong opening/hook
- a complete thought or mini-story
- useful or interesting information
- emotional impact
- surprising statements
- humor
- controversy/debate
- curiosity
- clear context
- a satisfying ending
- minimal dependence on information far outside the clip

Avoid:

- long introductions
- dead air
- incomplete sentences
- clips requiring excessive external context
- repetitive sections
- sections dominated by silence
- sections with poor audio
- clips that start or end awkwardly

### Output from AI analysis

The AI should return structured data, not free-form prose.

Example:

```json
{
  "clips": [
    {
      "start": 272.5,
      "end": 321.8,
      "score": 94,
      "reason": "Strong hook followed by a complete and interesting explanation.",
      "title": "Example title"
    }
  ]
}
```

The exact schema may evolve.

Use Pydantic models for validation.

---

## 6. Transcript

Use an existing speech-to-text solution rather than implementing speech recognition.

Preferred initial option:

- `faster-whisper`

The transcript should retain timestamps.

Ideally preserve:

- segment start
- segment end
- text

If word-level timestamps are easily available, preserve them for future features, but V1 does not need to render subtitles.

Example internal representation:

```json
[
  {
    "start": 12.40,
    "end": 16.10,
    "text": "Example sentence."
  }
]
```

The transcript is an intermediate artifact and should be reusable for debugging/reprocessing.

---

## 7. Candidate Generation

Do not send an entire very-long transcript to the LLM blindly.

A sensible pipeline is:

1. Obtain timestamped transcript.
2. Detect natural boundaries:
   - sentence boundaries
   - transcript segments
   - pauses
   - scene changes where practical
3. Build candidate windows.
4. Ask the LLM to evaluate candidates.
5. Rank candidates.
6. Remove overlapping selections.
7. Select the requested number of final clips.

The exact candidate-generation algorithm can be improved after the first working version.

---

## 8. Default Clip Settings

Initial defaults:

- Output aspect ratio: **9:16**
- Output resolution: **1080 × 1920**
- Output format: **MP4**
- Video codec: H.264
- Audio codec: AAC
- Number of clips: **5**
- Target duration: approximately **30–90 seconds**

These should be configurable where easy, but do not build a large settings system.

The generated clips should be compatible with common Shorts/Clips workflows.

---

## 9. Vertical Video / Smart Crop

The source video may be horizontal.

The system should convert it to a vertical 9:16 composition.

### V1 requirement

Prefer intelligent framing when practical.

For example, when a person is speaking in a 16:9 video, the vertical crop should try to keep the person visible rather than always using a fixed center crop.

Possible implementation approaches:

- face detection
- person detection
- tracking
- FFmpeg crop filters
- OpenCV
- an existing lightweight computer-vision model

Do NOT train a custom computer-vision model.

### Fallback

If no reliable subject can be detected:

- use a centered crop
- ensure output is always generated rather than failing

---

## 10. Video Processing

Use **FFmpeg** as the main video processing engine.

FFmpeg should handle:

- trimming
- crop
- scale
- aspect-ratio conversion
- audio handling
- encoding
- final MP4 generation

Do not use ComfyUI for normal video manipulation.

ComfyUI is NOT part of the required V1 architecture.

---

## 11. ComfyUI

ComfyUI should remain optional and out of the core pipeline.

Potential future use:

- AI-generated B-roll
- image generation
- video generation
- visual inserts
- advanced creative effects

These are explicitly out of scope for V1.

The application must work without ComfyUI installed.

---

## 12. LLM

Use an LLM through an abstraction layer.

The code should not hard-code application logic around one specific provider.

A provider interface should make it possible to use:

- OpenAI
- OpenRouter
- another OpenAI-compatible API

The LLM is used for semantic analysis and clip selection.

Keep prompts in dedicated files/modules rather than embedding large prompts throughout the code.

Require structured output where possible.

---

## 13. Suggested Architecture

Initial architecture:

    clipfactory/
    ├── app/
    │   ├── api/
    │   ├── core/
    │   ├── models/
    │   ├── services/
    │   ├── pipelines/
    │   └── prompts/
    ├── frontend/
    ├── tests/
    ├── data/
    ├── output/
    ├── downloads/
    ├── temp/
    ├── .env.example
    ├── .gitignore
    ├── README.md
    ├── pyproject.toml
    └── AGENTS.md

The exact structure may be adapted if the agent has a strong reason, but avoid unnecessary complexity.

---

## 14. Backend

Preferred stack:

- Python
- FastAPI
- Pydantic
- FFmpeg
- yt-dlp
- faster-whisper
- OpenAI-compatible LLM API

A lightweight background-job mechanism is desirable because video processing is long-running.

For V1, this can be simple:

- FastAPI creates a job
- a local worker/background process performs processing
- frontend polls job status or receives progress updates

Do not introduce distributed queues such as Celery unless actually needed.

---

## 15. Frontend

The frontend should be a simple local web application.

The first version should prioritize functionality over visual polish.

Required UI:

### Input section

- file drag-and-drop
- file picker
- YouTube URL input
- process button

### Processing section

- current state
- progress indicator
- useful status messages

Example:

    Downloading video...
    Transcribing...
    Finding interesting moments...
    Generating clip 2 of 5...
    Complete.

### Results section

For each clip:

- video preview
- clip number
- duration
- AI score
- short reason
- download button

No timeline editor is required.

---

## 16. Processing Job Model

A job should have a lifecycle similar to:

    CREATED
      |
      v
    ACQUIRING
      |
      v
    TRANSCRIBING
      |
      v
    ANALYZING
      |
      v
    RENDERING
      |
      v
    COMPLETED

Failure state:

    FAILED

Store useful error information for debugging.

Example:

```text
Job:
- id
- source
- status
- progress
- current_step
- created_at
- completed_at
- error
- generated_clips
```

Persistence can initially be lightweight. SQLite is sufficient for a personal application if persistence is needed.

Do not introduce PostgreSQL unless there is a concrete requirement.

---

## 17. File Management

Keep application-generated media outside Git.

Suggested directories:

    data/
        jobs/

    downloads/
        <job-id>/

    temp/
        <job-id>/

    output/
        <job-id>/
            clip_01.mp4
            clip_02.mp4
            clip_03.mp4

Use job IDs to prevent collisions.

Temporary files should be cleaned up after successful processing where appropriate.

Generated output should remain available until the user deletes it or an explicit cleanup policy removes it.

---

## 18. Configuration

Use environment variables for secrets/configuration.

Example `.env.example`:

```text
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
WHISPER_MODEL=
OUTPUT_DIR=./output
TEMP_DIR=./temp
DOWNLOAD_DIR=./downloads
```

Never commit `.env`.

Never hard-code API keys.

---

## 19. Logging

Use Python's standard logging facilities.

Log:

- job creation
- input acquisition
- transcription start/end
- AI analysis start/end
- selected clips
- rendering start/end
- failures
- cleanup

Do not log secrets or full API keys.

Useful logs should make it possible to understand why a job failed.

---

## 20. Error Handling

The application should gracefully handle:

- invalid YouTube URL
- failed YouTube download
- unsupported video
- corrupted video
- FFmpeg failure
- transcription failure
- LLM timeout
- invalid LLM response
- no suitable clips found
- crop/detection failure

Important principle:

**A failure in smart crop should not prevent clip generation.**

Fallback to center crop.

Likewise, if AI analysis produces invalid structured output, retry or fail the analysis step with a clear error rather than silently producing incorrect clips.

---

## 21. Testing

At minimum, create tests for:

### Unit tests

- transcript parsing
- clip schema validation
- candidate generation
- overlap removal
- clip ranking
- configuration
- filename/path generation

### Integration tests

Where practical:

- FFmpeg clip extraction
- aspect ratio conversion
- end-to-end processing with a short test video

Avoid requiring paid APIs in ordinary unit tests.

Mock the LLM.

---

## 22. Development Environment

The project is primarily intended to run locally on Windows initially.

The developer has experience with:

- Python
- C++
- Linux
- FastAPI
- AI agents
- LangGraph
- OpenAI-compatible APIs
- Docker
- ComfyUI

Do not assume Docker is required for V1.

The simplest local development experience is preferred.

---

## 23. Hardware Considerations

The application should be efficient on a personal workstation/laptop.

Normal video operations:

- FFmpeg crop
- trimming
- encoding
- resizing

should not require ComfyUI or generative AI.

GPU acceleration may be used where beneficial, but it should not be a hard dependency unless required by a selected model.

The user has an NVIDIA GPU with approximately 6 GB VRAM.

Avoid architectures that require large GPU memory.

---

## 24. NPU

Do not design V1 around NPU acceleration.

NPU support is optional future optimization only.

The application should work correctly using:

- CPU
- NVIDIA GPU where available
- external LLM API

---

## 25. AI Prompting Principles

The clip-selection prompt should emphasize that the model is selecting content, not writing a summary.

The model should prefer clips that work independently.

A useful conceptual instruction:

"You are selecting moments from a long-form video that can stand alone as engaging short-form videos. Choose moments with a strong hook, clear context, useful information, emotion, humor, surprise, or curiosity. Avoid sections that require extensive context from the rest of the video."

The model should return machine-readable structured data.

Do not let the model directly control FFmpeg commands.

The model selects timestamps; application code validates and executes them.

---

## 26. Security

This is a local personal application, but basic hygiene is still required.

- Never expose API keys in frontend code.
- Validate user-provided paths.
- Do not allow arbitrary shell command construction from LLM output.
- FFmpeg arguments must be constructed by trusted application code.
- Do not execute LLM-generated commands.
- Sanitize filenames.
- Keep generated media in controlled directories.

---

## 27. Non-Goals for V1

Explicitly do NOT implement:

- user accounts
- authentication
- authorization
- payments
- subscriptions
- social-media publishing
- cloud deployment
- team collaboration
- public API
- mobile application
- full video editor
- timeline
- subtitles/captions
- AI voice-over
- AI B-roll
- music generation
- thumbnail generation
- automatic title/description publishing
- analytics
- recommendation learning from social performance
- custom ML training
- ComfyUI integration

These can be considered later only if actual personal usage shows a need.

---

## 28. Future Features

Possible future evolution:

### V1.1

- captions
- configurable caption styles
- better face/person tracking
- configurable clip count/duration
- better preview

### V1.2

- AI-generated hooks
- titles
- descriptions
- automatic B-roll suggestions

### V2

- ComfyUI integration
- AI-generated B-roll
- automatic thumbnails
- multilingual subtitles
- automatic translation
- content-specific selection strategies

Potentially useful selection profiles:

    General
    Educational
    Funny
    Emotional
    Technical
    Storytelling

---

## 29. Product Philosophy

ClipFactory is a personal automation tool, not a SaaS platform.

Prioritize:

1. Output quality
2. Simple workflow
3. Reliability
4. Local execution
5. Fast processing
6. Easy debugging
7. Minimal dependencies
8. Simple architecture

Avoid:

- speculative abstractions
- premature scalability
- unnecessary microservices
- unnecessary databases
- unnecessary agent frameworks
- complex frontend architecture
- building features because commercial competitors have them

---

## 30. Definition of Done for V1

V1 is complete when the following workflow works end-to-end:

1. User starts ClipFactory.
2. User uploads a local video OR provides a YouTube URL.
3. ClipFactory acquires the source.
4. ClipFactory transcribes the video.
5. ClipFactory identifies the best moments using an LLM.
6. ClipFactory selects approximately 5 non-overlapping clips.
7. ClipFactory converts each clip to 1080x1920 9:16.
8. ClipFactory keeps the main speaker/subject visible when possible.
9. ClipFactory falls back gracefully to center crop.
10. ClipFactory writes MP4 files.
11. User can preview the clips in the browser.
12. User can download/use the clips manually.
13. Temporary processing files are cleaned up.
14. No API secrets or generated media are committed to Git.

---

## 31. Agent Instructions

When implementing ClipFactory:

### General

- Build the smallest working solution first.
- Do not implement future features unless explicitly requested.
- Prefer simple, well-known libraries.
- Keep components loosely coupled but do not over-abstract.
- Write readable Python.
- Use type hints.
- Use Pydantic for external/structured data.
- Add tests for non-trivial logic.

### AI

- Treat LLM output as untrusted data.
- Validate all structured output.
- Never execute LLM-generated shell commands.
- Keep AI prompts version-controlled in the repository.
- Make the LLM provider configurable.

### Video

- Use FFmpeg.
- Do not use ComfyUI for ordinary video manipulation.
- Keep source, temporary, and output files separate.
- Prefer robust fallbacks over hard failures.

### UX

- The user should understand what the application is doing.
- Long-running operations must not freeze the browser.
- Show meaningful processing states.
- Generated clips should be immediately accessible.

### Architecture

- Start as a single application.
- Avoid microservices.
- Avoid Kubernetes.
- Avoid Redis/Celery unless a concrete problem requires them.
- SQLite is sufficient for initial persistence.
- Keep the application runnable locally with minimal setup.

---

## 32. Suggested Initial Dependencies

Start with a small dependency set.

Potential dependencies:

```text
fastapi
uvicorn
python-multipart
pydantic
pydantic-settings
yt-dlp
openai
faster-whisper
```

Potentially:

```text
opencv-python
```

for smart cropping/detection.

FFmpeg should be installed as a system dependency rather than bundled into Python unless there is a compelling reason otherwise.

Frontend technology should be chosen for simplicity. A lightweight HTML/JS frontend is acceptable for V1.

---

## 33. Recommended Implementation Order

Implement in this order:

### Phase 1 — Skeleton

- repository structure
- FastAPI application
- configuration
- health endpoint
- basic frontend

### Phase 2 — Input

- local upload
- YouTube URL
- yt-dlp integration

### Phase 3 — Video utilities

- FFmpeg wrapper
- metadata extraction
- clip extraction
- 9:16 conversion

### Phase 4 — Transcription

- faster-whisper integration
- timestamped transcript model

### Phase 5 — AI selection

- candidate generation
- LLM prompt
- structured response
- ranking
- overlap removal

### Phase 6 — Smart crop

- subject/face detection
- tracking
- center-crop fallback

### Phase 7 — End-to-end jobs

- background processing
- job state
- progress
- error handling

### Phase 8 — Results UI

- previews
- metadata
- downloads

### Phase 9 — Cleanup

- tests
- documentation
- logging
- temporary-file cleanup
- configuration cleanup

Do not start with Phase 6 or future AI-generation functionality.

---

## 34. First Milestone

The first implementation milestone should be:

**Local video → transcribe → AI selects clips → FFmpeg creates 5 vertical MP4s.**

The UI can initially be minimal.

Once that pipeline works reliably, improve the UI and smart crop.

---

## 35. Git Repository

Repository name:

**ClipFactory**

Suggested GitHub description:

**AI-powered tool that automatically identifies the best moments from long-form videos and turns them into vertical clips for Shorts and Clips.**

Recommended:

- `.gitignore`: Python
- License: MIT

Do not commit:

- `.env`
- source videos
- generated videos
- downloaded YouTube files
- AI model files
- temporary files
- local databases if they contain personal data

Suggested `.gitignore` additions:

```gitignore
# Environment
.env
.env.*

# Virtual environments
.venv/
venv/

# IDE
.vscode/

# Python
__pycache__/
*.py[cod]
.pytest_cache/

# Application data
data/
output/
downloads/
temp/

# Media
*.mp4
*.mov
*.mkv
*.avi
*.webm

# Models
models/
*.safetensors
*.pt
*.pth
*.onnx
```

---

## 36. Final Instruction to the Coding Agent

Build ClipFactory as a simple, local-first personal application.

The first goal is not to reproduce Ssemble.

The first goal is:

    VIDEO
      ↓
    TRANSCRIPT
      ↓
    AI BEST MOMENTS
      ↓
    VERTICAL 9:16 MP4s

Everything else is secondary.

When uncertain between a simple implementation and a more complex architecture, choose the simple implementation unless the complexity provides a concrete benefit to the V1 requirements above.
