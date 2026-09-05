import wave
from pathlib import Path

from app.core.config import Settings
from app.models.script import ReelScript, ScriptSentence
from app.services.tts import Pyttsx3TTSService


class FakeEngine:
    def __init__(self) -> None:
        self.pending: list[Path] = []
        self.properties: dict[str, object] = {}

    def setProperty(self, name: str, value: object) -> None:
        self.properties[name] = value

    def getProperty(self, name: str) -> list[object]:
        assert name == "voices"
        return []

    def save_to_file(self, _: str, path: str) -> None:
        self.pending.append(Path(path))

    def runAndWait(self) -> None:
        for path in self.pending:
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8_000)
                output.writeframes(b"\0\0" * 8_000)
        self.pending.clear()


def test_tts_synthesizes_sentence_wavs_with_measured_timings(tmp_path: Path, monkeypatch) -> None:
    service = Pyttsx3TTSService(
        Settings(_env_file=None, tts_rate=190, tts_sentence_pause_seconds=0.25)
    )
    engine = FakeEngine()
    monkeypatch.setattr(service, "_get_engine", lambda: engine)
    script = ReelScript(
        title="Test script",
        sentences=[
            ScriptSentence(text="First narration sentence.", duration_seconds=2),
            ScriptSentence(text="Second narration sentence.", duration_seconds=2),
        ],
    )

    narration = service.synthesize(script, tmp_path / "narration.wav")

    assert narration.path.is_file()
    assert narration.duration == 2.25
    assert [(item.start, item.end) for item in narration.timings] == [(0, 1.25), (1.25, 2.25)]
    assert engine.properties["rate"] == 190
    with wave.open(str(narration.path), "rb") as output:
        assert output.getframerate() == 8_000
        assert output.getnframes() == 18_000
    assert not (tmp_path / "tts-segments").exists()