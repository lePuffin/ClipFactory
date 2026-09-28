# ClipFactory v0.5.0

ClipFactory is a local-first personal tool for turning related source material into a watchable vertical rough clip. v0.5.0 accepts multiple local videos, YouTube URLs, article URLs, pasted article text, and local images; it explicitly evaluates story candidates, selects a truthful editorial angle and hook, writes a provenance-backed short-form script, plans source visuals, and renders a $1080 \times 1920$ H.264 MP4 with synchronized AI narration, readable text overlays, and optionally ducked source audio.

The earlier source-video clip extraction and v0.2 Smart Crop workflows remain available through their existing APIs. Set `TTS_ENABLED=false` to retain the silent v0.4 rough-clip behavior; B-roll, music, and dedicated captions remain out of scope.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12, managed automatically by UV when needed
- FFmpeg and FFprobe on `PATH`
- An OpenRouter API key
- A configured local TTS provider for narrated jobs: Chatterbox Turbo is the default, while `pyttsx3` requires a platform voice engine such as `espeak-ng` on Linux

Install FFmpeg before running a job:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Windows PowerShell
winget install --id=Gyan.FFmpeg -e

# macOS
brew install ffmpeg
```

## Setup

```bash
uv sync --all-groups
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env` for the second command. Set the following value in `.env`:

```dotenv
OPENROUTER_API_KEY=your_openrouter_key
```

`LLM_MODEL` defaults to `openai/gpt-4o-mini`; select an OpenRouter model that supports JSON responses, and vision inputs when using local image sources. Free OpenRouter models can temporarily return a shared-pool `429`; ClipFactory retries the unchanged request using the provider's delay and never switches to a paid model. `LLM_SCRIPT_MAX_TOKENS` defaults to `8000` so compact structured script repairs can finish; lower it for a provider with a smaller completion limit. The first transcription run downloads the configured `faster-whisper` model.

## Run

```bash
uv run clipfactory
```

Open `http://127.0.0.1:8000` in a browser. The header reports missing local prerequisites before a run starts.

For automatic reload while developing:

```bash
uv run uvicorn app.main:app --reload
```

## Test

```bash
uv run pytest
uv run ruff check app tests
uv build
```

The ordinary test suite does not download a Whisper model, call OpenRouter, download YouTube content, or require FFmpeg. It uses fakes for those external boundaries and verifies the pipeline, source validation, command construction, storage, and HTTP endpoints.

The v0.5 renderer acceptance test creates a tiny synthetic video/image/article fixture, uses a deterministic audible provider, and requires local FFmpeg:

```bash
uv run pytest tests/test_reel_rendering.py
```

Run the configured real TTS provider only when deliberately requested. This test can download/load a local voice model or require a platform speech engine:

```bash
CLIPFACTORY_REAL_TTS=1 uv run pytest tests/test_real_tts.py
```

## v0.5 Narrated Rough Clip Pipeline

```text
Videos + YouTube URLs + articles + pasted text + images
 |
 v
Normalize and acquire sources
 |
 v
Extract article paragraphs/images and timestamped video transcripts
 |
 v
Analyze individual sources with structured, provenance-bound output
 |
 v
Generate coherent story candidates
 |
 v
Evaluate candidates with explicit score dimensions and select the strongest story
 |
 v
Generate and evaluate editorial angles, then select a truthful angle and hook
 |
 v
Generate and validate a structured, evidence-backed short-form script with visual intent
 |
 v
Plan source video/image/text-card scenes and validate visual references
 |
 v
Segment scene narration, synthesize sequentially, normalize/cache WAVs, and measure real durations
 |
 v
Extend scenes to preserve spoken narration, then render source scenes with Smart Crop and narration text overlays
 |
 v
Mix narration with optional ducked source audio
 |
 v
output/<job-id>/story_01.mp4 + story_01.json + narration.wav
```

Each pipeline stage is explicit: `Source -> ExtractedContent -> SourceAnalysis -> StoryCandidate -> EditorialEvaluation -> EditorialAngle -> Hook -> Script -> Scene -> NarrationSegment -> MeasuredAudio -> RenderedVideo`. Structured LLM outputs are validated before their IDs, timestamps, or asset references can influence FFmpeg. The renderer never decides the story or directly consumes an unvalidated LLM response.

## v0.4 Editorial Engine

Story candidate generation keeps related topics separate. Each candidate is evaluated across normalized `importance`, `novelty`, `audience_interest`, `clarity`, `storytelling_potential`, `factual_support`, `visual_potential`, and `source_coverage` dimensions. The LLM supplies an auditable structured assessment; ClipFactory applies configurable local weights and deterministic ID tie-breaking to select the winner.

