"""Deterministic alignment from recognized audio words to Script spelling."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from num2words import num2words

from clipfactory.ports.transcription import Transcript


@dataclass(frozen=True, slots=True)
class ScriptToken:
    text: str
    segment_index: int


@dataclass(frozen=True, slots=True)
class AlignedWord:
    text: str
    start_seconds: float
    end_seconds: float
    script_segment_index: int


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    words: tuple[AlignedWord, ...]
    wer: float


def align_transcript(script_segments: Sequence[str], transcript: Transcript) -> AlignmentResult:
    script_tokens = [
        ScriptToken(token, segment_index)
        for segment_index, segment in enumerate(script_segments)
        for token in re.findall(r"\S+", segment)
    ]
    recognized = list(transcript.words)
    if not script_tokens:
        return AlignmentResult((), 1.0 if recognized else 0.0)
    script_normalized = [_normalize(token.text) for token in script_tokens]
    recognized_normalized = [_normalize(word.text) for word in recognized]
    opcodes = SequenceMatcher(None, script_normalized, recognized_normalized, autojunk=False).get_opcodes()
    timing_by_script_index: dict[int, tuple[float, float]] = {}
    substitutions = deletions = insertions = 0
    for operation, script_start, script_end, transcript_start, transcript_end in opcodes:
        script_count = script_end - script_start
        transcript_count = transcript_end - transcript_start
        if operation == "equal":
            for offset in range(script_count):
                word = recognized[transcript_start + offset]
                timing_by_script_index[script_start + offset] = (word.start_seconds, word.end_seconds)
        elif operation == "replace":
            paired = min(script_count, transcript_count)
            substitutions += paired
            deletions += script_count - paired
            insertions += transcript_count - paired
            for offset in range(paired):
                word = recognized[transcript_start + offset]
                timing_by_script_index[script_start + offset] = (word.start_seconds, word.end_seconds)
        elif operation == "delete":
            deletions += script_count
        elif operation == "insert":
            insertions += transcript_count

    _interpolate_missing(timing_by_script_index, len(script_tokens), transcript.duration_seconds)
    words = tuple(
        AlignedWord(
            token.text,
            timing_by_script_index[index][0],
            timing_by_script_index[index][1],
            token.segment_index,
        )
        for index, token in enumerate(script_tokens)
    )
    expected, actual = _comparison_tokens(
        " ".join(script_segments), " ".join(word.text for word in recognized), transcript.language
    )
    comparisons = SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
    errors = sum(
        max(left_end - left_start, right_end - right_start)
        for operation, left_start, left_end, right_start, right_end in comparisons
        if operation != "equal"
    )
    wer = errors / max(1, len(expected))
    return AlignmentResult(words, wer)


def _comparison_tokens(expected: str, actual: str, language: str) -> tuple[list[str], list[str]]:
    if language.split("-")[0] != "en":
        return ([_normalize(word) for word in expected.split()], [_normalize(word) for word in actual.split()])
    numeric = re.compile(r"(?<!\w)-?\d+(?:\s*[,\.]\s*\d+)*")
    values = {
        match.group().replace(" ", "").replace(",", "")
        for text in (expected, actual)
        for match in numeric.finditer(text)
    }
    forms: list[tuple[str, str]] = []
    markers: dict[str, str] = {}
    for raw in values:
        if len(raw) > 18:
            continue
        value = Decimal(raw)
        marker = "numeric" + format(value.normalize(), "f").replace("-", "negative").replace(".", "point")
        markers[raw] = marker
        variants = [str(num2words(value))]
        if value == int(value) and 1000 <= value <= 2999:
            variants.append(str(num2words(int(value), to="year")))
        for variant in variants:
            words = re.findall(r"\w+", variant.casefold())
            pattern = r"\s+".join(r"(?:and\s+)?" if word == "and" else re.escape(word) for word in words)
            pattern = pattern.replace(r"\s+(?:and\s+)?\s+", r"\s+(?:and\s+)?")
            forms.append((pattern, marker))

    def tokens(text: str) -> list[str]:
        text = re.sub(
            r"([£$€])\s*(-?\d+(?:\s*[,\.]\s*\d+)*)",
            lambda match: match[2] + " " + {"£": "pounds", "$": "dollars", "€": "euros"}[match[1]],
            text,
        )
        text = numeric.sub(
            lambda match: markers.get(match.group().replace(" ", "").replace(",", ""), match.group()), text
        )
        text = " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKD", text).casefold()))
        for pattern, marker in sorted(forms, key=lambda item: len(item[0]), reverse=True):
            text = re.sub(r"\b" + pattern + r"\b", marker, text)
        return list[str](text.split())

    return tokens(expected), tokens(actual)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if character.isalnum())


def _interpolate_missing(timings: dict[int, tuple[float, float]], count: int, duration: float) -> None:
    known = sorted(timings)
    if not known:
        step = duration / count if duration > 0 else 0.0
        for index in range(count):
            timings[index] = (index * step, (index + 1) * step)
        return
    for index in range(count):
        if index in timings:
            continue
        before = max((item for item in known if item < index), default=None)
        after = min((item for item in known if item > index), default=None)
        if before is None:
            next_start = timings[after][0] if after is not None else duration
            gap_count = (after or 0) + 1
            step = max(next_start, 0) / gap_count
            timings[index] = (index * step, (index + 1) * step)
        elif after is None:
            previous_end = timings[before][1]
            gap_count = count - before
            step = max(duration - previous_end, 0) / gap_count
            timings[index] = (previous_end + (index - before - 1) * step, previous_end + (index - before) * step)
        else:
            left_end = timings[before][1]
            right_start = timings[after][0]
            gap_count = after - before
            step = max(right_start - left_end, 0) / gap_count
            timings[index] = (left_end + (index - before - 1) * step, left_end + (index - before) * step)
    previous_start = 0.0
    for index in range(count):
        start, end = timings[index]
        start = min(max(start, previous_start, 0.0), duration)
        end = min(max(end, start), duration)
        timings[index] = (start, end)
        previous_start = start
