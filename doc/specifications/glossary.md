# Glossary

Canonical terminology. All specifications, code identifiers, UI labels,
agent files, prompts and diagrams must use these terms. Entity fields are
defined in [04-domain-model.md](04-domain-model.md); this file defines meaning.

## Terminology rules

- The produced video is a **Clip**. Do not use "short", "shorts", "reel", "reels" or "TikTok video" as product terminology. <!-- terminology:allow -->
- YouTube, Instagram, TikTok and Facebook are **platforms**. Platform-specific names (e.g. a platform's own product name for vertical video) may appear only inside the corresponding `Publisher` adapter and its documentation.
- "Article" is a retrieved document; "Source" is an Article used as evidence
  for a Story. Counting Articles is not counting independent Sources.
- "Retry" always means a bounded new attempt. Specify which kind: **call
  retry** or **revision retry**.

## Core terms (mandatory)

| Term | Definition |
| --- | --- |
| **ClipFactory** | The application specified in this repository. |
| **Clip** | The final produced vertical video (default 720×1280, 30 FPS, 60–90 s) plus its technical metadata. One Run produces at most one approved Clip; each revision attempt produces a new Clip candidate. |
| **Story** | The news event or topic covered by a Clip. Several Articles from different publishers usually describe one Story. A Story is first a *candidate*, then possibly *selected*. |
| **Source** | A retrieved document (usually a news article) attached to a Story as evidence, with publisher, URL, retrieval time, text and syndication information. |
| **Claim** | A single factual assertion extracted from Source text, linked to one or more verbatim evidence excerpts in Sources. |
| **Story Package** | The versioned, structured bundle required to produce a Clip: Story, Sources, Claims, key facts, Script, Visual Plan, asset requirements and social metadata. Downstream stages read the Story Package instead of rediscovering the Story. |
| **Asset** | A stored media file with metadata and provenance: image, video/B-roll, generated image or video, graphic, chart, map, audio, music, or narration. Reusable Assets are shared across Runs. |
| **Run** | One execution of the production workflow, triggered by the schedule, Run Now, or a Manual URL. |
| **Content Profile** | Editorial and production configuration: language, category, topics, exclusions, geography, markets, voice, duration policy, visual style, platforms, schedule. |
| **Publication** | The act and record of publishing one approved Clip to one platform. |
| **Metric Snapshot** | Platform metrics for one Publication observed at one point in time. |
| **Provider** | An adapter implementing a port (interface) for an external or replaceable capability, e.g. `LLMProvider`, `TTSProvider`, `Publisher`. |
| **Evaluation** | Automated quality analysis of a Clip candidate (deterministic validation + semantic evaluation) producing `passed`, issues, warnings, actions and metrics. |
| **Retry** | A bounded new attempt to correct an unsuccessful stage or result. See *call retry* and *revision retry*. |

## Supporting terms

| Term | Definition |
| --- | --- |
| **Article** | A document returned by a `NewsSource` or fetched from a URL, before or after being attached to a Story. Persisted as a `Source` record. |
| **Story candidate** | A cluster of Articles believed to describe the same Story, before selection. |
| **Independent Source** | A Source whose *origin publisher* differs from every other counted Source and which is not a syndicated or near-duplicate copy of another counted Source. |
| **Syndicated copy** | An Article that republishes another publisher's reporting (wire copy, rewrite, near-duplicate text). It counts as an Article but not as an additional Independent Source. |
| **Origin publisher** | The publisher that originally reported the content of a Source (e.g. Reuters for a Reuters wire story republished by a blog). |
| **Evidence** | A verbatim excerpt of Source text supporting a Claim. |
| **Support level** | Classification of a Claim: `corroborated` (≥ 2 Independent Sources), `single_source` (1), `unsupported` (0 valid evidence excerpts). |
| **Key fact** | A short, accepted Claim selected as essential for the script. |
| **Script** | The versioned narration text, split into Script Segments, each citing the Claims it uses. |
| **Hook** | The first Script Segment, intended to capture attention in the first seconds. |
| **Visual Plan** | Ordered Visual Segments describing what is shown during each part of the narration. |
| **Visual Segment** | One entry of the Visual Plan: narration context, visual objective, asset requirement, strategy, duration, motion, transition, selected Asset. |
| **Asset requirement** | A description of the media needed for a Visual Segment (type, subjects, tags, description, strategy). |
| **Provenance** | Where an Asset came from: origin, provider, source URL, author, licence, attribution, and generation metadata when generated. |
| **Narration** | The TTS audio for a Script, stored as a non-reusable Asset. |
| **Word timing** | A word with start and end timestamps obtained from transcription and aligned to Script text. |
| **Caption Track** | Timed caption cues and their computed layout, derived deterministically from word timings. |
| **Safe area** | The region of the frame where captions and important visuals may appear without being hidden by platform UI or cropped. |
| **Stage** | A named step of the pipeline (canonical list in [16-scheduling-and-runs.md](16-scheduling-and-runs.md#stages)). |
| **Stage gate** | A deterministic check at the end of a stage that must pass before the workflow continues (e.g. script gate). |
| **Deterministic validation** | Code-only checks of a Clip candidate (duration, resolution, FPS, streams, integrity, captions, assets, metadata). No LLM. |
| **Semantic evaluation** | LLM-assisted checks of factual grounding, script quality, hook, visual relevance, pacing, narration, captions and editorial quality. |
| **Issue** | An Evaluation finding with code, severity (`blocking` or `warning`), affected stage, message and evidence. |
| **Action** | A concrete correction proposed for an Issue (e.g. `revise_script`, `reselect_asset`). |
| **Attempt** | One pass through the production stages for a Run. Attempt 1 is the initial pass; each revision retry creates the next Attempt. |
| **Call retry** | Re-issuing a failed provider call after a *transient* error, bounded per call. Does not change inputs. |
| **Revision retry** | Re-entering the stage affected by blocking Evaluation issues with corrective instructions, reusing unaffected artefacts. Bounded per Run. |
| **Platform** | A publishing destination: YouTube, Instagram, TikTok, Facebook. |
| **Publisher** | The provider port for publishing to one platform. |
| **PublicationRequest** | Platform-neutral value object passed to a `Publisher`: Clip file, title, description, hashtags, attributions, disclosure flags. |
| **Publishing mode** | `disabled`, `dry_run` (build and log requests, never call platforms), or `live`. |
| **Estimated revenue** | Revenue computed by ClipFactory from metrics and configured rates, or reported by a platform as an estimate. Never presented as guaranteed income. |
| **Run Event** | A persisted, ordered, structured record of something meaningful that happened in a Run. |
| **Run Now** | UI/API action that starts a Run immediately. |
| **Manual URL** | A news URL supplied by the user that seeds a Run instead of automated research. |
| **Open Decision (OD)** | A deliberately undecided item listed in [26-open-decisions-and-conflicts.md](26-open-decisions-and-conflicts.md). |
| **Derived requirement** | A requirement not literally stated in the project brief but necessary to make it implementable or safe; marked `[Derived]` for owner review. |
