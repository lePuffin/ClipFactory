"""Explicit one-time authoring of a profile's reusable branding assets."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from PIL import Image, ImageFont

from clipfactory.composition.render import validate_end_card
from clipfactory.infrastructure.media.brand_outro import generate_outro
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.ports.tts import SpeechRequest, TTSProvider


def _validate_logos(directory: Path) -> None:
    for filename in ("logo_letters.png", "logo_badge.png"):
        path = directory / filename
        if not path.is_file() or path.resolve().parent != directory:
            raise ValueError(f"Place {filename} inside the profile branding folder first")
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(f"{filename} must be a PNG image")
            image.verify()


async def generate_profile_branding(
    directory: Path,
    *,
    font: Path,
    tts: TTSProvider,
    runner: MediaRunner,
    text: str,
    voice_id: str,
    language: str,
    force: bool = False,
) -> bool:
    directory = await asyncio.to_thread(lambda: directory.expanduser().resolve(strict=True))
    if not text.strip():
        raise ValueError("Outro speech text must not be empty")
    await asyncio.to_thread(_validate_logos, directory)
    outputs = ("outro-voice.wav", "outro.png", "outro.mp4")
    for filename in outputs:
        path = directory / filename
        if path.is_symlink():
            raise ValueError(f"{filename} must not be a symbolic link")
    if not force and all((directory / filename).is_file() for filename in outputs):
        await validate_end_card(directory / "outro.mp4", runner=runner)
        await runner.probe(directory / "outro-voice.wav")
        return False
    font = await asyncio.to_thread(lambda: font.expanduser().resolve(strict=True))
    await asyncio.to_thread(ImageFont.truetype, str(font), 46)
    with tempfile.TemporaryDirectory(prefix=".branding-", dir=directory) as temporary:
        staged = Path(temporary)
        voice = staged / "outro-voice.wav"
        if not force and (directory / "outro-voice.wav").is_file():
            voice_bytes = await asyncio.to_thread((directory / "outro-voice.wav").read_bytes)
            await asyncio.to_thread(voice.write_bytes, voice_bytes)
        else:
            speech = await tts.synthesize(SpeechRequest((text.strip(),), language, voice_id, 1.0))
            await asyncio.to_thread(voice.write_bytes, speech.wav_bytes)
        await generate_outro(directory / "logo_badge.png", font, staged / "outro.mp4", runner=runner, voice=voice)
        for filename in outputs:
            await asyncio.to_thread((staged / filename).replace, directory / filename)
    return True
