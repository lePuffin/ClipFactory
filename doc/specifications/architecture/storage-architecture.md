# Storage Architecture

Decisions: [ADR-003](../decisions/ADR-003-postgresql.md), [ADR-006](../decisions/ADR-006-local-filesystem-storage.md).

## PostgreSQL

Single database. Tables (outline; columns follow [04-domain-model.md](../04-domain-model.md)):

| Table | Notes |
| --- | --- |
| `content_profile` | Partial unique index on `is_active` where true |
| `app_settings` | `section` primary key, `value` JSONB, `updated_at` |
| `run` | Partial unique index enforcing one `queued`/`running` Run (CF-REQ-652) |
| `run_event` | Unique (`run_id`, `sequence`); index on `run_id` |
| `source` | Unique `canonical_url`; index on `text_hash` |
| `story`, `story_source` | |
| `claim`, `claim_evidence` | |
| `story_package`, `script_version`, `visual_plan_version` | JSONB for segment lists |
| `asset` | Unique `sha256` among active; GIN index on `to_tsvector(description | | tags | | subjects)`; GIN on`tags`,`subjects` |
| `clip`, `asset_usage` | |
| `evaluation` | JSONB `issues`, `warnings`, `actions`, `metrics` |
| `publication` | Unique (`clip_id`, `platform`) |
| `metric_snapshot` | Unique (`publication_id`, `offset_label`) |
| `scheduled_task` | Index on (`status`, `due_at`) |
| `cost_entry` | Index on (`run_id`), (`created_at`) for monthly totals |
| `llm_request` | Index on (`started_at`) for per-minute/daily counts; (`run_id`) |
| LangGraph checkpoint tables | Created by the checkpointer's setup, in the same database |

Rules:

- All schema changes via Alembic (CF-NFR-013). The LangGraph checkpoint
  tables are created via the checkpointer's setup call executed from an
  Alembic migration step or at startup (implementation choice; document it).
- Value objects with list shape (segments, cues, word timings) are JSONB
  columns validated by Pydantic on read/write.
- Timestamps are `timestamptz`; money is `numeric(12,4)` + currency.
- No secrets in any table (CF-NFR-106).

## Filesystem layout

Root: `DATA_DIR`.

```text
${DATA_DIR}/
├── assets/<sha256[0:2]>/<sha256>.<ext>      # reusable and non-reusable Asset files
├── clips/<clip_id>.mp4                      # rendered Clip candidates
├── work/<run_id>/                           # intermediates, LLM audit JSON, logs excerpts
│   ├── attempt-<n>/segments/<spec_hash>.mp4
│   ├── attempt-<n>/captions.ass
│   └── llm/<sequence>-<task>.json
├── cache/tts/<hash>.wav                     # narration cache (CF-REQ-302)
├── music/                                   # permanent local music library + manifest.json (CF-REQ-322)
├── comfyui-workflows/                       # owner-supplied ComfyUI templates + manifests (CF-REQ-217)
├── benchmarks/<timestamp>/                  # benchmark reports (CF-NFR-030)
├── fonts/                                   # optional user fonts (bundled fonts ship with the app)
└── secrets/                                 # OAuth token files, mode 0600
```

Storage keys are the relative paths above and satisfy CF-NFR-105. Asset
files are written once (content-addressed) and never modified.

## StorageProvider

Contract in [provider-architecture](provider-architecture.md#storageprovider).
`LocalStorageProvider` writes via a temporary file and atomic rename, verifies
SHA-256 for asset keys, and refuses keys outside the root.

## Retention

Implemented by the `retention_cleanup` scheduled task (CF-REQ-214):
`work/<run_id>` after `retention.work_dir_retention_days`; rejected Clip files
after `retention.rejected_clip_retention_days`; TTS cache entries unused for
the work-dir retention period. Reusable Assets, approved Clips and database
rows are never deleted automatically.
