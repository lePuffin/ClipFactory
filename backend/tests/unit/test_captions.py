from pathlib import Path
from typing import Any

import pytest

from clipfactory.ports.transcription import RecognizedWord, Transcript
from clipfactory.production.alignment import AlignedWord, align_transcript
from clipfactory.production.captions import build_caption_track, render_ass


@pytest.mark.unit
@pytest.mark.req("CF-REQ-311")
def test_alignment_preserves_script_spelling_and_interpolates_unrecognized_words() -> None:
    transcript = Transcript(
        (
            RecognizedWord("hello", 0.2, 0.4),
            RecognizedWord("world", 0.4, 0.8),
        ),
        1.0,
        "en",
    )
    result = align_transcript(["Hello, brave world!"], transcript)
    assert [word.text for word in result.words] == ["Hello,", "brave", "world!"]
    assert result.words[0].start_seconds == 0.2
    assert result.words[2].end_seconds == 0.8
    assert result.words[1].start_seconds <= result.words[1].end_seconds
    assert result.wer == pytest.approx(1 / 3)


@pytest.mark.unit
@pytest.mark.req("CF-REQ-311")
@pytest.mark.parametrize(
    ("script", "recognized", "expected_wer"),
    [
        ("Sixty trains in twenty twenty-two", "60 trains in 2022", 0),
        ("Five thousand eight hundred thirty-one passengers", "5 ,831 passengers", 0),
        ("Sixty trains departed", "61 trains departed", 1 / 3),
        ("Sixty trains departed safely", "60 departed", 0.5),
        ("It costs £2.24", "It costs two point two four pounds", 0),
    ],
)
def test_wer_numeric_formatting_preserves_real_value_and_omission_errors(script, recognized, expected_wer) -> None:
    words = tuple(RecognizedWord(text, index * 0.2, (index + 1) * 0.2) for index, text in enumerate(recognized.split()))
    result = align_transcript([script], Transcript(words, len(words) * 0.2, "en"))
    assert result.wer == pytest.approx(expected_wer)
    assert [word.text for word in result.words] == script.split()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-312")
@pytest.mark.req("CF-REQ-313")
def test_caption_layout_respects_safe_area_and_burn_text_escapes_ass_markup() -> None:
    class FakeFont:
        def getlength(self, text: str) -> float:
            return len(text) * 24.0

        def getmetrics(self) -> tuple[int, int]:
            return 52, 12

    def load_font(_path: str, _size: int) -> Any:
        return FakeFont()

    words = tuple(
        AlignedWord(text, index * 0.3, (index + 1) * 0.3, 0)
        for index, text in enumerate(("A", "literal", "{\\b1}", "caption", "stays", "within", "safe", "area."))
    )
    track = build_caption_track(words, font_file=Path("fake-bold-font.ttf"), font_loader=load_font)
    assert track.cues
    assert all(len(cue.lines) <= 2 for cue in track.cues)
    assert all(cue.x >= 43 and cue.x + cue.width <= 677 for cue in track.cues)
    assert all(cue.y + cue.height <= 1152 for cue in track.cues)
    ass = render_ass(track)
    assert r"\{\\b1\}" in ass
    assert "Dialogue: 0,0:00:00.00" in ass
    assert r"\pos(360," in ass
    assert r"\fs56" in ass


@pytest.mark.unit
@pytest.mark.req("CF-REQ-312")
def test_caption_wrapping_reserves_box_padding_inside_safe_margins() -> None:
    class Font:
        def getlength(self, text: str) -> float:
            return len(text) * 10.0

        def getmetrics(self) -> tuple[int, int]:
            return 52, 12

    words = (AlignedWord("a" * 31, 0.0, 0.5, 0), AlignedWord("b" * 30, 0.5, 1.0, 0))
    track = build_caption_track(words, font_file=Path("fake.ttf"), font_loader=lambda _path, _size: Font())
    assert track.cues[0].lines == ("a" * 31, "b" * 30)
    assert track.cues[0].x >= 43
    assert track.cues[0].x + track.cues[0].width <= 677
