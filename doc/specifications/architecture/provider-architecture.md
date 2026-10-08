# Provider Architecture

Decisions: [ADR-005](../decisions/ADR-005-provider-adapters.md),
[ADR-012](../decisions/ADR-012-provider-independent-tts.md),
[ADR-013](../decisions/ADR-013-provider-independent-media-generation.md).
Diagram: [publishing-flow](diagrams/publishing-flow.puml).

## Principles

- A **port** is a `typing.Protocol` in `clipfactory/ports/`, expressed in
  domain terms. An **adapter** implements it in
  `clipfactory/infrastructure/providers/<port>/<name>.py`.
- Every port has a deterministic `fake` adapter and a shared contract test
  suite (`backend/tests/contract/test_<port>.py`) run against every adapter.
- Adapters convert all vendor exceptions to `ProviderError` (CF-NFR-111) and
  classify them as transient or permanent.
- Call retries/backoff/timeouts are applied by one shared wrapper
  (`infrastructure/providers/resilience.py`), not re-implemented per adapter
  (CF-NFR-010).
- Adapters expose `name: str` (recorded in provenance/events) and
  `is_configured() -> bool` (credentials present; no network call).
- No port is created without a v1.0 consumer. The list below is complete.

## Ports

Signatures are indicative; exact typing is decided during implementation
without changing semantics. All methods are `async`.

### LLMProvider

```python
class LLMProvider(Protocol):          # the "LLM client" interface used by use cases
    name: str
    async def generate_structured(
        self, task: str, messages: list[LLMMessage], schema: type[T], *,
        model_role: Literal["default", "evaluation"] = "default",
        images: list[ImageInput] | None = None,
        temperature: float = 0.2,
    ) -> LLMResult[T]: ...        # parsed object + model id + token usage + reported cost
```

- Initial adapter: `OpenAICompatibleLLMProvider` (base URL, API key, model via
  configuration) — works with OpenRouter, OpenAI and local OpenAI-compatible
  servers. Uses JSON-schema response format when supported, otherwise JSON
  mode plus schema validation. Images are sent as OpenAI-style `image_url`
  content parts (base64 data URLs).
- Initial model: a specific free vision-capable OpenRouter model
  (`google/gemma-4-31b-it:free`, OD-001); never the `openrouter/free` router,
  so runs are reproducible. Future providers or models (OpenAI, Luna, Terra,
  local) are new adapters or configuration only; no use case references a
  vendor or model.
- A shared governance wrapper (applies to every adapter) implements schema
  repair (CF-REQ-758), RPM limiter, daily budget, per-Run cap, selective
  retries with backoff, usage records and circuit breaker (CF-REQ-666 –
  CF-REQ-671). PostgreSQL is authoritative for usage; Dragonfly stores only
  the rolling RPM window and circuit state
  ([ADR-016](../decisions/ADR-016-compose-postgresql-and-dragonfly.md)).

### NewsSource

```python
class NewsSource(Protocol):
    name: str
    supports_search: bool
    async def latest(self, query: NewsQuery) -> list[ArticleRef]: ...
    async def search(self, text: str, since: datetime, limit: int) -> list[ArticleRef]: ...
```

- `ArticleRef`: url, title, publisher, published_at, summary.
- Article fetching/extraction is not part of this port; it is done by the
  research module with the safe HTTP client and an extraction library, so it
  is identical for all sources and for Manual URLs.
- Initial adapter: `RssNewsSource` (feeds from `research.feeds`, `supports_search = False`). See OD-003.

### MediaSourceProvider

```python
class MediaSourceProvider(Protocol):
    name: str
    async def search(self, request: MediaSearchRequest) -> list[MediaCandidate]: ...
    async def download(self, candidate: MediaCandidate, dest: StorageKey, max_bytes: int) -> DownloadedMedia: ...
```

- `MediaCandidate` carries provenance: url, download_url, source, author,
  licence, licence_url, attribution, media_type, width, height, duration.
- Initial adapters (OD-004, decided): `PexelsMediaSource`, `PixabayMediaSource`,
  `UnsplashMediaSource` (photos only; follows Unsplash API guidelines:
  trigger the download-tracking endpoint and keep photographer attribution),
  `WikimediaCommonsMediaSource` (preferred for real, identifiable people,
  CF-REQ-215); plus `LocalLibraryMediaSource` if needed for imported
  collections.

### ImageProvider / VideoProvider

```python
class ImageProvider(Protocol):
    name: str
    async def generate(self, request: ImageGenerationRequest) -> GeneratedMedia: ...

class VideoProvider(Protocol):
    name: str
    async def generate(self, request: VideoGenerationRequest) -> GeneratedMedia: ...
```

- Requests: prompt, negative prompt, width, height, (duration for video), seed.
- For local graphics, the existing request may carry an optional
  provider-neutral typed `graphics_spec`; the `select_assets` use case selects
  the named HyperFrames or Manim adapter explicitly from the VisualPlan kind.
  This is not provider-list fallback and does not add a port. HyperFrames
  accepts only trusted infographic templates; Manim accepts only trusted
  scientific templates. Neither accepts model-authored HTML/SVG/source code,
  arbitrary formulas or URLs. See CF-REQ-263–265 and [ADR-019](../decisions/ADR-019-local-typed-graphics-renderers.md).
