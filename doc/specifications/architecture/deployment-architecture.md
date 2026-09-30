# Deployment Architecture

Operational procedure: [23-deployment.md](../23-deployment.md).
Diagram: [diagrams/deployment.puml](diagrams/deployment.puml).

## Runtime topology

```text
Owner browser (Windows) ──http://localhost:8000──► WSL2: clipfactory serve
                                                     │  FastAPI + SPA + workflow + scheduler (1 process, 1 worker)
                                                     │  FFmpeg / FFprobe subprocesses
                                                     │  faster-whisper, wan_local (threads, CUDA via WSL2)
                                                     ├──► PostgreSQL 16 (native in WSL2)
                                                     ├──► data directory (WSL2 ext4)
                                                     ├──► ComfyUI (local HTTP, optional)
                                                     └──► outbound HTTPS to providers (LLM, TTS, media, news, Higgsfield, platforms)
Instagram / Facebook servers ──HTTPS──► owner reverse proxy ──(/public/media/* only)──► WSL2 backend
```

## Constraints

- Single host, single app replica, single worker (CF-NFR-001). No containers (OD-018).
- Inbound: the app's HTTP port on loopback; the only public path is
  `/public/media/*` through the owner's reverse proxy (CF-NFR-114).
- The process runs as the owner's WSL2 user and needs write access only to
  the data directory.
- Whisper and Wan model files are cached under the user's Hugging Face cache
  so first-run downloads happen once.
- GPU: small laptop GPU (OD-005, OD-015); CPU-only must still work for
  everything except local video generation.

## Environments

| Environment | Providers | Database | Publishing mode |
| --- | --- | --- | --- |
| `test` (CI) | `fake` only | Ephemeral PostgreSQL service (CI) | `dry_run` |
| `development` | Fakes or real, per `.env` | Native PostgreSQL in WSL2 | `dry_run` |
| `production` | Real | Native PostgreSQL in WSL2 | Owner-selected (`dry_run` until verified) |
