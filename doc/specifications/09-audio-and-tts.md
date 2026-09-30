# 09 — Audio, TTS, Transcription, Captions and Music

Covers stages `generate_narration`, `transcribe_narration`, `build_captions`,
and music selection. Decisions: [ADR-012](decisions/ADR-012-provider-independent-tts.md).
Ports: `TTSProvider`, `TranscriptionProvider` in
[architecture/provider-architecture.md](architecture/provider-architecture.md).

```text
Script ──► TTSProvider ──► narration audio (Asset, non-reusable)
                                  │
                                  ▼
                       TranscriptionProvider ──► recognised words + timestamps
                                  │
                                  ▼
             align to Script words (deterministic) ──► WordTimings (+ WER)
                                  │
                                  ▼
          caption layout (deterministic, font metrics) ──► CaptionTrack
```

## Narration

### CF-REQ-300 — Narration synthesis

- **Description:** `generate_narration` shall synthesise the full Script text
  through the configured `TTSProvider` using the profile language and
  `VoiceSpec` (opaque `provider_voice_id`, `speaking_rate`).
- **Behaviour:** The port accepts plain text segments; any provider limits
  (request size, SSML dialect, chunking and concatenation) are handled inside
  the adapter. Output is normalised to WAV PCM 48 kHz mono.
- **Initial provider (OD-006, decided):** Google Cloud Text-to-Speech, Chirp 3
  HD voices, initial voice `en-US-Chirp3-HD-Leda`, speaking rate `1.0`. The
  adapter sends plain text only (Chirp 3 HD does not use SSML); if the voice
  family does not support a non-default speaking rate, the adapter rejects
  values ≠ 1.0 at settings validation instead of ignoring them (verify in
  Phase 5). The voice is changed in Settings after listening tests.
- **Acceptance:**
  - The workflow code contains no reference to Google, ElevenLabs or any specific TTS API.
  - The fake TTS provider produces a WAV whose duration equals `words × 60 / wpm` (deterministic).
- **Related:** CF-REQ-305, ADR-012

### CF-REQ-301 — Narration as Asset

- **Description:** Narration audio shall be stored as an Asset with
  `category = narration`, `reusable = false`, and provenance
  `origin = generated` recording TTS provider, voice and text hash.
- **Acceptance:**
  - The Clip's `NarrationTrack.asset_id` references this Asset.

### CF-REQ-302 — Narration cache

- **Description:** Narration shall be cached by the hash of
  (provider, voice id, speaking rate, language, exact text). A retry whose
  Script text is unchanged shall reuse the cached narration.
- **Acceptance:**
  - A revision retry that only reselects an Asset makes zero TTS calls.
- **Related:** CF-REQ-412

### CF-REQ-303 — Narration validation

- **Description:** Narration shall be probed with FFprobe: decodable, one
  audio stream, duration > 0, not silent (mean volume above −50 dBFS).
- **Failure:** Invalid audio ⇒ issue `narration_invalid` ⇒ `regenerate_narration`
  (with the provider's cache entry invalidated).
- **Acceptance:**
  - A silent fixture WAV fails with `narration_invalid`.

### CF-REQ-304 — Narration duration gate

- **Description:** After synthesis, the measured narration duration plus
  `lead_in_seconds + tail_seconds` shall lie within the profile
  `[min_seconds, max_seconds]`.
- **Failure:** Issue `narration_too_short` / `narration_too_long` with the
  delta in seconds and a `revise_script` Action stating how many words to add
  or remove (`delta × wpm / 60`, rounded up).
- **Acceptance:**
  - 57.0 s narration + 1.3 s padding (58.3 s) fails; the Action requests ≥ 5 more words at 150 wpm.
  - 72.0 s narration passes.
- **Related:** CF-REQ-155, CF-REQ-401

### CF-REQ-305 — TTS provider independence

- **Description:** Replacing the TTS provider shall require only a new adapter
  and configuration change. Voice identifiers are opaque strings validated by
  the adapter (`list_voices()`), never enumerated in domain code.
- **Acceptance:**
  - Contract tests run identically against `FakeTTSProvider` and (opt-in) `GoogleTTSProvider`.
- **Related:** CF-NFR-020

## Transcription and alignment

### CF-REQ-310 — Narration transcription

- **Description:** `transcribe_narration` shall transcribe the narration audio
  with the configured `TranscriptionProvider`, passing the profile language,
  and obtain word-level timestamps.
- **Initial provider (OD-007, decided):** local faster-whisper with model
  `large-v3-turbo`; the model name is configuration
  (`WHISPER_MODEL`) so alternatives can be benchmarked.
- **Acceptance:**
  - The fake transcription provider returns the script words with evenly spaced timestamps.
  - Word timestamps are monotonically non-decreasing and within the audio duration.

### CF-REQ-311 — Alignment to script

- **Description:** Recognised words shall be aligned to the Script words with
  a deterministic sequence alignment; caption text uses **Script** spelling,
  timestamps come from recognised words; unmatched Script words receive
  timestamps interpolated between neighbours. The word error rate (WER) of
  the transcript against the Script is recorded.
- **Acceptance:**
  - A transcript with one misrecognised word produces captions with the correct Script word at the recognised word's timing.
  - WER is stored in the Evaluation metrics.
- **Related:** CF-REQ-404

## Captions

### CF-REQ-312 — Caption cue layout

- **Description:** `build_captions` shall group aligned words into cues
  deterministically: at most `captions.max_lines` (2) lines, centre-aligned,
  cue duration ≤ `captions.max_cue_seconds`, breaks preferred at punctuation,
  line width measured with the configured bold sans-serif font file and size
  (not character counts) against `captions.max_text_width_pct` (88 % of frame
  width).
- **Acceptance:**
  - Identical word timings and settings produce identical `CaptionTrack` JSON.
  - No cue exceeds 2 lines or 3.0 s with defaults.

### CF-REQ-313 — Caption safe area

- **Description:** Every cue's computed bounding box (text plus background
  box padding) shall lie within the caption area: at least
  `captions.horizontal_margin_pct` (6 %) from each side, text no wider than
  `captions.max_text_width_pct` (88 %), and the box bottom at
  `captions.bottom_margin_pct` (10 %) above the frame bottom. If a line cannot
  fit, the layout first re-breaks lines, then reduces font size down to 80 % of
  `font_size_px`.
