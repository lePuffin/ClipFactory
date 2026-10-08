# 18 — Configuration

Canonical home for **every configuration key and default value**. Other
documents reference keys by name and must not restate different defaults.

Architecture: [architecture/application-architecture.md](architecture/application-architecture.md#configuration).
Security of secrets: [19-security.md](19-security.md).

## Configuration layers

| Layer | Storage | Editable from UI | Contains |
| --- | --- | --- | --- |
| **Environment** | Process environment / `.env` file (never committed) | No | Deployment settings, provider selection, provider endpoints, credentials |
| **Application settings** | PostgreSQL table `app_settings` (one JSON document per section, validated by Pydantic) | Yes (Settings page) | Workflow, provider call policy, research feeds, captions, composition, evaluation, publishing mode and approval gate, budget limits and price table, analytics, retention |
| **Content Profile** | PostgreSQL (`content_profile`) | Yes (Content Profile page) | Editorial settings — see [14-content-profiles.md](14-content-profiles.md) |
| **Code defaults** | Pydantic model defaults | No | The defaults listed below |

A key belongs to exactly one layer; there is no cross-layer override chain.
The single exception is the `environment` application-settings section (CF-REQ-759): its defaults are the values loaded from the environment/`.env`, and stored values override them for later Runs.
Effective application settings = code defaults overlaid with the stored
section values. A Run snapshots the effective application settings and the
Content Profile at start (CF-REQ-653); later edits affect only later Runs.

## Environment variables

Loaded with `pydantic-settings` from the process environment and `.env`,
**without a prefix**. The one exception is `APP_ENV` (not `ENV`, which POSIX
shells use for their startup file). A committed `.env.example` (no real
values) documents all of them. Values containing spaces or parentheses must be
quoted so the file can also be sourced by a shell.

### Deployment

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_ENV` | `development` | `development`, `test`, `production` |
| `DATABASE_URL` | — (required) | `postgresql+psycopg://…` |
| `DRAGONFLY_URL` | `redis://127.0.0.1:6380/0` | Rolling LLM RPM and circuit state only (ADR-016) |
| `DATA_DIR` | `./data` | Root of local media storage |
| `HOST` | `127.0.0.1` | |
| `PORT` | `8000` | |
| `API_TOKEN` | — | Required when `HOST` is not a loopback address (CF-NFR-101) |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` in production, `console` otherwise | |
| `FFMPEG_PATH` | `ffmpeg` | Resolved on `PATH` at startup |
| `FFPROBE_PATH` | `ffprobe` | |
| `NODE_PATH` | `node` | Node runtime for the pinned local HyperFrames package |
| `HYPERFRAMES_PACKAGE_DIR` | `./renderers/hyperframes` | Isolated local Node package directory under `backend/`; exact HyperFrames release is pinned by its package lock |
| `HYPERFRAMES_PATH` | — (required when infographic rendering is selected) | Local trusted launcher for the pinned package |
| `MANIM_PATH` | — (required when scientific rendering is selected) | Manim executable from the optional `graphics-manim` Python group |
| `SCHEDULER_ENABLED` | `true` | `false` in tests |
| `LIVE_TESTS` | unset | `1` enables opt-in real-provider tests |

### Provider selection

Each capability selects one implementation by name, or a list of available
implementations where the pipeline tries several (news, media sources,
generation, publishers). `fake` implementations exist for every port and are
the only ones allowed when `APP_ENV=test`.

| Variable | Default | Allowed values in v1.0 |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai_compatible` | `openai_compatible`, `fake` |
| `NEWS_SOURCES` | `rss` | comma list of `rss`, `fake` |
| `MEDIA_SOURCES` | `pexels,pixabay,unsplash,wikimedia_commons` | comma list of `pexels`, `pixabay`, `unsplash`, `wikimedia_commons`, `local_library`, `fake` (OD-004, decided) |
| `IMAGE_PROVIDERS` | `comfyui,higgsfield` | comma list of available image generators: `comfyui`, `higgsfield`, `fake`; empty = none. Order of use comes from the Content Profile (CF-REQ-208) |
| `VIDEO_PROVIDERS` | `comfyui,wan_local,higgsfield` | comma list of available video generators: `comfyui`, `wan_local`, `higgsfield`, `fake`; empty = none |
| `TTS_PROVIDER` | `google` | `google`, `fake` |
| `TRANSCRIPTION_PROVIDER` | `whisper_local` | `whisper_local`, `fake` |
| `PUBLISHERS` | `youtube,instagram,tiktok,facebook` | Adapters to load; enabling per Run comes from the Content Profile |
| `STORAGE_PROVIDER` | `local` | `local` |

HyperFrames and Manim are local graphics adapters, not entries in
`IMAGE_PROVIDERS` / `VIDEO_PROVIDERS`; typed VisualPlan routing selects them
explicitly under CF-REQ-264. Their executable/install paths are listed above.

### Provider settings and credentials

| Variable | Default | Secret | Notes |
| --- | --- | --- | --- |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | No | Any OpenAI-compatible endpoint |
| `LLM_API_KEY` | — | Yes | |
| `LLM_MODEL` | `google/gemma-4-31b-it:free` | No | Default model for all LLM tasks: a **specific** free, vision-capable OpenRouter model, never the `openrouter/free` router (OD-001). Fallback candidate if retired: `qwen/qwen3.8-27b:free` |
| `LLM_MODEL_EVALUATION` | = `LLM_MODEL` | No | Model for `evaluate_clip`; must accept image input when `evaluation.visual_enabled` (later e.g. a Luna or Terra model, configuration only) |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `120` | No | |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Yes (path) | Google TTS service-account file (OD-006) |
| `WHISPER_MODEL` | `large-v3-turbo` | No | faster-whisper model; configurable for benchmarking (OD-007) |
| `WHISPER_DEVICE` | `auto` | No | `auto`, `cpu`, `cuda` |
| `WHISPER_COMPUTE_TYPE` | `default` | No | Use `int8` on CPU; `auto` is not valid for CPU CTranslate2 |
| `PEXELS_API_KEY` | — | Yes | |
| `PIXABAY_API_KEY` | — | Yes | |
| `UNSPLASH_ACCESS_KEY` | — | Yes | Photos only; adapter must follow Unsplash API guidelines (download tracking, attribution) |
| `WIKIMEDIA_USER_AGENT` | — (required when enabled) | No | Contact user agent required by Wikimedia API policy |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | No | Local ComfyUI server (owner-run) |
| `COMFYUI_WORKFLOWS_DIR` | `${DATA_DIR}/comfyui-workflows` | No | Owner-supplied workflow JSON templates (CF-REQ-217) |
| `WAN_MODEL` | `Wan-AI/Wan2.1-T2V-1.3B-Diffusers` | No | Native Wan via diffusers; optional dependency group `local-gen` |
| `WAN_DEVICE` | `cuda` | No | `cuda`, `cpu` (CPU is impractically slow) |
| `WAN_FPS` | `16` | No | Generated video frame rate, 1–60 |
| `WAN_INFERENCE_STEPS` | `50` | No | Diffusion steps, 1–100; local-gen uses sequential CPU offload on CUDA and VAE tiling |
| `WAN_MAX_GENERATIONS_PER_RUN` | `2` | No | Maximum native Wan starts per Run, 0–100; 0 disables new calls (CF-REQ-266) |
| `WAN_MODEL_LICENSE` | `Apache-2.0` | No | Default official checkpoint licence; owner must verify/update for a different checkpoint |
| `GRAPHICS_FPS` | `30` | No | Local HyperFrames/Manim output frame rate, 1–60; editable in the Run-snapshot `environment` settings |
| `GRAPHICS_TIMEOUT_SECONDS` | `180` | No | Bounded graphics subprocess time, 1–3600; editable in the Run-snapshot `environment` settings |
| `HIGGSFIELD_API_KEY` | — | Yes | Higgsfield cloud API credentials (exact auth scheme verified in Phase 5, OD-005) |
| `PUBLIC_MEDIA_BASE_URL` | — | No | Public HTTPS base URL of the owner's reverse proxy that forwards only `/public/media/` (CF-REQ-461) |
| `MEDIA_URL_SIGNING_KEY` | — (required when `PUBLIC_MEDIA_BASE_URL` is set) | Yes | ≥ 32 random bytes, HMAC key for signed media URLs (CF-NFR-114) |
| `YOUTUBE_CLIENT_SECRETS_FILE` | — | Yes (path) | OAuth client; token stored under `${DATA_DIR}/secrets/` (OD-009) |
| `INSTAGRAM_ACCESS_TOKEN` | — | Yes | |
| `INSTAGRAM_USER_ID` | — | No | |
| `TIKTOK_CLIENT_KEY` | — | Yes | |
| `TIKTOK_CLIENT_SECRET` | — | Yes | |
| `FACEBOOK_ACCESS_TOKEN` | — | Yes | Page access token |
| `FACEBOOK_PAGE_ID` | — | Yes | |

Wan model files are cached under `${DATA_DIR}/models/wan`, never checked into
Git. First generation automatically downloads missing files from `WAN_MODEL`
(Hugging Face model ID); a local directory uses existing weights. Install the
optional dependencies with `cd backend && uv sync --group local-gen`.
Downloads can be large and first use may exceed the configured stage timeout;
partial downloads remain resumable in the cache. The default 1.3B model
requires substantial RAM/VRAM even with offloading; live feasibility on the
reference host is not established.
Local typed graphics rendering uses HyperFrames for infographic templates
and Manim for scientific templates (CF-REQ-264). HyperFrames is installed
locally at `HYPERFRAMES_PACKAGE_DIR` as an exact-version-pinned Node package;
Manim is isolated in the optional `graphics-manim` Python dependency group.
`NODE_PATH`, `HYPERFRAMES_PATH`, and `MANIM_PATH` are environment-only
executable/install paths. `GRAPHICS_FPS` and `GRAPHICS_TIMEOUT_SECONDS` are
Run-snapshot settings below. Graphics work files remain inside the normal
DATA_DIR work/recovery areas; user-supplied paths are not accepted in a
VisualDraft. Relative HyperFrames package/launcher paths resolve against the
process working directory; use absolute paths when launching from the
repository root. Executable names such as `node` or `manim` resolve on
`PATH`.

Credentials are never stored in PostgreSQL, never returned by the API, never
logged (CF-NFR-106).

## Application settings (defaults)

Section and key names are canonical. All numeric values are validated
(ranges in brackets).

### `environment`

Per-Run overrides of non-secret environment variables (CF-REQ-759, CF-REQ-760). Defaults are the values loaded from the environment/`.env`, not code defaults.

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `llm_model` | `LLM_MODEL` | non-empty | `LLMProvider` |
| `llm_model_evaluation` | `LLM_MODEL_EVALUATION` | empty = `llm_model` | `evaluate_clip` |
| `llm_request_timeout_seconds` | `LLM_REQUEST_TIMEOUT_SECONDS` | 1–600 | `LLMProvider` |
| `whisper_model` | `WHISPER_MODEL` | non-empty | `TranscriptionProvider` |
| `whisper_device` | `WHISPER_DEVICE` | `auto`, `cpu`, `cuda` | `TranscriptionProvider` |
| `whisper_compute_type` | `WHISPER_COMPUTE_TYPE` | non-empty | `TranscriptionProvider` |
| `wan_fps` | `WAN_FPS` | 1–60 | `VideoProvider` |
| `wan_inference_steps` | `WAN_INFERENCE_STEPS` | 1–100 | `VideoProvider` |
| `wan_max_generations_per_run` | `WAN_MAX_GENERATIONS_PER_RUN` (`2`) | 0–100 | CF-REQ-266; durable usage across Retry/Continue, 0 disables new Wan calls |
| `graphics_fps` | `GRAPHICS_FPS` | 1–60 | HyperFrames/Manim graphics render |
| `graphics_timeout_seconds` | `GRAPHICS_TIMEOUT_SECONDS` | 1–3600 | Per-render subprocess bound; silent stage-watchdog heartbeats renew the stage deadline only while work is active |

### `workflow`

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `max_revision_retries` | `3` | 0–10 | CF-REQ-411 |
| `resume_interrupted_runs` | `true` | | CF-REQ-657 |
| `stage_timeout_seconds` | `1800` | 60–7200 | CF-REQ-656 (Provisional); renewed by native generation/render watchdog activity |

### `providers`

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `max_call_retries` | `3` | 0–10 | CF-NFR-010 |
| `call_retry_base_delay_seconds` | `2` | 0.1–60 | Exponential backoff with jitter |
| `call_retry_max_delay_seconds` | `60` | 1–600 | Also caps honoured `Retry-After` |
| `default_timeout_seconds` | `60` | 1–600 | Non-LLM HTTP calls |
| `llm_max_schema_repairs` | `1` | 0–5 | CF-REQ-758 — each repair is a real request and counts against the LLM request limits |

### `llm`

LLM request governance (CF-REQ-666 – CF-REQ-671). Defaults assume the
OpenRouter free tier (baseline assumption 20 requests/minute and 50
requests/day; verify against the account, OD-021).

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `requests_per_minute` | `20` | 1–10 000 | CF-REQ-667 |
| `requests_per_day` | `50` | 1–1 000 000 | CF-REQ-668 |
| `daily_reset_timezone` | `UTC` | IANA | CF-REQ-668 |
| `target_requests_per_clip` | `5` | 1–20 | CF-REQ-666 (quality-mode target, reported) |
| `max_requests_per_run` | `8` | 1–50 | CF-REQ-666 (hard cap incl. repairs and revisions) |
| `min_daily_requests_to_start_run` | `5` | 0–50 | CF-REQ-668, automatic research |
| `min_daily_requests_to_start_manual_run` | `4` | 0–50 | CF-REQ-668, Manual URL |
| `max_input_chars` | `60000` | 1 000–1 000 000 | CF-REQ-112 (source text budget per request) |
| `circuit_failure_threshold` | `3` | 1–20 | CF-REQ-671 |
| `circuit_open_seconds` | `300` | 10–86 400 | CF-REQ-671 |

### `research`

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `feeds` | curated list (see below) | | `RssNewsSource` |
| `near_duplicate_threshold` | `0.8` | 0.5–1.0 | CF-REQ-104 (Provisional) |
| `max_additional_sources` | `5` | 0–20 | CF-REQ-110 |
| `story_novelty_window_days` | `7` | 0–90 | CF-REQ-109 [Derived] |
| `selection_weights` | `{profile_relevance: 0.30, newsworthiness: 0.25, independent_sources: 0.20, source_quality: 0.15, recency: 0.10}` | sum = 1.0 | CF-REQ-107 (Provisional) |
| `publisher_quality` | mapping `publisher domain → tier` (`high` / `standard` / `low` / `blocked`); starter entries for the starter feeds are `high` | | CF-REQ-103 |
| `max_article_bytes` | `5_000_000` | | CF-NFR-104 |

`feeds` default: the starter list below (OD-003, decided), editable in
Settings. Every URL must be verified to return a valid feed during Phase 3;
feeds that fail are removed from the seed and reported. Reuters and AP no
longer publish official public RSS feeds, so their reporting enters mainly
through syndication and `gather_sources`. An empty list makes automated
research fail with `no_candidates`.

| Publisher | Feed URL (to verify) |
| --- | --- |
| BBC News — World | `https://feeds.bbci.co.uk/news/world/rss.xml` |
| The Guardian — World | `https://www.theguardian.com/world/rss` |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` |
| NPR — World | `https://feeds.npr.org/1004/rss.xml` |
| Deutsche Welle — World | `https://rss.dw.com/rdf/rss-en-world` |
| France 24 | `https://www.france24.com/en/rss` |
| The New York Times — World | `https://rss.nytimes.com/services/xml/rss/nyt/World.xml` |
| CNN — World | `http://rss.cnn.com/rss/edition_world.rss` |

### `script`

| Key | Default | Used by |
| --- | --- | --- |
| `max_segments` | `8` | CF-REQ-156 |
| `min_segments` | `4` | CF-REQ-156 |
| `hook_max_seconds` | `5` | CF-REQ-157 |

### `quality`

News-explainer rollout settings. Creative numeric defaults below are Provisional pending reference-set review; they are not claims of optimal engagement.

| Key | Default | Range / Meaning | Used by |
| --- | --- | --- | --- |
| `style` | `modern_news_explainer` | Versioned local style template | CF-REQ-163 |
| `enabled` | `true` | Enforce the news-explainer quality extension | CF-REQ-416 |
| `allow_paid_models` | `true` | Only within verified pre-call Clip/month budgets | CF-REQ-661–663 |
| `reference_story_count` | `10` | 5–50, Provisional diverse frozen Stories | CF-REQ-418 |
| `safe_subtitle_bottom_margin_pct` | `22` | 10–30, Provisional conservative mobile band; validate against reviewed platform masks | CF-REQ-261, CF-REQ-362 |
| `cta_enabled` | `true` | Optional invitations; sensitive-story policy still applies | CF-REQ-165 |
| `max_ctas_per_clip` | `1` | 0–1 | CF-REQ-165 |
| `cta_max_seconds` | `4` | 0–5; included in the Clip duration | CF-REQ-165 |
| `sensitive_story_cta_enabled` | `false` | Disable promotional invitations for sensitive reporting | CF-REQ-165 |

### `overlays`

Numeric creative defaults are Provisional for reference-set review. Platform safe-zone rectangles are versioned template data, never assumed to be permanent platform guarantees.

| Key | Default | Range / Meaning | Used by |
| --- | --- | --- | --- |
| `enabled` | `true` | Editorial labels separate from captions | CF-REQ-259 |
| `min_dwell_seconds` | `2` | 1–10 readable seconds | CF-REQ-261 |
| `reading_words_per_second` | `3` | 1–5; language-specific override permitted | CF-REQ-261 |
| `font_size_px` | `32` | 24–72 at 720 px output width; scaled with output | CF-REQ-261 |
| `safe_zone_template_version` | `news-mobile-v1` | Owner-reviewed rectangles for YouTube, Instagram, TikTok and Facebook | CF-REQ-261 |

### `sound_effects`

| Key | Default | Range / Meaning | Used by |
| --- | --- | --- | --- |
| `enabled` | `true` | Only licensed, available cues | CF-REQ-323 |
| `sensitive_story_effects_enabled` | `false` | Suppress playful/aggressive cues | CF-REQ-324 |
| `max_cue_seconds` | `2` | 0.1–10, Provisional | CF-REQ-324 |
| `narration_ducked_level_db` | `-24` | -60–0 relative level, Provisional | CF-REQ-325 |
| `fade_seconds` | `0.15` | 0–1, Provisional | CF-REQ-325 |

### `visual`

| Key | Default | Used by |
| --- | --- | --- |
| `min_segment_seconds` | `1.5` | CF-REQ-257 |
| `max_segment_seconds` | `8.0` | CF-REQ-250, CF-REQ-257 |

### `visual_review`

Preview limits are Provisional; modality/request capacity and remaining budget are checked before calls. Overflow leaves uncovered scenes pending owner review rather than sending unbounded requests.

| Key | Default | Range / Meaning | Used by |
| --- | --- | --- | --- |
| `enabled` | `true` | One initial batched candidate-review request | CF-REQ-219 |
| `candidates_per_scene` | `3` | 1–5 preliminary candidates | CF-REQ-218 |
| `max_preview_images` | `24` | 1–64, also limited by model capacity | CF-REQ-218 |
| `preview_width_px` | `512` | 256–1024 | CF-REQ-218 |
| `max_preview_bytes` | `1000000` | 10000–5000000 per permitted preview | CF-REQ-218 |

### `assets`

| Key | Default | Used by |
| --- | --- | --- |
| `reuse_min_match_score` | `0.6` | CF-REQ-205 (Provisional) |
| `reuse_cooldown_days` | `3` | CF-REQ-206 [Derived] |
| `min_image_short_side_px` | `720` | CF-REQ-210 |
| `min_video_height_px` | `720` | CF-REQ-210 |
| `max_image_bytes` | `20_000_000` | CF-NFR-104 |
| `max_video_bytes` | `300_000_000` | CF-NFR-104 |
| `max_audio_bytes` | `50_000_000` | CF-NFR-104 |
| `candidates_per_search` | `10` | CF-REQ-207 |

### `captions`

Values are fractions of the output frame so they hold for any 9:16
resolution (OD-011, decided). At 720×1280: side margins 43 px, text width
≤ 634 px, bottom margin 128 px.

| Key | Default | Used by |
| --- | --- | --- |
| `font_file` | bundled `NotoSans-Bold.ttf` (bold sans-serif, broad language coverage) | CF-REQ-312 |
| `font_size_px` | `56` (at 720 px width, scaled with width) | CF-REQ-312 |
| `max_lines` | `2` | CF-REQ-312 |
| `max_cue_seconds` | `3.0` | CF-REQ-312 |
| `alignment` | `center` | CF-REQ-312 |
| `horizontal_margin_pct` | `6` | CF-REQ-313 |
| `max_text_width_pct` | `88` | CF-REQ-313 |
| `bottom_margin_pct` | `10` | CF-REQ-313 |
| `text_color` | `#FFFFFF` | CF-REQ-314 |
| `background_box` | `{color: "#000000", opacity: 0.55, padding_px: 12, corner_radius_px: 8}` | CF-REQ-314 |
| `shadow` | `{color: "#000000", opacity: 0.8, offset_px: 2, blur_px: 4}` | CF-REQ-314 |

### `composition`

| Key | Default | Used by |
| --- | --- | --- |
| `video_codec` | `libx264` | CF-REQ-351 |
| `crf` | `23` | CF-REQ-351 |
| `preset` | `medium` | CF-REQ-351 |
| `pixel_format` | `yuv420p` | CF-REQ-351 |
| `audio_codec` | `aac` | CF-REQ-351 |
| `audio_bitrate` | `128k` | CF-REQ-351 |
| `audio_sample_rate` | `48000` | CF-REQ-351 |
| `lead_in_seconds` | `0.3` | CF-REQ-354 |
| `tail_seconds` | `1.0` | CF-REQ-354 |
| `narration_loudness_lufs` | `-14` | CF-REQ-356 |
| `transition_seconds` | `0.4` | CF-REQ-355 |

### `evaluation`

| Key | Default | Used by |
| --- | --- | --- |
| `semantic_enabled` | `true` | CF-REQ-405 |
| `visual_enabled` | `true` | CF-REQ-415 |
| `visual_frame_count` | `5` | 1–10, CF-REQ-415 |
| `visual_frame_width_px` | `360` | CF-REQ-415 (frames downscaled to limit tokens) |
| `max_narration_wer` | `0.15` | CF-REQ-404 (Provisional) |
| `max_segment_duration_drift_seconds` | `2.0` | CF-REQ-404 |
| `quality_max_review_images` | `32` | 1–64, Provisional and bounded by model/budget; uncovered shots remain pending | CF-REQ-416 |

### `publishing`

| Key | Default | Used by |
| --- | --- | --- |
| `mode` | `dry_run` | CF-REQ-452 [Derived] |
| `approval_required` | `true` | CF-REQ-459, owner review during quality rollout |
| `auto_publish_enabled` | `false` | CF-REQ-460, explicit opt-in only after benchmark approval |
| `auto_publish_after_minutes` | `10` (range 1–10080) | CF-REQ-460 |
| `public_media_url_ttl_minutes` | `60` (range 5–1440) | CF-REQ-461, CF-NFR-114 |

### `budget`

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `currency` | `EUR` | ISO 4217 | CF-REQ-661 |
| `max_cost_per_clip` | `1.00` | ≥ 0 (0 = only free providers) | CF-REQ-662 |
| `max_cost_per_month` | `30.00` | ≥ 0 | CF-REQ-663 |
| `usd_to_currency_rate` | `0.92` | > 0 | CF-REQ-661 — converts USD-priced providers (Provisional, OD-020) |
| `price_table` | per provider operation, see [below](#provider-price-table) | | CF-REQ-661 |

#### Provider price table

Used to *estimate* cost before a call when the provider does not return the
actual cost. Values are Provisional (OD-020) and editable in Settings.

| Provider operation | Unit | Default price |
| --- | --- | --- |
| `llm` | per call | Actual cost reported by the endpoint when available (OpenRouter usage accounting); otherwise `llm_usd_per_1k_tokens` = `0.002` USD |
| `google_tts` | per 1 M characters | `30.00` USD (Chirp 3 HD; verify, OD-020) |
| `higgsfield_image` | per image | `0.05` USD |
| `higgsfield_video` | per second of video | `0.10` USD |
| `comfyui_*`, `wan_local`, `whisper_local` | — | `0` (local) |
| `pexels`, `pixabay`, `unsplash`, `wikimedia_commons` | — | `0` |

### `analytics`

| Key | Default | Used by |
| --- | --- | --- |
| `snapshot_offsets` | `["1h","6h","24h","48h","7d","30d"]` | CF-REQ-501 |
| `rpm_by_platform` | `{youtube: 0.05, instagram: 0.01, tiktok: 0.40, facebook: 0.02}` (USD per 1 000 views) | CF-REQ-504 (OD-010, decided) |
| `currency` | `USD` | CF-REQ-504 |

### `scheduler`

| Key | Default | Used by |
| --- | --- | --- |
| `poll_interval_seconds` | `30` | CF-REQ-651 |
| `missed_run_grace_minutes` | `60` | CF-REQ-651 |

### `retention`

| Key | Default | Used by |
| --- | --- | --- |
| `work_dir_retention_days` | `7` | CF-REQ-214 |
| `rejected_clip_retention_days` | `14` | CF-REQ-214 |

## Content Profile defaults

The seeded default profile (created by the initial migration if none exists):

| Field | Default |
| --- | --- |
| name | `Global News (English)` |
| language | `en` |
| category | `general` |
| topics | `[]` |
| excluded_topics | `[]` |
| geography | `["global"]` |
| markets | `["global"]` |
| voice | `{provider_voice_id: "en-US-Chirp3-HD-Leda", speaking_rate: 1.0, words_per_minute: 150}` (Google Cloud TTS, Chirp 3 HD; changeable in Settings after listening tests, OD-006) |
| duration | `{min_seconds: 60, target_seconds: 70, max_seconds: 90}` (OD-002, decided) |
| output | `{width: 720, height: 1280, fps: 30}` |
| visual_style | `{description: "clean, factual news style", caption_style: "bold_white_on_dark_box", motion_intensity: "medium", allow_generated_media: true}` |
| generation | `{image_providers: ["comfyui", "higgsfield"], video_providers: ["comfyui", "wan_local", "higgsfield"]}` — order of preference; entries not enabled in the environment are skipped (CF-REQ-208) |
| platforms | `[]` (owner enables explicitly) |
| schedule | `{enabled: true, local_time: "05:00", timezone: "Europe/Lisbon"}` (OD-008, decided) |
| research | `{max_candidate_articles: 20, min_sources: 1, preferred_independent_sources: 3, max_article_age_hours: 24, allowed_publishers: null, blocked_publishers: []}` |
| music | `{enabled: true, mood_tags: ["news", "neutral"], energy: "low", ducked_level_db: -20, unducked_level_db: -12}` (levels relative to normalised narration; CF-REQ-321) |

## Requirements

### CF-REQ-750 — Validated configuration at startup

- **Description:** The system shall load and validate environment variables
  and application settings at startup and refuse to start on invalid values.
- **Behaviour:** Missing required variables, unknown provider names, invalid
ranges, a missing FFmpeg/FFprobe binary, a missing configured
HyperFrames/Manim executable, or unreachable PostgreSQL or Dragonfly
produce a single startup error listing every problem, without printing
secret values. An optional renderer that is not configured may remain
unused, but selecting a visual that requires it fails explicitly.
- **Acceptance:**
  - Starting with `LLM_PROVIDER=unknown` exits non-zero and names the variable.
  - Starting with `APP_ENV=test` and a non-`fake` provider exits non-zero.
  - Starting with an unreachable `DRAGONFLY_URL` exits non-zero and makes no provider call.
  - Error output never contains the value of any secret variable.
- **Related:** CF-NFR-106, [application-architecture](architecture/application-architecture.md#configuration)

### CF-REQ-751 — Provider selection by configuration

- **Description:** The composition root shall instantiate provider
  implementations exclusively from the provider selection variables, except
  the explicitly routed local graphics adapters in CF-REQ-264.
- **Behaviour:** No module outside the composition root and
  `infrastructure/providers` references a concrete provider class. The
  composition root makes local HyperFrames/Manim adapters available only
  when configured; `select_assets` chooses them by the typed VisualPlan kind,
  never by `VIDEO_PROVIDERS` or Content Profile provider order.
- **Acceptance:**
  - Switching `TTS_PROVIDER` between `google` and `fake` requires no code change.
  - An architecture test fails if application/domain modules import a concrete provider.
  - Changing `VIDEO_PROVIDERS` order does not change infographic/Manim
    routing, while media generation still follows the existing configured
    order.
- **Related:** CF-REQ-264, CF-NFR-020, ADR-005, ADR-019

### CF-REQ-752 — Editable application settings

- **Description:** The API shall expose read and update operations for the
  application settings sections listed in this document.
- **Behaviour:** Updates are validated with the same models as startup; an
  invalid update is rejected with field-level errors and nothing is stored.
  Successful updates emit a structured log entry listing changed keys.
- **Acceptance:**
  - `PUT` with `workflow.max_revision_retries = 11` returns 422 and the stored value is unchanged.
  - A valid update is visible in a subsequent `GET` and used by the next Run.
- **Related:** CF-REQ-606, CF-REQ-653

### CF-REQ-753 — Credential status without disclosure

- **Description:** The API shall report, per provider, whether required
  credentials are configured, without returning credential values.
- **Acceptance:**
  - The settings response contains `{"provider": "google_tts", "credentials_configured": true}` style entries and no secret values.
- **Related:** CF-NFR-106, CF-REQ-606

### CF-REQ-754 — Seeded defaults

- **Description:** Database initialisation shall create the default Content
  Profile and default application settings documented above if absent.
- **Acceptance:**
  - A fresh database after `alembic upgrade head` plus first start contains exactly one active Content Profile with the defaults in this document.

### CF-REQ-755 — Local dependency setup [Derived]

- **Description:** `clipfactory setup` shall provision the local PostgreSQL
  and Dragonfly services defined by the repository's Docker Compose file,
  wait for both health checks, apply Alembic migrations and seed defaults.
- **Behaviour:** The command shall be idempotent and shall not start or
  containerise the backend. Compose image versions shall be pinned.
- **Progress:** Each step (prerequisites, container start, role initialisation, health wait, migrations, defaults) is printed as `[n/N] <step>` when it starts and with `done`/`FAILED` and its elapsed time when it ends; on an interactive terminal a live elapsed-time indicator is shown. A failed container start also prints the redacted tail of the Docker Compose output.
- **Failure:** Missing Docker/Compose, an unhealthy service or a failed
  migration exits non-zero and identifies the failed step without exposing secrets.
- **Acceptance:**
  - On a fresh supported host, `clipfactory setup` leaves PostgreSQL and
    Dragonfly healthy, the schema at head and defaults seeded.
  - Running it twice succeeds without duplicate defaults or a second backend process.
- **Related:** CF-REQ-754, ADR-016

### CF-REQ-756 — Operational diagnostics [Derived]

- **Description:** `clipfactory doctor` shall perform read-only checks for
  configuration validity, Docker and Compose availability, PostgreSQL and
  Dragonfly reachability/health, migration status, FFmpeg/FFprobe features and
  data-directory access, plus any configured local graphics renderer
  executable/package path.
- **Behaviour:** It shall make no provider request, migration or data change;
  print one redacted result per check; and exit 0 only when every required
  check passes, otherwise exit 1. A renderer path explicitly configured for
  use is required and must resolve; an unconfigured optional renderer is
  reported as unavailable and is not claimed ready.
  `PUBLIC_MEDIA_DIR` is optional: an unavailable directory or mount produces
  a redacted `WARN`, not a failed required check. The current signed media
  endpoint serves Clip files from `DATA_DIR`, not this optional directory.
- **Acceptance:**
  - With Dragonfly stopped, output names `Dragonfly` as failed, exits 1 and
    does not contact the configured LLM endpoint.
  - With all dependencies healthy, every required check passes and it exits 0.
  - An unavailable `PUBLIC_MEDIA_DIR` produces a warning and does not change
    the exit code when required checks pass.
  - Configured HyperFrames/Manim paths are checked locally without rendering
    or contacting a provider; an unconfigured optional renderer is reported
    as unavailable, not as validated.
- **Related:** CF-REQ-750, CF-REQ-856, ADR-016

### CF-REQ-757 — Native application run command [Derived]

- **Description:** `clipfactory run` shall validate required dependencies,
  run pending migrations and start ClipFactory as one native backend process
  with one Uvicorn worker.
- **Behaviour:** It shall use the configured Compose-managed PostgreSQL and
  Dragonfly services but shall not run the backend in a container. If either
  dependency is unavailable it exits non-zero with guidance to run
  `clipfactory setup` or `clipfactory doctor`.
  From the repository root, `uv run clipfactory` is the canonical launch:
  omitting a CLI subcommand is equivalent to `run`. The root runtime manifest
  installs both local Wan and Manim automatically, without project/group
  flags. Backend-only installs retain explicitly selectable extras/groups.
  `PUBLIC_MEDIA_DIR` is not a startup or setup dependency. Neither command
  accesses or creates that optional directory; an unavailable network share
  cannot block local Clip production. `DATA_DIR` remains required.
- **Acceptance:**
  - A successful invocation serves the API/UI and scheduler from one native process.
  - With PostgreSQL or Dragonfly stopped, no backend server is started.
  - Empty CLI arguments and explicit `run` perform the same startup sequence.
  - Root `uv run clipfactory --help` resolves the installed command; the
    root locked runtime contains both native generation dependency sets.
  - With `PUBLIC_MEDIA_DIR` missing, unwritable or on an unavailable mount,
    startup and setup proceed without accessing it; required dependency
    failures still prevent startup.
- **Related:** CF-NFR-001, CF-REQ-750, ADR-016

### CF-REQ-758 — Structured LLM output validation

- **Description:** Every LLM call shall request structured output described
  by a Pydantic schema and validate the response against it.
- **Behaviour:** On validation failure the provider wrapper re-asks with the
  validation errors, up to `providers.llm_max_schema_repairs` times; schema
  repairs are separate from call retries.
- **Failure:** After the limit, the stage fails with error code
  `llm_invalid_output` and the validation errors in the Run Event payload.
- **Acceptance:**
  - A fake LLM returning invalid JSON once then valid JSON succeeds with `llm_max_schema_repairs=1` and records 2 requests.
  - Returning invalid JSON twice with `llm_max_schema_repairs=1` fails the stage with `llm_invalid_output`.
- **Related:** CF-NFR-010, [provider-architecture](architecture/provider-architecture.md#llmprovider)

### CF-REQ-759 — Environment values editable per Run

- **Description:** The Settings page shall show the `environment` section with defaults taken from the loaded environment/`.env`, allow the owner to change and save them, and apply the saved values to every Run created afterwards.
- **Behaviour:** Only values that differ from the environment are stored, so later `.env` edits still apply to keys the owner has not overridden. Run Now, Manual URL and scheduled Runs snapshot the effective section; before executing a Run the backend applies that snapshot to the providers, falling back to the environment for missing keys. Credentials and provider endpoints (`LLM_API_KEY`, `LLM_BASE_URL`, …), deployment variables and provider selection remain environment-only and require a restart.
- **Acceptance:**
  - With `LLM_MODEL=a` in `.env`, `GET /api/settings` shows `environment.llm_model = a`; after saving `b`, the next Run's snapshot contains `b` and the LLM provider uses `b`.
  - Wan FPS and inference steps are editable under Settings / Environment.
    New and explicitly continued Runs apply the effective snapshot to Wan,
    including an already-loaded pipeline; changing steps/FPS does not reload
    weights. Editing `.env` requires a server restart; saved UI values override it.
  - Saving an unknown key such as `llm_api_key` returns 422 and nothing is stored.
- **Related:** CF-REQ-752, CF-REQ-653, CF-NFR-106

### CF-REQ-760 — Local graphics renderer runtime settings

- **Description:** The application shall expose validated, non-secret graphics
  FPS and renderer-timeout settings with defaults and ranges defined in this
  document.
- **Behaviour:** `graphics_fps` and `graphics_timeout_seconds` are loaded from
  `GRAPHICS_FPS` and `GRAPHICS_TIMEOUT_SECONDS`, can be edited under Settings
  / Environment, and are included in each Run's settings snapshot. Changes
  affect new/continued render work without changing renderer package versions.
  Editing `.env` requires a process restart; saving Settings updates affects
  subsequent or explicitly continued Run work.
  `NODE_PATH`, `HYPERFRAMES_PACKAGE_DIR`, `HYPERFRAMES_PATH` and `MANIM_PATH`
  remain environment-only and require a process restart after changes.
- **Acceptance:**
  - Defaults are 30 FPS and a 180-second renderer subprocess bound.
  - Values outside the configured ranges are rejected before rendering.
  - A Run uses its snapshot values; a later setting edit affects only a
    subsequent or explicitly continued Run.
  - Renderer executable/package paths are not exposed as editable Settings
    values or accepted from a VisualDraft.
- **Related:** CF-REQ-653, CF-REQ-751, CF-REQ-264–265, ADR-019
