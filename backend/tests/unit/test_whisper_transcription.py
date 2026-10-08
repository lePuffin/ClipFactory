from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from clipfactory.infrastructure.providers.transcription.whisper_local import WhisperLocalTranscriptionProvider
from clipfactory.infrastructure.settings import EnvironmentSettings


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


@pytest.mark.unit
@pytest.mark.req("CF-REQ-310")
@pytest.mark.asyncio
async def test_whisper_adapter_returns_word_timestamps_and_reuses_model(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"mock audio")
    model_calls: list[str] = []

    class Model:
        def transcribe(self, path: str, *, language: str, word_timestamps: bool):
            model_calls.append(path)
            assert language == "pt"
            assert word_timestamps
            words = [
                SimpleNamespace(word=" Olá", start=0.1, end=0.4, probability=0.99),
                SimpleNamespace(word=" mundo", start=0.4, end=0.9, probability=0.95),
            ]
            return [SimpleNamespace(start=0.1, end=0.9, words=words)], SimpleNamespace(duration=1.0, language="pt")

    factory_calls: list[dict[str, Any]] = []

    def factory(model_name: str, **kwargs: Any) -> Model:
        factory_calls.append({"model": model_name, **kwargs})
        return Model()

    provider = WhisperLocalTranscriptionProvider(_settings(), model_factory=factory)
    first = await provider.transcribe(audio, "pt")
    second = await provider.transcribe(audio, "pt")
    assert len(factory_calls) == 1
    assert len(model_calls) == 2
    assert first.words[0].text == "Olá"
    assert first.words[1].end_seconds == 0.9
    assert first.duration_seconds == 1.0
    assert second.language == "pt"

    provider.settings.whisper_model = "owner-selected-model"
    await provider.transcribe(audio, "pt")
    assert len(factory_calls) == 2
    assert factory_calls[-1]["model"] == "owner-selected-model"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-310")
@pytest.mark.asyncio
@pytest.mark.parametrize("device", ["auto", "cuda"])
async def test_missing_cuda_library_falls_back_only_for_auto(tmp_path: Path, device: Literal["auto", "cuda"]) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"mock audio")
    devices = []

    class Model:
        def __init__(self, selected_device: str) -> None:
            self.device = selected_device

        def transcribe(self, path, **kwargs):
            def segments():
                if self.device != "cpu":
                    raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
                yield SimpleNamespace(end=1.0, words=[SimpleNamespace(word="hello", start=0.0, end=1.0)])

            return segments(), SimpleNamespace(duration=1.0, language="en")

    def factory(model_name, **kwargs):
        devices.append(kwargs["device"])
        return Model(kwargs["device"])

    settings = _settings()
    settings.whisper_device = device
    provider = WhisperLocalTranscriptionProvider(settings, model_factory=factory)
    if device == "cuda":
        with pytest.raises(RuntimeError, match="libcublas"):
            await provider.transcribe(audio, "en")
        assert devices == ["cuda"]
    else:
        first = await provider.transcribe(audio, "en")
        second = await provider.transcribe(audio, "en")
        assert first.words[0].text == second.words[0].text == "hello"
        assert devices == ["auto", "cpu"]
        assert settings.whisper_device == "auto"
