# ClipFactory Agent Guide

## Scope

ClipFactory is a single-user, local-first FastAPI application. Keep V1 focused on source acquisition, transcription, semantic clip selection, vertical rendering, preview, and download. Do not add accounts, distributed queues, cloud deployment, social publishing, captions, timelines, ComfyUI, or other future features without an explicit request.

## Commands

```bash
uv sync --all-groups
uv run pytest
uv run ruff check app tests
uv run clipfactory
```

## Conventions

- Use Python 3.12 through UV and preserve the `uv.lock` file.
- Keep external boundaries behind `app/services/`; pipeline coordination belongs in `app/pipelines/`.
- Treat LLM responses as untrusted: validate them with Pydantic before timestamps reach FFmpeg.
- Build subprocess calls as argument lists. Never execute generated shell commands.
- Keep source media, temporary work, transcripts, and output in their respective configured directories.
- Keep tests offline and deterministic. Mock or fake OpenRouter, FFmpeg, Whisper, and yt-dlp in ordinary tests.
- Prefer small, typed, readable changes over additional infrastructure.
