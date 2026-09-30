# ADR-005 — Ports and adapters for all external capabilities

- **Status:** Proposed

## Context

Initial vendors (OpenRouter, Google TTS, specific media APIs, platform APIs)
are expected to change. The domain must not depend on them, and tests must
not require them.

## Decision

- Define ports in `clipfactory/ports/`: `LLMProvider`, `NewsSource`,
  `MediaSourceProvider`, `ImageProvider`, `VideoProvider`, `TTSProvider`,
  `TranscriptionProvider`, `Publisher`, `StorageProvider`.
- Implement adapters in `infrastructure/providers/`, selected by configuration
  in the composition root (CF-REQ-751).
- Every port has a fake and a shared contract test suite.
- Shared resilience wrapper for timeouts, call retries and error classification.
- `PublicationRequest` is platform-neutral; platform specifics live in the adapters.

## Consequences

- Switching vendor = new adapter + configuration.
- Slight indirection cost; acceptable because each port has a real consumer.
- Architecture tests enforce isolation (CF-NFR-020).

## Alternatives considered

- Calling SDKs directly from use cases: faster to write, couples domain to vendors, untestable without network.
- Generic plugin framework: unnecessary; a composition root with explicit selection is enough.
