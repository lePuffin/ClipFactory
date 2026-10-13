import asyncio
import io
import wave
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from clipfactory.infrastructure.media.branding_command import generate_profile_branding
from clipfactory.infrastructure.media.runner import MediaRunner
from clipfactory.ports.tts import SpeechRequest, SynthesizedSpeech


class FakeBrandingTTS:
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[SpeechRequest] = []

    async def synthesize(self, request: SpeechRequest) -> SynthesizedSpeech:
        self.requests.append(request)
        content = io.BytesIO()
        with wave.open(content, "wb") as voice:
            voice.setnchannels(1)
            voice.setsampwidth(2)
            voice.setframerate(48000)
            voice.writeframes(b"\x01\x00" * 48000)
        return SynthesizedSpeech(content.getvalue(), len(request.segments[0]), self.name, request.voice_id)


@pytest.mark.integration
@pytest.mark.rendering
@pytest.mark.req("CF-REQ-360")
@pytest.mark.asyncio
async def test_branding_authors_real_poster_video_and_voice_once_and_force_rebuilds(tmp_path: Path) -> None:
    for filename in ("logo_letters.png", "logo_badge.png"):
        Image.new("RGBA", (64, 64), (0, 180, 255, 255)).save(tmp_path / filename)
    logos = {name: (tmp_path / name).read_bytes() for name in ("logo_letters.png", "logo_badge.png")}
    provider = FakeBrandingTTS()
    runner = MediaRunner(timeout_seconds=120)
    arguments: dict[str, Any] = {
        "font": Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        "tts": provider,
        "runner": runner,
        "text": "Follow Football.",
        "voice_id": "fake-voice",
        "language": "en",
    }
    assert await generate_profile_branding(tmp_path, **arguments)
    assert len(provider.requests) == 1
    assert provider.requests[0] == SpeechRequest(("Follow Football.",), "en", "fake-voice", 1.0)
    with Image.open(tmp_path / "outro.png") as poster:
        assert poster.size == (720, 1280)
    with wave.open(str(tmp_path / "outro-voice.wav")) as voice:
        assert (voice.getnchannels(), voice.getframerate(), voice.getnframes()) == (1, 48000, 48000)
    probe = await runner.probe(tmp_path / "outro.mp4")
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["codec_name"], video["r_frame_rate"]) == (720, 1280, "h264", "30/1")
    assert float(probe["format"]["duration"]) == pytest.approx(3, abs=1 / 30)
    assert any(stream["codec_type"] == "audio" and stream["codec_name"] == "aac" for stream in probe["streams"])
    await runner.decode(tmp_path / "outro.mp4")
    assert not await generate_profile_branding(tmp_path, **arguments)
    assert len(provider.requests) == 1
    assert await generate_profile_branding(tmp_path, **arguments, force=True)
    assert len(provider.requests) == 2
    for name, content in logos.items():
        assert (tmp_path / name).read_bytes() == content
    assert not await asyncio.to_thread(lambda: any(path.name.startswith(".branding-") for path in tmp_path.iterdir()))
