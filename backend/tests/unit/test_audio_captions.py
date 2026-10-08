import asyncio
import io
import wave
from functools import partial
from itertools import pairwise
from pathlib import Path
from uuid import uuid4

import pytest

from clipfactory.infrastructure.storage import LocalStorageProvider
from clipfactory.ports.transcription import RecognizedWord, Transcript
from clipfactory.ports.tts import SpeechRequest, SynthesizedSpeech
from clipfactory.production.alignment import AlignedWord
from clipfactory.production.audio_captions import (
    NarrationDurationGateError,
    generate_narration,
    produce_narration_and_captions,
)
from clipfactory.production.captions import FontMetrics
from clipfactory.production.timing import reconcile_visual_timing


def _wav(duration_seconds: float) -> bytes:
    sample_rate = 48_000
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(round(sample_rate * duration_seconds) * 2))
    return output.getvalue()


class FakeTTS:
    name = "fake"

    def __init__(self, audio: bytes) -> None:
        self.audio = audio
        self.calls = 0

    async def synthesize(self, request: SpeechRequest) -> SynthesizedSpeech:
        self.calls += 1
        return SynthesizedSpeech(self.audio, sum(map(len, request.segments)), self.name, request.voice_id)


class FakeTranscription:
    name = "fake"

    async def transcribe(self, audio_path: Path, language: str) -> Transcript:
        assert await asyncio.to_thread(audio_path.is_file)
        return Transcript(
            (RecognizedWord("Hello", 0.1, 0.4), RecognizedWord("there.", 0.4, 0.8)),
            2.0,
            language,
        )


class FakeFontMetrics(FontMetrics):
    def getlength(self, text: str) -> float:
        return float(len(text) * 20)

    def getmetrics(self) -> tuple[int, int]:
        return 48, 12


def _font_loader(_path: str, _size: int) -> FontMetrics:
    return FakeFontMetrics()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-302")
@pytest.mark.asyncio
async def test_targeted_narration_retry_does_not_reuse_rejected_audio(tmp_path: Path) -> None:
    tts = FakeTTS(_wav(2.0))
    arguments = partial(
        generate_narration,
        script_segments=("Hello there.",),
        language="en",
        voice_id="voice-1",
        speaking_rate=1.0,
        min_seconds=1,
        max_seconds=5,
        lead_in_seconds=0.3,
        tail_seconds=1,
        speaking_words_per_minute=150,
        tts=tts,
        storage=LocalStorageProvider(tmp_path),
    )
    original = await arguments()
    await arguments()
    tts.audio = _wav(3.0)
    retried = await arguments(force_refresh=True)
    assert tts.calls == 2
    assert not retried.cached
    assert retried.narration_key != original.narration_key
    assert await arguments.keywords["storage"].read_bytes(original.narration_key) == _wav(2.0)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-302")
@pytest.mark.req("CF-REQ-311")
@pytest.mark.req("CF-REQ-312")
@pytest.mark.asyncio
async def test_audio_caption_use_case_caches_narration_and_persists_ass(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path / "data")
    tts = FakeTTS(_wav(2.0))
    args = {
        "run_id": uuid4(),
        "attempt": 1,
        "script_segments": ("Hello there.",),
        "language": "en",
        "voice_id": "voice-1",
        "speaking_rate": 1.0,
        "min_seconds": 1.0,
        "max_seconds": 5.0,
        "lead_in_seconds": 0.1,
        "tail_seconds": 0.1,
        "tts": tts,
        "transcription": FakeTranscription(),
        "storage": storage,
        "font_file": Path("fake-font.ttf"),
        "speaking_words_per_minute": 150,
        "font_loader": _font_loader,
    }
    first = await produce_narration_and_captions(**args)
    second = await produce_narration_and_captions(**args)
    assert tts.calls == 1
    assert not first.cached
    assert second.cached
    assert first.narration_duration_seconds == 2.0
    caption_bytes = await storage.read_bytes(first.caption_key)
    assert b"Dialogue:" in caption_bytes
    assert first.alignment.words[0].text == "Hello"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-304")
@pytest.mark.asyncio
async def test_audio_caption_use_case_routes_duration_failure_with_word_delta(tmp_path: Path) -> None:
    storage = LocalStorageProvider(tmp_path / "data")
    with pytest.raises(NarrationDurationGateError) as caught:
        await produce_narration_and_captions(
            run_id=uuid4(),
            attempt=1,
            script_segments=("Hello there.",),
            language="en",
            voice_id="voice-1",
            speaking_rate=1.0,
            min_seconds=5.0,
            max_seconds=10.0,
            lead_in_seconds=0.3,
            tail_seconds=1.0,
            tts=FakeTTS(_wav(2.0)),
            transcription=FakeTranscription(),
            storage=storage,
            font_file=Path("fake-font.ttf"),
            speaking_words_per_minute=150,
            font_loader=_font_loader,
        )
    assert caught.value.code == "narration_too_short"
    assert caught.value.action_word_count == 5


@pytest.mark.unit
@pytest.mark.req("CF-REQ-351")
@pytest.mark.parametrize("duration", [6.7, 6.8, 17.0])
def test_reconciled_visual_timing_splits_oversized_spans_and_preserves_assets(duration: float) -> None:
    segments = [
        {
            "index": 0,
            "script_segment_index": 0,
            "planned_duration_seconds": 7.0,
            "selected_asset_id": "chosen-asset",
            "motion": "ken_burns",
            "transition_in": "crossfade",
        }
    ]
    result = reconcile_visual_timing(
        segments,
        (AlignedWord("Narration", 0.0, duration, 0),),
        narration_duration_seconds=duration,
        lead_in_seconds=0.3,
        tail_seconds=1.0,
        max_segment_seconds=8.0,
    )
    assert result[0]["start_seconds"] == 0.0
    assert result[-1]["end_seconds"] == pytest.approx(duration + 1.3)
    assert [item["index"] for item in result] == list(range(len(result)))
    assert all(item["selected_asset_id"] == "chosen-asset" for item in result)
    assert all(1.5 <= item["end_seconds"] - item["start_seconds"] <= 8.0 for item in result)
    assert all(left["end_seconds"] == right["start_seconds"] for left, right in pairwise(result))
