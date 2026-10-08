import io
import wave
from typing import Any

import pytest

from clipfactory.infrastructure.providers.tts.google import GoogleTTSProvider
from clipfactory.infrastructure.settings import EnvironmentSettings
from clipfactory.ports.tts import SpeechRequest


def _settings() -> EnvironmentSettings:
    values: dict[str, Any] = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused",
        "LLM_PROVIDER": "fake",
        "NEWS_SOURCES": "fake",
        "TTS_PROVIDER": "fake",
        "TRANSCRIPTION_PROVIDER": "fake",
        "PUBLIC_MEDIA_BASE_URL": None,
        "MEDIA_URL_SIGNING_KEY": None,
    }
    return EnvironmentSettings(**values)


def _wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(48_000)
        wav_file.writeframes(pcm)
    return output.getvalue()


class FakeSpeechClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def synthesize_speech(self, *, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        return type("SpeechResponse", (), {"audio_content": _wav(bytes(200))})()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-300")
@pytest.mark.req("CF-REQ-305")
@pytest.mark.asyncio
async def test_google_tts_returns_mono_48khz_pcm_and_preserves_voice_settings() -> None:
    client = FakeSpeechClient()
    provider = GoogleTTSProvider(_settings(), client=client)
    result = await provider.synthesize(
        SpeechRequest(("First sentence.", "Second sentence."), "en-US", "en-US-Chirp3-HD-Leda", 1.0)
    )
    with wave.open(io.BytesIO(result.wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 48_000
        assert wav_file.getnframes() == 100
    assert result.character_count == len("First sentence.\nSecond sentence.")
    assert result.provider == "google"
    assert client.requests[0]["voice"].name == "en-US-Chirp3-HD-Leda"
    assert client.requests[0]["audio_config"].speaking_rate == 1.0


@pytest.mark.unit
@pytest.mark.req("CF-REQ-300")
@pytest.mark.asyncio
async def test_google_tts_chunks_long_text_and_concatenates_wave_frames() -> None:
    client = FakeSpeechClient()
    provider = GoogleTTSProvider(_settings(), client=client)
    text = "word " * 2_000
    result = await provider.synthesize(SpeechRequest((text,), "en", "voice", 1.0))
    assert len(client.requests) == 3
    with wave.open(io.BytesIO(result.wav_bytes), "rb") as wav_file:
        assert wav_file.getnframes() == 300
    assert result.character_count == len(text.strip())


@pytest.mark.unit
@pytest.mark.req("CF-REQ-300")
@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected"), [("en", "en-US"), ("en-US", "en-US"), ("fr", "fr")])
async def test_generic_language_uses_matching_voice_locale(language: str, expected: str) -> None:
    client = FakeSpeechClient()
    provider = GoogleTTSProvider(_settings(), client=client)
    await provider.synthesize(SpeechRequest(("A sentence.",), language, "en-US-Chirp3-HD-Leda", 1.0))
    assert client.requests[0]["voice"].language_code == expected
