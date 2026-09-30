# 02 — Functional Requirements Map

Functional requirements (`CF-REQ-###`) are defined in the topic documents
below, next to the behaviour they describe. This page is a map, not a
second copy: the complete per-ID list with titles, components and
verification is [traceability.md](traceability.md).

| Area | Document | IDs | Pipeline stages |
| --- | --- | --- | --- |
| Research, clustering, selection, sources, claims | [05-research-and-source-grounding.md](05-research-and-source-grounding.md) | CF-REQ-100 – CF-REQ-118 | `research`, `cluster_stories`, `select_story`, `gather_sources`, `extract_claims` |
| Story Package, script, social metadata | [06-story-and-script.md](06-story-and-script.md) | CF-REQ-150 – CF-REQ-162 | `build_story_package`, `write_script` |
| Asset library, reuse, acquisition, generation, provenance | [07-asset-management.md](07-asset-management.md) | CF-REQ-200 – CF-REQ-217 | `select_assets` |
| Visual plan, motion, framing, timing | [08-visual-production.md](08-visual-production.md) | CF-REQ-250 – CF-REQ-257 | `plan_visuals`, `build_captions`, `compose_clip` |
| Narration, transcription, captions, music | [09-audio-and-tts.md](09-audio-and-tts.md) | CF-REQ-300 – CF-REQ-321 | `generate_narration`, `transcribe_narration`, `build_captions` |
| Composition and output format | [10-composition.md](10-composition.md) | CF-REQ-350 – CF-REQ-359 | `compose_clip` |
| Evaluation and targeted retry | [11-evaluation-and-retry.md](11-evaluation-and-retry.md) | CF-REQ-400 – CF-REQ-414 | `validate_clip`, `evaluate_clip`, `plan_retry` |
| Publishing | [12-publishing.md](12-publishing.md) | CF-REQ-450 – CF-REQ-461 | `publish` |
| Analytics | [13-analytics.md](13-analytics.md) | CF-REQ-500 – CF-REQ-506 | scheduled metric tasks |
| Content Profiles | [14-content-profiles.md](14-content-profiles.md) | CF-REQ-550 – CF-REQ-555 | all |
| UI and dashboard | [15-ui-and-dashboard.md](15-ui-and-dashboard.md) | CF-REQ-600 – CF-REQ-613 | — |
| Runs, workflow execution, scheduling, cost governance | [16-scheduling-and-runs.md](16-scheduling-and-runs.md) | CF-REQ-650 – CF-REQ-665 | all |
| Manual URL | [17-manual-input.md](17-manual-input.md) | CF-REQ-700 – CF-REQ-703 | `ingest_url` |
| Configuration | [18-configuration.md](18-configuration.md) | CF-REQ-750 – CF-REQ-758 | all |
| Observability | [20-observability.md](20-observability.md) | CF-REQ-850 – CF-REQ-856 | all |

## Pipeline coverage

Every stage of the canonical pipeline ([00-project-overview.md](00-project-overview.md#canonical-pipeline))
has requirements:

| Pipeline element | Key requirements |
| --- | --- |
| Scheduler / Run Now | CF-REQ-650, CF-REQ-651, CF-REQ-652, CF-REQ-608 |
| Research | CF-REQ-100 – CF-REQ-103 |
| Deduplicate / cluster | CF-REQ-102, CF-REQ-104, CF-REQ-105 |
| Story selection | CF-REQ-106 – CF-REQ-109, CF-REQ-111 |
| Source gathering | CF-REQ-110 |
| Claim extraction | CF-REQ-112 – CF-REQ-117 |
| Story Package | CF-REQ-150 – CF-REQ-152 |
| Script writer | CF-REQ-153 – CF-REQ-160 |
| Visual planner | CF-REQ-250 – CF-REQ-253 |
| Asset selection (reuse / acquire / generate) | CF-REQ-204 – CF-REQ-211 |
| TTS / audio | CF-REQ-300 – CF-REQ-305, CF-REQ-320, CF-REQ-321 |
| Transcription | CF-REQ-310, CF-REQ-311 |
| Captions | CF-REQ-312 – CF-REQ-314 |
| Composition | CF-REQ-350 – CF-REQ-359, CF-REQ-254 – CF-REQ-256 |
| Deterministic validation | CF-REQ-401 – CF-REQ-404 |
| Semantic evaluation | CF-REQ-405 – CF-REQ-408 |
| Retry | CF-REQ-410 – CF-REQ-414 |
| Publish | CF-REQ-450 – CF-REQ-457 |
| Metrics | CF-REQ-458, CF-REQ-500 – CF-REQ-506 |

Non-functional requirements: [03-non-functional-requirements.md](03-non-functional-requirements.md),
[19-security.md](19-security.md), [21-testing.md](21-testing.md).
