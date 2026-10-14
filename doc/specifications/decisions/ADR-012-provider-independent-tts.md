# ADR-012 — Provider-independent TTS (Google first)

- **Status:** Proposed

## Context

Google is the initial TTS provider, but voice quality, cost and language
coverage may lead to ElevenLabs or a local model later.

## Decision

- The pipeline depends only on `TTSProvider` (plain-text segments, language,
  opaque voice ID, speaking rate → WAV 48 kHz mono).
- `GoogleTTSProvider` is the initial adapter; provider-specific concerns
  (SSML dialect, request limits, chunking, voice catalogue) stay inside it.
- Word timing comes from `TranscriptionProvider` + alignment, not from
  provider-specific timepoint features, so captions work with any TTS.
- Narration is cached by (provider, voice, rate, language, text) hash.

## Consequences

- Switching TTS provider is inexpensive and does not affect captions.
- Transcription is always required, adding some processing time.

## Alternatives considered

- Using provider timepoints/marks for captions: couples captions to one vendor.
- Hard-coding Google voices in the profile schema: violates provider isolation.
