# News Quality Rendering

Implementation slice delivered on 2026-10-06. This page describes tested repository entry points, not completion of every quality requirement.

## Reproduce A Retained-Content Render

From the repository root, with the normal `.env` and operational database configured:

```bash
uv run --project backend clipfactory db upgrade
uv run --project backend clipfactory import-audio database/clipfactory-data/quality-audio-manifest.json
uv run --project backend clipfactory render-saved database/clipfactory-data/news-quality-recipe.json
```

The manifests are private deployment data, not committed fixtures. `import-audio` validates one audio stream, full decode, byte limit, creator/licence/attribution and platform restrictions before activation; duplicate content reuses the existing Asset. Each render uses a new UUID and retains a PostgreSQL `render_revision` record plus a JSON sidecar. It does not rewrite the original failed Run or publish the output. No LLM, research, TTS or transcription call is made when reusing the stored inputs.

The recipe references a persisted `base_clip_id`, evidence-bound `overlays`, optional `music_asset_id`, timed licensed `sound_effects`, target platforms, template version and transition policy. It cannot supply arbitrary output paths. Labels are independently timed from subtitles, measured and checked for evidence, readable dwell, output bounds and collisions. Unverified person labels are rejected. The conservative subtitle band is Provisional, not a guarantee about changing platform interfaces.

## Review In The Application

The API exposes `POST /api/render-revisions`, `GET /api/render-revisions/{revision_id}` and authenticated/range-capable `GET /api/render-revisions/{revision_id}/media`. The UI route `/review/{revision_id}` provides exact-file playback, sources/credits, pending status and targeted label edits/rerender. Generated API types come from OpenAPI. A changed recipe creates a new revision; no stale approval is carried over. The preview page does not offer publication approval for pending evidence.

## Full Video Test

The tested revision is [82a7aee7-dbcc-482a-94ab-f54f7d105f4c.mp4](../../database/clipfactory-data/clips/revisions/82a7aee7-dbcc-482a-94ab-f54f7d105f4c.mp4), with its [saved recipe/evidence sidecar](../../database/clipfactory-data/clips/revisions/82a7aee7-dbcc-482a-94ab-f54f7d105f4c.json). It contains the retained grounded news narration, reviewed location imagery and B-roll, eight contextual editorial graphics, restrained motion/transitions, a licence-verified human-performed CC0 ambient bed and neutral original procedural information cues. Archive/illustrative labels remain visible; sensitive reporting has no promotional CTA or invented event audio.

Real FFmpeg probe/full decode reports 72.600 seconds, 720x1280 H.264/yuv420p, constant 30 FPS and stereo AAC at 48 kHz. Final mixed audio measured -14.89 LUFS and -4.25 dBTP. Browser playback reached the complete 72.6-second end at 2x speed without a media error; seeking and nonblank frame checks passed. Desktop and 390-pixel mobile review layouts had no horizontal overflow, and editable fields had readable contrast. Frames were inspected for label/subtitle collisions and factual attribution. These checks do not constitute measured audience engagement or an owner listening/approval decision.

## Validation Record

Backend: Ruff lint/format and Pyright passed; pytest passed 259 tests with three existing resource warnings and measured 76 percent combined coverage. Frontend: lint, types, all 15 tests and production build passed. The real layered integration checks independent overlay timing/pixels and narration/music/SFX mixing; the saved-content service regression confirms retained narration bytes and zero research/model/TTS/transcription call counters. API contracts are generated into frontend types. Browser full-duration playback, seeking, nonblank frames, desktop/mobile overflow and field contrast were checked; the review page intentionally has no Approve button for pending evidence. These results verify this slice, not every quality requirement or future engagement metrics.

## Current Limitations

- New rendering inputs and saved-package workflow are implemented; automatic beat generation from the writing call and batched candidate-model review are still pending.
- Owner identity confirmation/anchor editing and exact platform-chrome masks are incomplete; person-label requests fail closed without verified identity.
- The request/cost ledger, Dragonfly limiter/circuit and full five-call/eight-cap quality pipeline are not complete. This slice avoids new paid model calls; it must not be used to claim complete governed live production.
- Automated quality benchmark acceptance and publication eligibility are not implemented; new revisions stay `pending_review`. Human-first defaults disable timeout publication, including legacy timeout attempts without proven eligibility.
- Engagement analytics/version comparisons and automatic editorial optimization are not delivered by this slice. No promise of views, comments or subscriptions is made.

See the canonical [quality roadmap](../specifications/25-roadmap.md#news-explainer-quality-rollout), [requirements](../specifications/README.md) and [production audit](production-audit.md) for remaining work.