The selected story receives multiple evidence-backed editorial angles. Their evaluations use the same deterministic score calculation. A dedicated hook stage proposes concise, truthful openings before the script is written. The chosen angle and hook, their reasons, and all candidates remain in the JSON plan for review.

Scripts use an explicit short-form narrative subset of `hook`, `context`, `development`, `key_revelation`, `implication`, and `ending`. Every section labels its statement as a `fact`, `source_claim`, `inference`, or `opinion`, retains evidence references, and records visual intent, preferred visual type, and optional available asset IDs. Scripts are timed from word count at `REEL_WORDS_PER_MINUTE`, not trusted LLM duration declarations.

Before rendering, deterministic validation verifies story, angle, and hook identity; source and evidence references; word-count duration; non-empty and non-duplicated sections; visual asset references; and conservative lexical support for each substantive claim. Material source conflicts are retained on the candidate and must be attributed when a section combines conflicting sources. A rejected script gets one controlled structured repair request and is validated again.

## Sources and Provenance

The **Rough clip** workbench accepts any combination of local video, local image, URL, and pasted article text. URLs are classified as supported YouTube videos where applicable; other public `http` or `https` URLs are article sources. Pasted text needs at least 120 characters.

Video transcripts receive stable segment IDs such as `video-01-seg-001` and retain their timestamps. Article paragraphs receive IDs such as `article-01-p-001`; local and article images receive source-owned asset IDs. Every source analysis claim, story key point, angle, hook, script section, rendered scene, and narration segment retains one or more evidence references. The clip plan records candidate scores, selection reasons, source usage, script provenance, visual intent, visual decisions, provider choices, cache identity, and measured narration timing.

The default rough-clip script target is 20-60 seconds. Measured speech, rather than a character estimate, controls the final scene duration: the conservative `extend_scene` policy freezes the last valid source-video frame or continues an image/text-card visual instead of cutting narration. Visual selection prefers relevant source video, then source image, article image, and finally a non-black text card. Video scenes reuse the v0.2 dynamic Smart Crop renderer.

API clients submit multipart requests to `POST /api/jobs/story-clip`. Repeat `video_files`, `image_files`, `urls`, or `article_texts` as needed. Explicit `youtube_urls` and `article_urls` remain available as compatibility fields. A completed MP4 is available from `GET /api/jobs/<job-id>/story-clip`; the complete machine-readable plan is available from `GET /api/jobs/<job-id>/story-clip/plan`.

Completed rough clips remain in `output/<job-id>/`:

```text
output/<job-id>/
 story_01.mp4
 story_01.json
 narration.wav
```

Use `story_01.json` to inspect the selected story and score, candidate evaluations, selected angle and score, hook, normalized sources, script sections and their evidence, visual intent, scene visuals, and narration metadata. The assembled WAV is retained with the completed reel for diagnostics. Intermediate source, candidate, editorial, script, scene, and `reel_narration.json` metadata are retained in `data/jobs/<job-id>/`; temporary uploads, downloads, and intermediate audio are removed after a successful job. Failed-job temporary files are retained for diagnosis.

To compare a v0.5 run against a retained v0.4 plan, submit the same sources, then compare `story_01.json` files and their MP4s. Review the selected story, weighted score dimensions, selected angle and hook, evidence attached to every script section, visual intent, narration timing, and the final rendered scenes. The browser result panel surfaces the selected story, scores, angle, hook, script, sources, scenes, narration diagnostics, MP4 preview, and both downloadable artifacts.

## v0.5 Narration

The configured provider is selected per job through the browser workbench or multipart `POST /api/jobs/story-clip` fields: `tts_enabled`, `tts_provider`, `tts_voice`, `tts_language`, and `tts_speed`. Those generic choices are persisted on the job so a queued run cannot change when the environment changes. The provider interface is independent of the editorial and renderer layers; Chatterbox Turbo and `pyttsx3` are practical local adapters, and no provider silently falls back to another.

Each scene is a meaningful narration unit. The original validated script text remains intact, while a conservative preprocessing pass only spaces short all-capital acronyms for speech. Generated segment WAVs are normalized to mono PCM at `TTS_AUDIO_SAMPLE_RATE`, measured with FFprobe, assembled with deliberate inter-segment pauses, and cached under `data/cache/tts/` using provider, model, voice, language, speed, text, and sample rate. Corrupt cache entries are discarded and regenerated.

