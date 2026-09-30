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
| `DATA_DIR` | `./data` | Root of local media storage |
| `HOST` | `127.0.0.1` | |
| `PORT` | `8000` | |
| `API_TOKEN` | — | Required when `HOST` is not a loopback address (CF-NFR-101) |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `json` in production, `console` otherwise | |
| `FFMPEG_PATH` | `ffmpeg` | Resolved on `PATH` at startup |
| `FFPROBE_PATH` | `ffprobe` | |
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

Credentials are never stored in PostgreSQL, never returned by the API, never
logged (CF-NFR-106).

## Application settings (defaults)

Section and key names are canonical. All numeric values are validated
(ranges in brackets).

### `workflow`

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `max_revision_retries` | `3` | 0–10 | CF-REQ-411 |
| `resume_interrupted_runs` | `true` | | CF-REQ-657 |
| `stage_timeout_seconds` | `1800` | 60–7200 | CF-REQ-656 (Provisional) |

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
| `target_requests_per_clip` | `4` | 1–20 | CF-REQ-666 (design target, reported) |
| `max_requests_per_run` | `8` | 1–50 | CF-REQ-666 (hard cap incl. repairs and revisions) |
| `min_daily_requests_to_start_run` | `4` | 0–50 | CF-REQ-668 |
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

### `visual`

| Key | Default | Used by |
| --- | --- | --- |
| `min_segment_seconds` | `1.5` | CF-REQ-257 |
| `max_segment_seconds` | `8.0` | CF-REQ-250, CF-REQ-257 |

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

### `publishing`

| Key | Default | Used by |
| --- | --- | --- |
| `mode` | `dry_run` | CF-REQ-452 [Derived] |
| `approval_required` | `false` | CF-REQ-459 |
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
  ranges, a missing FFmpeg/FFprobe binary, or an unreachable database produce
  a single startup error listing every problem, without printing secret values.
- **Acceptance:**
  - Starting with `LLM_PROVIDER=unknown` exits non-zero and names the variable.
  - Starting with `APP_ENV=test` and a non-`fake` provider exits non-zero.
  - Error output never contains the value of any secret variable.
- **Related:** CF-NFR-106, [application-architecture](architecture/application-architecture.md#configuration)

### CF-REQ-751 — Provider selection by configuration

- **Description:** The composition root shall instantiate provider
  implementations exclusively from the provider selection variables.
- **Behaviour:** No module outside the composition root and
  `infrastructure/providers` references a concrete provider class.
- **Acceptance:**
  - Switching `TTS_PROVIDER` between `google` and `fake` requires no code change.
  - An architecture test fails if application/domain modules import a concrete provider.
- **Related:** CF-NFR-020, ADR-005

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
