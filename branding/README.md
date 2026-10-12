# inPulso ending asset

`outro.mp4` is a reusable three-second, 720x1280, 30 FPS H.264/AAC end
card with the owner-provided globe logo, "Follow for more" and an original
offline-synthesized news sting underneath TTS saying **"Keep up with the
world. Follow InPulso."** `outro.png` is its still preview.
`outro-voice.wav` contains the exact line generated once using the configured
Google TTS voice `en-US-Chirp3-HD-Leda`, explicitly authorized by the owner.
The ending is reused; there are no per-Run TTS requests for it.

Regenerate from the repository root without providers, GPU generation or
network calls:

```bash
uv run --no-sync python -m clipfactory.infrastructure.media.brand_outro \
  --font /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf \
  --voice-file branding/outro-voice.wav
```

Enable via composition settings: `logo_file: logo_letters.png`,
`end_card_file: branding/outro.mp4`, `tail_seconds: 3`. The end card replaces
the reserved tail rather than increasing the Clip's duration. Each Run freezes
and hashes the asset; saved revisions reuse that frozen copy. Set
`end_card_file: null` to retain the ordinary tail.
