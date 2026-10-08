# Provider and Platform Credentials

Keep credentials in the ignored root `.env` file or in private files referenced
by environment variables. Never put a credential in a source file, settings
API request, issue, log, or Git commit. The repository's `secrets/` directory
is ignored; the application runtime stores OAuth tokens under
`${DATA_DIR}/secrets/` with owner-only permissions.

## Local startup

The target command contract below is approved architecture, not a claim that
the current implementation already provides the commands.

1. Install Python 3.13+, `uv`, Docker with the Compose plugin, and FFmpeg with
  H.264, AAC and libass support.
2. Copy `.env.example` to `.env`; set `DATA_DIR` to a writable directory on
  the WSL2 ext4 filesystem and configure `DATABASE_URL` and `DRAGONFLY_URL`.
3. Run `cd backend && uv run clipfactory setup`, then
  `uv run clipfactory doctor`; start the native backend with
  `uv run clipfactory run`.
4. For offline development, select fake providers in `.env`. Live providers
   are selected independently through the documented environment variables
   in [18-configuration.md](../specifications/18-configuration.md).
5. Use provider-specific account consoles to create credentials. Restrict
   their scopes to the required read, upload or publishing operations.
6. Start with publishing mode `dry_run`; verify local output and account
   permissions before enabling `live`.

## Provider notes

- **OpenAI-compatible LLM:** configure `LLM_BASE_URL`, `LLM_API_KEY`, and the
  concrete model name in `LLM_MODEL`. Use a vision-capable evaluation model
  when visual evaluation is enabled.
- **Google Cloud TTS:** enable the Text-to-Speech API, create a service account
  with only the required TTS permissions, save its JSON outside the repository,
  and set `GOOGLE_APPLICATION_CREDENTIALS` to that path.
- **Media search:** create API credentials with Pexels, Pixabay and Unsplash as
  needed. Wikimedia Commons requires a descriptive `WIKIMEDIA_USER_AGENT`.
  Observe attribution, licence and provider download-tracking requirements.
- **YouTube:** configure an OAuth client and set
  `YOUTUBE_CLIENT_SECRETS_FILE`. OAuth tokens belong under `${DATA_DIR}/secrets/`.
- **Instagram and Facebook:** configure eligible professional/Page accounts
  and their Graph API access. Their publishing APIs fetch media from a public
  URL; configure `PUBLIC_MEDIA_BASE_URL` and a random signing key of at least
  32 bytes, then expose only `/public/media/*` through an HTTPS reverse proxy.
- **TikTok:** configure the Content Posting API client and complete the
  platform's app review/user authorization requirements. Automated posting is
  subject to the platform's access restrictions.
- **ComfyUI and Higgsfield:** ComfyUI is an owner-operated local service with
  workflow templates under `COMFYUI_WORKFLOWS_DIR`; Higgsfield requires its
  provider credential and cost settings. Generation is gated by budget policy.

Live credentials and platform app approval are not required for standard
tests. Use `scripts/check_credentials.py` only after reviewing its read-only
requests; that legacy utility may contact live services.
