"""Offline authoring of the reusable owner branding end card."""

from __future__ import annotations

import argparse
import asyncio
import io
import math
import struct
import tempfile
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from clipfactory.composition.render import validate_end_card
from clipfactory.infrastructure.media.runner import MediaRunner


def render_outro_poster(logo: Path, font: Path) -> bytes:
    image = Image.new("RGB", (720, 1280), "#040e19")
    draw = ImageDraw.Draw(image)
    for y in range(1280):
        glow = max(0, 1 - abs(y - 640) / 640)
        draw.line((0, y, 720, y), fill=(4, round(14 + 6 * glow), round(25 + 10 * glow)))
    for x in range(60, 720, 60):
        draw.line((x, 0, x, 1280), fill="#0b1b29", width=1)
    for y in range(40, 1280, 60):
        draw.line((0, y, 720, y), fill="#0b1b29", width=1)
    with Image.open(logo) as source:
        mark = source.convert("RGBA")
        mark.thumbnail((504, 504), Image.Resampling.LANCZOS)
        image.paste(mark, ((720 - mark.width) // 2, (1280 - mark.height) // 2), mark)
    title = ImageFont.truetype(str(font), 46)
    text = "Follow for more"
    draw.text((360, 965), text, font=title, anchor="mm", fill="#f3f7fc")
    draw.line((272, 1018, 448, 1018), fill="#00b9f4", width=3)
    draw.rounded_rectangle((60, 58, 660, 62), radius=2, fill="#00b9f4")
    draw.rounded_rectangle((60, 1218, 660, 1222), radius=2, fill="#327bff")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def news_sting() -> bytes:
    """An original three-second synthesized broadcast cadence, with no sampled audio."""
    rate = 48000
    notes = ((0.06, 0.30, 293.66), (0.36, 0.30, 369.99), (0.66, 0.30, 440), (1.0, 1.6, 587.33))
    samples = bytearray()
    for index in range(3 * rate):
        t = index / rate
        value = 0.0
        for start, duration, frequency in notes:
            age = t - start
            if 0 <= age < duration:
                envelope = min(age / 0.012, 1) * min((duration - age) / 0.15, 1) * math.exp(-1.8 * age)
                tone = math.sin(2 * math.pi * frequency * age) + 0.25 * math.sin(4 * math.pi * frequency * age)
                value += 0.23 * envelope * tone
        if 1 <= t < 2.7:
            age = t - 1
            envelope = min(age / 0.03, 1) * min((2.7 - t) / 0.3, 1) * math.exp(-age)
            value += 0.12 * envelope * sum(math.sin(2 * math.pi * f * age) for f in (146.83, 185, 220)) / 3
        sample = round(max(-0.8, min(0.8, value)) * 32767)
        samples.extend(struct.pack("<hh", sample, sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples)
    return output.getvalue()


async def generate_outro(
    logo: Path, font: Path, output: Path, *, runner: MediaRunner, voice: Path | None = None
) -> None:
    poster = await asyncio.to_thread(render_outro_poster, logo, font)
    audio = await asyncio.to_thread(news_sting)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".outro-", dir=output.parent) as temporary:
        root = Path(temporary)
        picture = root / "poster.png"
        sound = root / "sting.wav"
        video = root / "outro.mp4"
        picture.write_bytes(poster)
        sound.write_bytes(audio)
        voice_arguments: list[str] = []
        audio_arguments = ["-af", "afade=t=out:st=2.7:d=0.3"]
        if voice is not None:
            probe = await runner.probe(voice)
            duration = float(probe["format"]["duration"])
            if duration <= 0 or not any(stream.get("codec_type") == "audio" for stream in probe["streams"]):
                raise ValueError("Outro voice must contain a nonempty audio stream")
            speed = max(1, duration / 2.65)
            if speed > 1.5:
                raise ValueError("Outro voice is too long for intelligible three-second delivery")
            voice_arguments = ["-i", str(voice)]
            audio_arguments = [
                "-filter_complex",
                f"[2:a]atempo={speed:.6f},aresample=48000,aformat=channel_layouts=stereo,"
                "loudnorm=I=-16:TP=-2,adelay=100:all=1,apad=whole_dur=3,atrim=duration=3[voice];"
                "[1:a]volume=0.22,afade=t=out:st=2.7:d=0.3[sting];"
                "[voice][sting]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.8:level=false[mix]",
                "-map",
                "0:v",
                "-map",
                "[mix]",
            ]
        await runner.ffmpeg(
            [
                "-hide_banner",
                "-nostdin",
                "-y",
                "-filter_complex_threads",
                "1",
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                str(picture),
                "-i",
                str(sound),
                *voice_arguments,
                "-vf",
                "fade=t=in:st=0:d=0.2,fade=t=out:st=2.8:d=0.2,format=yuv420p",
                *audio_arguments,
                "-t",
                "3",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-preset",
                "medium",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(video),
            ]
        )
        await validate_end_card(video, runner=runner)
        await asyncio.to_thread(picture.replace, output.with_suffix(".png"))
        await asyncio.to_thread(video.replace, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the original three-second inPulso end card offline")
    parser.add_argument("--logo", type=Path, default=Path("branding/inpulso_world/logo_inPulso_world.png"))
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("branding/outro.mp4"))
    parser.add_argument("--voice-file", type=Path, help="Pre-generated offline speech to mix over the sting")
    args = parser.parse_args()
    asyncio.run(
        generate_outro(
            args.logo, args.font, args.output, runner=MediaRunner(timeout_seconds=120), voice=args.voice_file
        )
    )
    print(f"Created {args.output} and {args.output.with_suffix('.png')}")


if __name__ == "__main__":
    main()
