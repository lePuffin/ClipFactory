# Deployment Architecture

Operational procedure: [23-deployment.md](../23-deployment.md).
Diagram: [diagrams/deployment.puml](diagrams/deployment.puml).

## Runtime topology

```text
Owner browser (Windows) ──http://localhost:8000──► WSL2: clipfactory run
                                                     │  FastAPI + SPA + workflow + scheduler (1 process, 1 worker)
                                                     │  FFmpeg / FFprobe subprocesses
                                                     │  HyperFrames (pinned local Node package) / Manim (optional local Python group)
                                                     │  faster-whisper, wan_local (threads, CUDA via WSL2)
                                                     ├──► PostgreSQL 16 (Docker Compose)
                                                     ├──► Dragonfly (Docker Compose; LLM RPM/circuit state only)
                                                     ├──► data directory (WSL2 ext4)
                                                     ├──► ComfyUI (local HTTP, optional)
                                                     └──► outbound HTTPS to providers (LLM, TTS, media, news, Higgsfield, platforms)
Instagram / Facebook servers ──HTTPS──► owner reverse proxy ──(/public/media/* only)──► WSL2 backend
```

## Constraints

- Single host, single native app replica, single worker (CF-NFR-001).
  Containers are limited to PostgreSQL and Dragonfly (ADR-016).
- Inbound: the app's HTTP port on loopback; the only public path is
  `/public/media/*` through the owner's reverse proxy (CF-NFR-114).
- The process runs as the owner's WSL2 user and needs write access only to
  the data directory.
- HyperFrames runs locally using its exact-version-pinned Node package;
  Manim is installed only in the optional `graphics-manim` Python dependency
  group. Neither renderer is containerized or exposed as a network service.
- Local graphics work and recovery files stay under DATA_DIR. Renderer
  executable/package paths, FPS and subprocess timeout come from canonical
  configuration; renderer subprocess cancellation is scoped to its own IDs.
- Whisper and Wan model files are cached under the user's Hugging Face cache
  so first-run downloads happen once.
- GPU: small laptop GPU (OD-005, OD-015); CPU-only must still work for
  everything except local video generation.

## Environments

| Environment | Providers | Database | Publishing mode |
| --- | --- | --- | --- |
| `test` (CI) | `fake` only | Ephemeral PostgreSQL + Dragonfly services | `dry_run` |
| `development` | Fakes or real, per `.env` | Compose-managed PostgreSQL + Dragonfly | `dry_run` |
| `production` | Real | Compose-managed PostgreSQL + Dragonfly on the owner host | Owner-selected (`dry_run` until verified) |
