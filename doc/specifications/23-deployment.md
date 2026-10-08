# 23 — Deployment

Architecture: [architecture/deployment-architecture.md](architecture/deployment-architecture.md),
diagram [deployment.puml](architecture/diagrams/deployment.puml).
The production host is decided (OD-018): **the owner's Windows machine under
WSL2 (Ubuntu), with a native backend and Compose-managed dependencies, started manually.**

This is the target operational contract approved on 2026-10-01; the commands
below are requirements and do not assert that the current implementation is complete.

## Topology

One WSL2 Linux environment running:

| Component | Form | Notes |
| --- | --- | --- |
| `clipfactory run` | Native `uv` install from `backend/` | FastAPI + workflow runner + scheduler + static frontend (`frontend/dist`) |
| PostgreSQL 16 | Docker Compose service | Only durable database and source of truth |
| Dragonfly | Docker Compose service | Disposable rolling LLM RPM/circuit state only |
| FFmpeg ≥ 6 | Native package with libx264, libass, aac | |
| Data directory | `DATA_DIR` on the WSL2 ext4 filesystem (not `/mnt/c`, for I/O speed) | Assets, Clips, work dirs, secrets/token files, ComfyUI workflows |
| ComfyUI (optional) | Owner-run local server at `COMFYUI_URL` | Only needed for local generation |
| Graphics renderers | HyperFrames local pinned Node package; optional Manim in `graphics-manim` | Native local subprocesses; not containers or network services |
| GPU | NVIDIA RTX PRO 500 Blackwell laptop GPU (≈ 4–6 GB VRAM) via WSL2 CUDA | Suitable for faster-whisper; local Wan video is expected to be slow or fail for memory reasons, so Higgsfield is the practical video generator (OD-005) |

The backend runs as **one process with one Uvicorn worker**, because the
scheduler and workflow runner are in-process and enforce the single-active-Run
rule (CF-REQ-652). Running multiple workers or replicas is unsupported in v1.0.

**Availability caveat:** the daily 05:00 Run only happens if WSL2 and
`clipfactory run` are running at that time. A missed Run is executed at
startup if within `scheduler.missed_run_grace_minutes`; otherwise it is
skipped and logged (CF-REQ-651). The dashboard shows the next scheduled time.

## Build and start

```bash
cd frontend && npm ci && npm run build                  # produces frontend/dist
cd .. && uv sync --locked                              # root runtime includes Wan and Manim
cd backend/renderers/hyperframes && npm ci              # exact HyperFrames package lock; local only
cd ../../..                                           # repository root
uv run clipfactory setup                                # Compose dependencies, migrations, defaults
uv run clipfactory doctor                               # read-only readiness checks
uv run clipfactory                                      # native process; runs pending migrations, then serves
```

The root Python runtime always includes the `local-gen` and `graphics-manim`
extras. Backend-only development installs may still select those groups.
HyperFrames is installed from the exact-pinned Node package lock in
`backend/renderers/hyperframes`.
Renderer setup details: [local graphics rendering](../setup/local-graphics-rendering.md).

## Startup sequence

1. Validate configuration and dependency health (CF-REQ-750, CF-REQ-757).
2. `alembic upgrade head` (run by `clipfactory run`; idempotent).
3. Seed defaults if absent (CF-REQ-754).
4. Resume or fail interrupted Runs (CF-REQ-657); mark `publishing` Publications `unknown_outcome` (CF-REQ-455).
5. Start the scheduler loop (unless disabled).
6. Serve API and static UI on `HOST:PORT`.

`PUBLIC_MEDIA_DIR` is optional and is not accessed or created by startup or
setup. An unavailable share does not block the application; `doctor` reports
it as a warning. Local production and signed media serving use `DATA_DIR`.

## Network exposure

Default bind is loopback. For remote UI access, prefer an SSH tunnel or a
private network (e.g. a VPN); if the UI is exposed, `API_TOKEN` is
mandatory (CF-NFR-101).

For Instagram and Facebook publishing (CF-REQ-461), the owner's reverse proxy exposes **only** `https://<public-host>/public/media/*` and forwards it to the WSL2 backend (WSL2 ports are reachable from Windows via `localhost`; the proxy runs on Windows or another host the owner controls). TLS terminates at the proxy. No other path is forwarded (CF-NFR-114).

## Backup and restore

- Backup: `pg_dump -Fc` of the database plus a copy of `DATA_DIR`
  (excluding `work/`), taken while no Run is active.
- Restore: create database, `pg_restore`, restore the data directory to the
  same path, start the app (migrations run automatically).
- Dragonfly is not backed up or restored; it contains no durable records.
- `secrets/` contains OAuth token files; protect backups accordingly.

## Upgrades

Stop the app (no active Run), back up, `git pull`, rebuild the frontend,
`uv sync --locked`, start (migrations run). Downgrades are supported only via
restore from backup.
