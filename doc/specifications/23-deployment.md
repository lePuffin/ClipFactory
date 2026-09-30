# 23 — Deployment

Architecture: [architecture/deployment-architecture.md](architecture/deployment-architecture.md),
diagram [deployment.puml](architecture/diagrams/deployment.puml).
The production host is decided (OD-018): **the owner's Windows machine under
WSL2 (Ubuntu), native install, no containers, started manually.**

## Topology

One WSL2 Linux environment running:

| Component | Form | Notes |
| --- | --- | --- |
| `clipfactory serve` | Native `uv` install from `backend/` | FastAPI + workflow runner + scheduler + static frontend (`frontend/dist`) |
| PostgreSQL 16 | Native package in WSL2 (`apt`) | Only database; started with `sudo service postgresql start` |
| FFmpeg ≥ 6 | Native package with libx264, libass, aac | |
| Data directory | `DATA_DIR` on the WSL2 ext4 filesystem (not `/mnt/c`, for I/O speed) | Assets, Clips, work dirs, secrets/token files, ComfyUI workflows |
| ComfyUI (optional) | Owner-run local server at `COMFYUI_URL` | Only needed for local generation |
| GPU | NVIDIA RTX PRO 500 Blackwell laptop GPU (≈ 4–6 GB VRAM) via WSL2 CUDA | Suitable for faster-whisper; local Wan video is expected to be slow or fail for memory reasons, so Higgsfield is the practical video generator (OD-005) |

The backend runs as **one process with one Uvicorn worker**, because the
scheduler and workflow runner are in-process and enforce the single-active-Run
rule (CF-REQ-652). Running multiple workers or replicas is unsupported in v1.0.

**Availability caveat:** the daily 05:00 Run only happens if WSL2 and
`clipfactory serve` are running at that time. A missed Run is executed at
startup if within `scheduler.missed_run_grace_minutes`; otherwise it is
skipped and logged (CF-REQ-651). The dashboard shows the next scheduled time.

## Build and start

```bash
cd frontend && npm ci && npm run build                  # produces frontend/dist
cd ../backend && uv sync --locked --no-dev              # add --group local-gen for native Wan
sudo service postgresql start
uv run clipfactory serve                                # runs migrations, then serves
```

The `local-gen` optional dependency group (PyTorch, diffusers) is installed
only when `wan_local` is enabled, keeping the default install light.

## Startup sequence

1. Validate configuration (CF-REQ-750).
2. `alembic upgrade head` (run by `clipfactory serve`; idempotent).
3. Seed defaults if absent (CF-REQ-754).
4. Resume or fail interrupted Runs (CF-REQ-657); mark `publishing` Publications `unknown_outcome` (CF-REQ-455).
5. Start the scheduler loop (unless disabled).
6. Serve API and static UI on `HOST:PORT`.

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
- `secrets/` contains OAuth token files; protect backups accordingly.

## Upgrades

Stop the app (no active Run), back up, `git pull`, rebuild the frontend,
`uv sync --locked`, start (migrations run). Downgrades are supported only via
restore from backup.
