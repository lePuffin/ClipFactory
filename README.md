# ClipFactory

ClipFactory is a local-first personal tool that finds strong moments in long-form videos and renders them as vertical MP4 clips for Shorts and Reels.

It accepts a local video or a YouTube URL, transcribes it with `faster-whisper`, uses an OpenRouter-backed LLM to select non-overlapping moments, and renders $1080 \times 1920$ H.264/AAC MP4s through FFmpeg.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12, managed automatically by UV when needed
- FFmpeg and FFprobe on `PATH`
- An OpenRouter API key

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

`LLM_MODEL` defaults to `openai/gpt-4o-mini`; change it to any OpenRouter model that supports JSON responses. The first transcription run downloads the configured `faster-whisper` model.

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

## Pipeline

```text
Local file or YouTube URL
 |
 v
Acquire and validate source video
 |
 v
Extract audio and transcribe with faster-whisper
 |
 v
Build timestamp-aligned candidate windows
 |
 v
OpenRouter selects structured clip candidates
 |
 v
Validate, rank, and remove overlap
 |
 v
Sparse face detection, scene-aware tracking, and a smoothed virtual camera
 |
 v
FFmpeg render with a dynamic crop path and static fallback
```

Completed clips remain in `output/<job-id>/`. Timestamped transcripts are retained in `data/jobs/<job-id>/` for debugging or reprocessing. Temporary upload/download and audio files are removed after successful jobs; failed-job temporary files are retained for debugging.

## Sources

The **Sources** tab creates one managed reel job from any number of local videos, URLs, or pasted
article texts. A URL is classified as a supported YouTube video when applicable; other public
`http` or `https` URLs are treated as articles. One meaningful source is enough. Each source can
be removed before the job is submitted, and pasted article text must contain at least 120 characters.

The narration model chooses the reel's total duration and sentence-level timing from the available
context. The server permits scripts from 30 to 300 seconds by default; change
`REEL_MIN_DURATION_SECONDS` or `REEL_MAX_DURATION_SECONDS` only when a different safety range is
needed. Relevant source-video intervals are selected per narration sentence and rendered through
the existing smart-framing system.

API clients can submit the same multipart request to `POST /api/jobs/reel`. Repeat `video_files`,
`urls`, or `article_texts` as needed. Older `youtube_urls` and `article_urls` fields remain accepted
for compatibility. A completed reel is available from `GET /api/jobs/<job-id>/reel`.

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
- `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`
- `OUTPUT_WIDTH`, `OUTPUT_HEIGHT` (even 9:16 output dimensions; defaults to 1080x1920)
- `OUTPUT_DIR`, `TEMP_DIR`, `DOWNLOAD_DIR`, `DATA_DIR`
- `MAX_UPLOAD_SIZE_BYTES`
- `REEL_MIN_DURATION_SECONDS`, `REEL_MAX_DURATION_SECONDS`
- `SMART_CROP_ENABLED`
- `SMART_CROP_DETECTION_INTERVAL_SECONDS`
- `SMART_CROP_DETECTION_CONFIDENCE_THRESHOLD`, `SMART_CROP_TRACKING_CONFIDENCE_THRESHOLD`
- `SMART_CROP_SMOOTHING_STRENGTH`, `SMART_CROP_DEAD_ZONE_PIXELS`
- `SMART_CROP_MAX_CAMERA_SPEED_PIXELS_PER_SECOND`
- `SMART_CROP_SCENE_CHANGE_THRESHOLD`, `SMART_CROP_TRACKING_GRACE_SECONDS`
- `SMART_CROP_DEBUG`

No secrets, local job data, downloaded media, generated clips, or model files are tracked by Git.
