"""Deterministic selection of source-video b-roll for narration sentence timings."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.models.broll import BRollClip, BRollKind, VideoSourceContext
from app.models.script import NarrationTiming, ReelScript, ScriptSentence

_WORD = re.compile(r"[a-z0-9']+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "with",
    }
)


class BRollSelector:
    """Favors script-referenced, semantically related video before visual placeholders."""

    def allocate(
        self,
        script: ReelScript,
        timings: Sequence[NarrationTiming],
        video_sources: Sequence[VideoSourceContext],
    ) -> tuple[BRollClip, ...]:
        timings_by_sentence = {timing.sentence_index: timing for timing in timings}
        if len(timings_by_sentence) != len(script.sentences):
            raise ValueError("Narration timings must contain exactly one entry per script sentence")
        if set(timings_by_sentence) != set(range(len(script.sentences))):
            raise ValueError("Narration timings must cover every script sentence in order")

        used_ranges: dict[str, list[tuple[float, float]]] = {}
        timeline: list[BRollClip] = []
        for index, sentence in enumerate(script.sentences):
            timing = timings_by_sentence[index]
            selected = self._select_video(sentence, timing, video_sources, used_ranges)
            if selected is None:
                timeline.append(
                    BRollClip(
                        kind=BRollKind.PLACEHOLDER,
                        sentence_index=index,
                        timeline_start=timing.start,
                        timeline_end=timing.end,
                        visual_label="News brief",
                    )
                )
                continue
            source, start, end = selected
            used_ranges.setdefault(source.source_id, []).append((start, end))
            timeline.append(
                BRollClip(
                    kind=BRollKind.VIDEO,
                    sentence_index=index,
                    timeline_start=timing.start,
                    timeline_end=timing.end,
                    source_id=source.source_id,
                    source_start=start,
                    source_end=end,
                    visual_label="Source video",
                )
            )
        return tuple(timeline)

    def _select_video(
        self,
        sentence: ScriptSentence,
        timing: NarrationTiming,
        video_sources: Sequence[VideoSourceContext],
        used_ranges: dict[str, list[tuple[float, float]]],
    ) -> tuple[VideoSourceContext, float, float] | None:
        candidates: list[tuple[float, VideoSourceContext, float]] = []
        query_words = self._words(f"{sentence.text} {sentence.broll_hint}")
        for source in video_sources:
            if source.metadata.duration < timing.duration:
                continue
            source_bonus = 0.75 if source.source_id in sentence.source_ids else 0
            if source.transcript:
                for segment in source.transcript:
                    if segment.end - segment.start <= 0:
                        continue
                    score = self._similarity(query_words, self._words(segment.text)) + source_bonus
                    midpoint = (segment.start + segment.end) / 2
                    score -= self._reuse_penalty(midpoint, used_ranges.get(source.source_id, []))
                    candidates.append((score, source, midpoint))
            else:
                candidates.append((source_bonus, source, timing.start % source.metadata.duration))
        if not candidates:
            return None
        _, source, midpoint = max(
            candidates,
            key=lambda candidate: (candidate[0], -candidate[2], candidate[1].source_id),
        )
        start = min(
            max(0, midpoint - timing.duration / 2),
            source.metadata.duration - timing.duration,
        )
        end = start + timing.duration
        return source, start, end

    def _words(self, value: str) -> set[str]:
        return {word for word in _WORD.findall(value.lower()) if word not in _STOP_WORDS}

    def _similarity(self, query_words: set[str], candidate_words: set[str]) -> float:
        if not query_words or not candidate_words:
            return 0
        return len(query_words & candidate_words) / len(query_words)

    def _reuse_penalty(self, midpoint: float, used_ranges: Sequence[tuple[float, float]]) -> float:
        return 0.5 if any(start <= midpoint <= end for start, end in used_ranges) else 0