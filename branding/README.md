# Profile branding

Each saved Content Profile owns a readable name-derived folder, such as
`branding/football-news-english/`. The Profile page shows its exact folder
and authoring command. Folder names are assigned once and remain stable
when a profile is renamed; collisions receive a unique suffix.

Personal logos, voices, posters and videos are ignored by Git. Only this
generic instruction file is tracked. Legacy UUID paths may remain as
compatibility symlinks for earlier Run snapshots; use the named folders.

Place these two owner-provided PNG images in the folder:

- `logo_letters.png`: transparent wordmark for the top-right Clip overlay.
- `logo_badge.png`: badge centered in the three-second end card.

From the repository root, generate the remaining files:

```bash
uv run clipfactory branding branding/<profile-slug>
```

The command uses the configured Google TTS credentials and installed caption
font to create `outro-voice.wav`, `outro.png` and `outro.mp4`. Speech defaults
to "Follow for more." The video is 720x1280, 30 FPS, H.264/AAC, with an original
locally synthesized news sting underneath the voice.

Customize the spoken line and voice if needed:

```bash
uv run clipfactory branding branding/<profile-slug> \
  --text "Follow our channel for more." \
  --voice-id en-US-Chirp3-HD-Leda \
  --language en
```

Use `--font /absolute/path/font.ttf` to select another local font. Keep speech
brief: it must fit three seconds with at most 1.5x time compression.

Completed assets are validated and reused without another TTS request.
Use `--force` after changing logos, speech or voice to rebuild all three
generated files. A failed rebuild preserves the previous completed assets.
An incomplete build reuses an existing `outro-voice.wav` rather than requesting
speech again.

New Runs automatically select their profile's wordmark and end card. They
never borrow another profile's assets or generate branding speech. If the
MP4 is missing but that folder contains its badge and voice, composition can
rebuild the local end card. Missing or invalid inputs fail explicitly.
Each Run freezes and hashes its end card; saved revisions reuse that frozen
copy. Existing Run snapshots are unchanged. Profile deletion retains branding.

The original shared files and named logo folders are retained as migration
sources; they are not defaults for new profiles.