- `GeneratedMedia` includes the file, `GenerationInfo`, and the reported cost if any.
- Adapters also expose `estimate_cost(request) -> Money` used by the budget
  check (CF-REQ-662); local adapters return 0.
- v1.0 adapters (OD-005, decided):

| Adapter | Port(s) | Runs | Notes |
| --- | --- | --- | --- |
| `ComfyUIImageProvider`, `ComfyUIVideoProvider` | Image, Video | Local ComfyUI HTTP API | Owner-supplied workflow templates (CF-REQ-217); Wan, Flux, SDXL etc. run as workflows |
| `WanLocalVideoProvider` | Video | In-process via diffusers + PyTorch (worker thread, CUDA) | Optional `local-gen` dependency group; small GPU makes it slow/unreliable on the reference host |
| `HyperFramesVideoProvider` | Video | Local pinned Node package, explicit infographic route | Uses only bounded typed templates; separate from profile provider order |
| `ManimVideoProvider` | Video | Local Manim renderer, explicit scientific route | Optional `graphics-manim` Python dependency group; bounded typed templates |
| `HiggsfieldImageProvider`, `HiggsfieldVideoProvider` | Image, Video | Higgsfield cloud API (paid) | API contract, auth and pricing verified in Phase 5 |
| `fake` | Image, Video | FFmpeg-rendered gradients | Tests |

- Provider order comes from the Content Profile `generation` policy; the
  asset manager, not the adapters, implements fallback (CF-REQ-208).
- Wan can supply video for a missing image shot as well. Its lazy loader
  automatically caches missing official model files beneath DATA_DIR.
  Generated files pass normal import validation with generation metadata;
  final visual review and approval still apply.
- HyperFrames/Manim outputs are rendered video Assets and use the existing
  validation, FFprobe/full-decode, provenance and import lifecycle. A graphics
  failure never falls through to Wan or another provider. The renderer's
  internal encoding is allowed; FFmpeg authoring of a graphic is not.

### TTSProvider

```python
class TTSProvider(Protocol):
    name: str
    async def synthesize(self, request: SpeechRequest) -> SynthesizedSpeech: ...
    async def list_voices(self, language: str) -> list[VoiceInfo]: ...
```

- `SpeechRequest`: segments (plain text), language, voice id (opaque),
  speaking rate. Adapter handles chunking, request limits and concatenation,
  returns WAV 48 kHz mono and character count.
- Initial adapter: `GoogleTTSProvider` (OD-006). Future: `ElevenLabsTTSProvider`, `LocalTTSProvider`.

### TranscriptionProvider

```python
class TranscriptionProvider(Protocol):
    name: str
    async def transcribe(self, audio: StorageKey, language: str) -> Transcript: ...
```

- `Transcript`: words with start/end seconds and confidence.
- Initial adapter: `WhisperLocalTranscriptionProvider` (faster-whisper, run in a worker thread; OD-007).

### Publisher

```python
class Publisher(Protocol):
    platform: Platform
    name: str
    def is_configured(self) -> bool: ...
    async def publish(self, request: PublicationRequest, clip_file: Path) -> PublicationResult: ...
    async def fetch_metrics(self, platform_post_id: str) -> PlatformMetrics: ...
```

- Initial adapters: `YouTubePublisher`, `InstagramPublisher`, `TikTokPublisher`, `FacebookPublisher` (OD-009).
- Platform limits (title length, hashtags, disclosure fields) are handled
  inside each adapter (CF-REQ-451, CF-REQ-453).
- `PlatformMetrics` fields map to `MetricSnapshot`; unavailable values are `None`.

### StorageProvider

```python
class StorageProvider(Protocol):
    async def put_file(self, source: Path, key: StorageKey) -> StoredObject: ...
    async def open(self, key: StorageKey) -> AsyncIterator[bytes]: ...
    def local_path(self, key: StorageKey) -> Path: ...   # for FFmpeg; local provider only
    async def exists(self, key: StorageKey) -> bool: ...
    async def delete(self, key: StorageKey) -> None: ...
    def work_dir(self, run_id: UUID) -> Path: ...
```

- Initial adapter: `LocalStorageProvider` ([storage-architecture](storage-architecture.md)).
- A future object-storage adapter would stage files locally for FFmpeg via
  `local_path` semantics; this is why FFmpeg code asks the provider for a path
  rather than building paths itself.

## Non-provider ports

`Clock`, repositories (`RunRepository`, `StoryRepository`, `AssetRepository`, …),
`UnitOfWork` and `RunEventPublisher` are ports too, implemented in
infrastructure; they are not external "providers".

## Adding a provider

1. Implement the adapter in `infrastructure/providers/<port>/`.
2. Make it pass the port's contract test suite.
3. Add its selection value and settings to [18-configuration.md](../18-configuration.md).
4. Add opt-in live tests under `backend/tests/live/`.
5. Document licence/terms constraints in the adapter module docstring.
No change in domain or application code may be needed; if it is, the port is
wrong — raise it with the architect agent.