When source audio is enabled, ClipFactory creates a scene-aligned source-audio timeline, pads unavailable intervals with silence, lowers it to `TTS_SOURCE_AUDIO_VOLUME`, and uses smooth FFmpeg sidechain ducking while narration is active. Set `TTS_SOURCE_AUDIO_ENABLED=false` for narration-only output or `TTS_DUCKING_ENABLED=false` to mix the configured source level without ducking. A selected unavailable provider fails only that job with its useful provider error; application startup remains available. `TTS_FALLBACK_ENABLED=true` is the explicit opt-in for legacy Chatterbox jobs to fall back to `pyttsx3`.

## Smart Framing

ClipFactory uses the local OpenCV Haar face detector already installed by UV. It samples each
selected clip at a configurable interval rather than running detection on every frame. The
framing planner detects abrupt scene changes from frame histograms, resets tracking at those
boundaries, selects a primary face deterministically, and generates a bounded camera path.

Raw targets are filtered by a dead zone, low-pass smoothing, and a maximum camera speed before
FFmpeg interpolates the crop position during a single render. The crop always remains within the
source frame and preserves a 9:16 output.

When detection is briefly unavailable, the virtual camera holds its last reliable target. If no
reliable target is available, ClipFactory uses a static face-based crop when possible and otherwise
uses the centered v0.1 fallback. A framing failure never fails the job.

Set `SMART_CROP_DEBUG=true` to retain `data/jobs/<job-id>/framing.json`. It records the per-clip
rendering mode, scene changes, selected subject IDs, target/camera coordinates, confidence, and
tracking validity. Normal runs log only a compact framing summary per clip.

The bundled Haar detector is lightweight and fully local, but works best for reasonably clear,
front-facing talking heads. Profile faces, heavy occlusion, rapid cuts, and very small subjects can
fall back to static framing. No model download, cloud vision service, or GPU is required.

## Configuration

The complete configurable values are documented in `.env.example`:

- `OPENROUTER_API_KEY` or the compatible alias `LLM_API_KEY`
- `OPENROUTER_BASE_URL` or `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_RATE_LIMIT_RETRIES`, `LLM_RATE_LIMIT_MAX_WAIT_SECONDS` (default 3 retries and a 60-second wait cap)
- `LLM_SCRIPT_MAX_TOKENS` (default 8000 for complete structured script responses)
- `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`
- `OUTPUT_WIDTH`, `OUTPUT_HEIGHT` (even 9:16 output dimensions; defaults to 1080x1920)
- `OUTPUT_DIR`, `TEMP_DIR`, `DOWNLOAD_DIR`, `DATA_DIR`
- `MAX_UPLOAD_SIZE_BYTES`
- `CLIP_MIN_DURATION_SECONDS`, `CLIP_MAX_DURATION_SECONDS`
- `REEL_MIN_DURATION_SECONDS`, `REEL_MAX_DURATION_SECONDS` (default 20-60 seconds)
- `REEL_WORDS_PER_MINUTE` (default 155; used for script timing)
- `EDITORIAL_*_WEIGHT` for each inspectable story and angle score dimension
- `TTS_ENABLED`, `TTS_PROVIDER` (or legacy `TTS_BACKEND`), `TTS_MODEL`, `TTS_VOICE`, `TTS_LANGUAGE`, `TTS_SPEED`, `TTS_RATE`, `TTS_SENTENCE_PAUSE_SECONDS`, and `TTS_TIMING_POLICY`
- `TTS_CACHE_ENABLED`, `TTS_AUDIO_SAMPLE_RATE`, `TTS_NARRATION_VOLUME`, `TTS_SOURCE_AUDIO_ENABLED`, `TTS_SOURCE_AUDIO_VOLUME`, `TTS_DUCKING_ENABLED`, `TTS_FALLBACK_ENABLED`, and `TTS_FORCE_CPU`
- `SMART_CROP_ENABLED`
- `SMART_CROP_DETECTION_INTERVAL_SECONDS`
- `SMART_CROP_DETECTION_CONFIDENCE_THRESHOLD`, `SMART_CROP_TRACKING_CONFIDENCE_THRESHOLD`
- `SMART_CROP_SMOOTHING_STRENGTH`, `SMART_CROP_DEAD_ZONE_PIXELS`
- `SMART_CROP_MAX_CAMERA_SPEED_PIXELS_PER_SECOND`
- `SMART_CROP_SCENE_CHANGE_THRESHOLD`, `SMART_CROP_TRACKING_GRACE_SECONDS`
- `SMART_CROP_DEBUG`

No secrets, local job data, downloaded media, generated clips, or model files are tracked by Git.