- **Failure:** If still out of bounds, issue `caption_out_of_bounds` (blocking)
  with the cue index.
- **Acceptance:**
  - At 720×1280 with defaults, every cue box has x ≥ 43 px, x + width ≤ 677 px, text width ≤ 634 px and bottom edge at 1152 px.
  - A single 40-character unbreakable token at 56 px triggers font reduction or `caption_out_of_bounds`; never an out-of-bounds render.
- **Related:** CF-REQ-402, OD-011

### CF-REQ-314 — Caption rendering

- **Description:** Captions shall be burned into the video from the
  `CaptionTrack` via an ASS subtitle file rendered by FFmpeg/libass using the
  same font file used for measurement, white bold text on a semi-transparent
  dark background box with a drop shadow (`captions.text_color`,
  `captions.background_box`, `captions.shadow`) so text stays readable over
  arbitrary B-roll. Caption text is escaped for ASS (`\`, `{`, `}` and newlines).
- **Acceptance:**
  - A caption containing `{\\b1}` renders literally, not as ASS markup.
  - On a pure-white and a pure-black fixture frame, the contrast ratio between caption text and its box background is ≥ 4.5:1 (WCAG AA) in the rendered frame.
- **Related:** CF-NFR-107

## Music

### CF-REQ-320 — Royalty-free music selection

- **Description:** When `MusicPolicy.enabled`, the system shall select one
  `music` Asset from the local library deterministically from metadata — no
  LLM request and no AI music generation.
- **Behaviour:** Eligible tracks: `active`, licence permits the use, and
  `allowed_platforms` is null or contains every platform enabled in the
  profile. Score: mood-tag overlap with `MusicPolicy.mood_tags`, energy match
  with `MusicPolicy.energy`, duration ≥ Clip duration (or `loopable`); ties
  broken by least recent use, then title.
- **Failure:** No eligible music ⇒ warning event; the Clip is composed without
  music (not a failure).
- **Acceptance:**
  - With an empty music library the Run still produces a Clip and records warning `no_music_available`.
  - A track with `allowed_platforms = [youtube]` is never chosen when TikTok is enabled.
  - Selection makes no LLM request and is identical for identical inputs.
- **Related:** CF-REQ-216, CF-REQ-322, OD-013

### CF-REQ-321 — Music mixing and ducking

- **Description:** Music shall be mixed under narration with deterministic
  ducking: at `MusicPolicy.ducked_level_db` (default −20 dB) relative to the
  normalised narration while narration is speaking, and at
  `MusicPolicy.unducked_level_db` (default −12 dB) in lead-in, tail and pauses
  longer than 0.8 s; transitions ramp over 0.3 s (attack) / 0.5 s (release).
  The envelope is computed from word timings (no sidechain analysis), music is
  looped with a 1 s crossfade if shorter than the Clip, faded in over 1 s and
  out over 2 s.
- **Acceptance:**
  - Measured music loudness during narration is within ±2 dB of −20 dB relative to narration (integration test with fixtures).
  - Identical word timings produce an identical volume envelope.
- **Related:** CF-REQ-356

### CF-REQ-322 — Local music library and manifest

- **Description:** Music tracks shall be stored permanently in the local
  library (`${DATA_DIR}/music/`, never deleted by retention) and described by
  a manifest (`${DATA_DIR}/music/manifest.json`) with, per track: `file`,
  `title`, `artist`, `source` (initially `youtube_audio_library` or `mixkit`),
  `source_url`, `license`, `attribution_required`, `attribution_text`
  (when required), `genre`, `mood` (list), `energy` (`low`/`medium`/`high`),
  `bpm`, `duration_seconds`, `loopable`, `allowed_platforms` (null = all).
- **Behaviour:** `clipfactory import-music <manifest>` (and the UI import)
  validates every entry (all required fields, file exists, FFprobe-measured
  duration within ±1 s of the manifest), creates or updates `music` Assets
  with `origin = imported`, and reports invalid entries without importing
  them. Tracks are downloaded manually by the owner from the source sites;
  ClipFactory does not scrape them. Licence terms must be checked per track
  (e.g. some YouTube Audio Library tracks may be restricted to YouTube or
  require attribution) and reflected in `allowed_platforms` and attribution.
  Audio files are not committed to the Git repository.
- **Acceptance:**
  - A manifest entry missing `license` is rejected with a field error; valid entries are still imported.
  - Re-importing the same manifest creates no duplicate Assets.
  - A track with `attribution_required = true` adds its attribution text to the Clip description (CF-REQ-161).
- **Related:** CF-REQ-216, OD-013
