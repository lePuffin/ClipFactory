# Isolated native Wan reference test

Contract: [CF-REQ-267](../specifications/08-visual-production.md#cf-req-267--native-wan-reference-recipe-and-isolated-manual-test).
Configuration: [18-configuration](../specifications/18-configuration.md).

## What was compared

The owner's local OpenMontage project `paper-boat-wan21-test` records Wan 2.1
1.3B, seed 42, 832x480, 16 FPS and 50 steps. FFprobe confirms its saved
`paper-boat.mp4` is H.264 yuv420p, 80 frames, exactly five seconds.
Its x264 bitstream metadata records CRF 10, which is now the default native
Wan encoding quality rather than FFmpeg's implicit CRF 23.
The saved midpoint shows a realistic boat, wet surface and night lighting.

The local engine uses explicit guidance 5, the official Wan Chinese
motion/quality negative prompt, a CPU noise generator, aligned inference
frames and trimming to the requested output length. It selects BF16 and
offload mode by GPU capacity. It does not override the checkpoint scheduler;
ClipFactory's cached checkpoint already declares UniPC with flow shift 3.
The owner supplied the original Copilot transcript, recovering its actual
tool-input prompt (used in the command below). The transcript ends before
the later successful retry, so it does not independently establish that
retry's precision, offload mode or dependency versions.

On 2026-10-08 the owner executed the recovered prompt through ClipFactory at
25 steps and accepted the resulting playback as equal in visual quality to
the OpenMontage reference. The reported pipeline load took about one minute
and denoising took 12 minutes 17 seconds. This is an owner-verified landscape
sample, not a guarantee of quality or runtime for other shots.

ClipFactory previously used oversized portrait inference, a brief English
negative prompt, search descriptions prefixed by disclosure/policy text and
an extra output frame. The new implementation separates generation prompts
from search keywords, bounds native inference to the 480p recipe, makes
guidance/shift explicit and trims encoding to the requested duration.
Portrait requests stay portrait (720x1280 becomes 464x832 before inference);
the existing final fitting composes them into the unchanged Clip output.
FP32 VAE and sequential CPU offload are retained for stability on the
reference laptop; no quantization dependency is added.

OpenMontage is only a read-only comparison source. No OpenMontage module is
copied/imported or made a ClipFactory dependency.

## Preview the recipe without generating

From the ClipFactory repository root:

```bash
uv run clipfactory wan-test \
  --prompt "A small folded paper boat floats slowly through a rain-filled city gutter at night, streetlight reflections ripple in the water, low ground-level tracking camera, cinematic realism, no text, no logos" \
  --width 832 --height 480 --fps 16 --seconds 5 --steps 25 --seed 42 \
  --guidance 5 --flow-shift 3 \
  --output database/wan-tests/paper-boat-reference-25-next.mp4 \
  --dry-run
```

This prints the recipe and creates no media, manifest or output directory.
It does not load weights, query CUDA, contact a provider or connect to a
database. It does not read saved Settings from PostgreSQL: `.env` plus these
explicit CLI overrides define this isolated comparison. Nothing changes
the saved settings, per-Run cap or counts.

## Manually generate when ready

Run the same command **without `--dry-run`**. It exclusively invokes the
production local Wan adapter, using the shared `${DATA_DIR}/models/wan`
cache. It never starts the app, scheduler or a Run, calls an LLM/cloud
generator, imports an Asset, or publishes anything.

Offline mode is the default. If cached weights are missing, the command fails
explicitly. Add `--allow-download` only if you want to download missing
checkpoint files from the configured Hugging Face source; inference remains
local and free. Both the MP4 and adjacent `.mp4.json` path must be unused.

On success the command probes and fully decodes the output, verifies geometry,
FPS, duration and frame count, and writes:

- `database/wan-tests/paper-boat-reference-25-next.mp4`
- `database/wan-tests/paper-boat-reference-25-next.mp4.json`: effective recipe, model, prompt,
  seed, inference/output frame counts and probe measurements.

The inference uses 81 frames, encoded output uses 80. No frame interpolation,
model chaining, upscaling or synthetic sharpening is used in this comparison.
Use a different output filename for each attempt; existing files are never
overwritten. Stop any application inference first to avoid two processes
competing for RAM/VRAM. Loading may still be slow on a Windows-mounted cache.

## Production Run integration

Normal Runs use the same native Wan adapter as this manual test,
not a separate inference implementation. Default Content Profile output is
720x1280; Wan infers vertically at 464x832, 16 FPS and 25 steps, with guidance
5, flow shift 3 and CRF 10. Only final composition fits to the configured Clip
output dimensions. No Full HD native inference is needed.

The existing single writing request supplies a separate cinematic generation
prompt for eligible shots, including reuse-first media that may need a
fallback. It describes recognizable subject geometry, restrained motion,
lighting and camera, and frames for the Content Profile orientation. The
normalized Visual Plan preserves this prompt unchanged for generation; search
descriptions stay separate. Legacy plans keep their naturalistic fallback.

Run snapshots and owner overrides in Settings remain authoritative; defaults
do not silently overwrite an existing saved value. The two-Wan-start cap,
typed graphics/refined-search alternatives, person restrictions and final
quality review remain in force. The landscape reference does not approve
unrelated generated Assets automatically.

## Validation boundary

Unit tests use mocked inference and fake test generation, with
mock-inference/real-FFmpeg encoding cases including 832x480 and the production
464x832 import path, 16 FPS and exactly 80 output frames over five seconds.
They do not load Wan weights or verify image quality. No new real generation
or operational Run was performed while integrating the production flow.
The owner's landscape playback acceptance is recorded above; live portrait
quality and bitwise equality are not claimed. Review new generated shots
for subject realism, coherent motion and artifacts.
