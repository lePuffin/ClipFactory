"""Deterministic matching of named public figures in narration (CF-REQ-268)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from clipfactory.planning.script import PersonDraft

MIN_PIECE_WORDS = 3
# About three seconds of narration: shorter remainders stay on the portrait rather than flash a new shot.
MIN_AFTER_PERSON_WORDS = 8
_NAME_PARTICLES = {"jr", "jr.", "sr", "sr.", "ii", "iii"}
# Lowercase surname particles inside full names ("Lula da Silva", "von der Leyen").
_SURNAME_PARTICLES = ("da", "das", "de", "del", "della", "der", "di", "do", "dos", "du", "van", "von", "bin", "ibn")


@dataclass(frozen=True, slots=True)
class Mention:
    word_index: int
    name: str


def person_aliases(person: PersonDraft) -> tuple[str, ...]:
    """Spoken forms that identify the person: declared mentions, full name and a distinctive surname."""
    aliases = [*person.mentions, person.name]
    parts = [part for part in person.name.split() if part.casefold() not in _NAME_PARTICLES]
    if len(parts) >= 2 and len(parts[-1]) >= 4:
        aliases.append(parts[-1])
    particle = next((index for index, part in enumerate(parts) if part in _SURNAME_PARTICLES), None)
    if particle is not None and particle > 0 and particle < len(parts) - 1:
        aliases.append(" ".join(parts[particle:]))
        if particle > 1 and len(parts[particle - 1]) >= 4:
            aliases.append(parts[particle - 1])  # "Lula" in "Luiz Inacio Lula da Silva"
    return tuple(dict.fromkeys(" ".join(alias.split()) for alias in aliases if alias.strip()))


_HYPHENS = "[-\u2010\u2011\u2012\u2013]"


def _ascii_hyphens(text: str) -> str:
    """Narration from free models often spells "El-Sayed" with a non-breaking hyphen (U+2011)."""
    return re.sub("[\u2010\u2011\u2012]", "-", text)


def mentions_in(text: str, aliases: Sequence[str]) -> list[int]:
    """Word indexes where any alias starts as a whole word (possessives allowed), case-insensitively."""
    if not aliases:
        return []
    pattern = re.compile(
        r"(?<![\w'\u2019])(?:"
        + "|".join(
            re.escape(_ascii_hyphens(alias)).replace(r"\-", _HYPHENS)
            for alias in sorted(aliases, key=len, reverse=True)
        )
        + r")(?:['\u2019]s?)?(?![\w])",
        re.IGNORECASE,
    )
    starts = [match.start() for match in pattern.finditer(text)]
    return [len(text[:start].split()) for start in starts]


def find_mentions(text: str, people: Sequence[PersonDraft]) -> list[Mention]:
    """First-person-wins ordered mentions; overlapping matches at one word keep the longest declared name."""
    found: dict[int, str] = {}
    for person in sorted(people, key=lambda item: len(item.name), reverse=True):
        for index in mentions_in(text, person_aliases(person)):
            found.setdefault(index, person.name)
    return [Mention(index, found[index]) for index in sorted(found)]


def split_at_mentions(text: str, people: Sequence[PersonDraft]) -> list[tuple[str, str | None]]:
    """Split narration into contiguous pieces, each starting at a person's mention (None = no person).

    Every piece keeps at least ``MIN_PIECE_WORDS`` words; a mention too close to the previous boundary stays in the
    previous piece. A person's piece ends with the sentence naming them when at least ``MIN_AFTER_PERSON_WORDS``
    words follow before the next mention, so a portrait is not held over narration about something else.
    Joining the pieces with spaces reproduces the normalized narration.
    """
    words = text.split()
    mentions = find_mentions(text, people)
    if not words or not mentions:
        return [(" ".join(words), None)] if words else []

    def close_person(until: int) -> None:
        start, name = boundaries[-1]
        if name is None:
            return
        cut = next(
            (index + 1 for index in range(start, until) if re.search(r"[.!?][\"'\u201d\u2019)]*$", words[index])),
            None,
        )
        if cut is not None and cut - start >= MIN_PIECE_WORDS and until - cut >= MIN_AFTER_PERSON_WORDS:
            boundaries.append((cut, None))

    boundaries: list[tuple[int, str | None]] = []
    first = mentions[0]
    if first.word_index >= MIN_PIECE_WORDS:
        boundaries.append((0, None))
        boundaries.append((first.word_index, first.name))
    else:
        boundaries.append((0, first.name))
    for mention in mentions[1:]:
        too_close = mention.word_index - boundaries[-1][0] < MIN_PIECE_WORDS
        if too_close or len(words) - mention.word_index < MIN_PIECE_WORDS:
            continue
        close_person(mention.word_index)
        start, name = boundaries[-1]
        if mention.name == name or mention.word_index - start < MIN_PIECE_WORDS:
            continue
        boundaries.append((mention.word_index, mention.name))
    if len(boundaries) > 1 and len(words) - boundaries[-1][0] < MIN_PIECE_WORDS:
        boundaries.pop()
    close_person(len(words))
    pieces: list[tuple[str, str | None]] = []
    for position, (start, name) in enumerate(boundaries):
        end = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(words)
        pieces.append((" ".join(words[start:end]), name))
    return pieces


MAX_NAME_CANDIDATES = 8
_TITLE_WORDS = {
    "according",
    "a",
    "an",
    "and",
    "but",
    "by",
    "former",
    "from",
    "for",
    "governor",
    "gov",
    "gov.",
    "he",
    "her",
    "his",
    "in",
    "it",
    "mayor",
    "minister",
    "mr",
    "mr.",
    "mrs",
    "mrs.",
    "ms",
    "ms.",
    "on",
    "president",
    "prime",
    "rep",
    "rep.",
    "secretary",
    "sen",
    "sen.",
    "senator",
    "she",
    "the",
    "their",
    "they",
    "this",
    "today",
    "when",
    "while",
    "with",
}
_ROLE_WORDS = {
    "chancellor",
    "chief",
    "colonel",
    "commander",
    "director",
    "dr",
    "dr.",
    "general",
    "governor",
    "judge",
    "justice",
    "king",
    "lieutenant",
    "major",
    "mayor",
    "minister",
    "pope",
    "president",
    "prince",
    "princess",
    "queen",
    "secretary",
    "senator",
    "speaker",
    "spokesman",
    "spokesperson",
    "spokeswoman",
}
_TITLE_WORDS |= _ROLE_WORDS
_INSTITUTION_WORDS = {
    "administration",
    "agency",
    "airline",
    "airlines",
    "airport",
    "army",
    "assembly",
    "association",
    "bank",
    "center",
    "centre",
    "club",
    "college",
    "commission",
    "committee",
    "company",
    "corporation",
    "council",
    "court",
    "department",
    "embassy",
    "emirates",
    "forces",
    "foundation",
    "government",
    "group",
    "hospital",
    "institute",
    "international",
    "kingdom",
    "league",
    "ministry",
    "museum",
    "nations",
    "news",
    "office",
    "organisation",
    "organization",
    "parliament",
    "party",
    "police",
    "republic",
    "school",
    "senate",
    "states",
    "station",
    "union",
    "university",
}
_ARTICLE_PREFIX = r"(?:al|el|ad|an|ar|as|ash|at|az)-"
_ROLE_TITLES = (
    "President|Prime Minister|Chancellor|Premier|Governor|Mayor|Senator|Sen\\.|Rep\\.|Gov\\.|Secretary|"
    "Minister|Speaker|Pope|King|Queen|Prince|Princess|General|Judge|Justice|Mr\\.?|Mrs\\.?|Ms\\.?|Dr\\.?"
)
_SURNAME_CONTEXT = re.compile(
    rf"\b(?:{_ROLE_TITLES})\s+(?P<titled>[A-Z][a-z][\w-]+)\b(?!\s+(?:[A-Z]|{_ARTICLE_PREFIX}))"
    r"|\b(?P<governing>[A-Z][a-z][\w-]+)(?:['\u2019]s)?\s+(?:administration|government|presidency|campaign|cabinet|regime)\b"
)
_CAPITALIZED_RUN = re.compile(
    r"[A-Z][\w'\u2019.-]*(?:\s+(?:(?:"
    + "|".join(_SURNAME_PARTICLES)
    + r")\s+)*(?:"
    + _ARTICLE_PREFIX
    + r")?[A-Z][\w'\u2019.-]*)+"
)


def _capitalized(word: str) -> bool:
    return re.sub(rf"^{_ARTICLE_PREFIX}", "", word)[:1].isupper()


def _is_title(word: str) -> bool:
    return any(part.casefold() in _TITLE_WORDS for part in word.split("-"))


def _is_role(word: str) -> bool:
    return any(part.casefold() in _ROLE_WORDS for part in word.split("-"))


def _full_names(text: str) -> list[str]:
    names: list[str] = []
    for match in _CAPITALIZED_RUN.finditer(text):
        words = [re.sub(r"['\u2019]s?$", "", word).rstrip(".,") for word in match.group().split()]
        groups: list[list[str]] = [[]]
        for word in words:
            if _is_title(word):
                groups.append([])
            else:
                groups[-1].append(word)
        for group in groups:
            capitalized = [word for word in group if word not in _SURNAME_PARTICLES]
            if (
                2 <= len(capitalized) <= 4
                and group[0][:1].isupper()
                and all(_capitalized(word) for word in capitalized)
                and not any(word.casefold() in _INSTITUTION_WORDS for word in group)
            ):
                names.append(" ".join(group))
    return names


def expand_bare_names(people: Sequence[PersonDraft], evidence: Sequence[str]) -> tuple[PersonDraft, ...]:
    """Replace a single-word declared name with the one evidence full name ending in it (CF-REQ-268)."""
    found = [name for text in evidence for name in _full_names(_ascii_hyphens(text))]
    expanded: list[PersonDraft] = []
    for person in people:
        name = " ".join(person.name.split())
        if len(name.split()) != 1:
            expanded.append(person)
            continue
        matches = {full for full in found if full.split()[-1].casefold() == name.casefold()}
        if len(matches) != 1:
            expanded.append(person)
            continue
        full = matches.pop()
        expanded.append(PersonDraft(name=full, mentions=list(dict.fromkeys([*person.mentions, name]))))
    return tuple(expanded)


def name_candidates(narration: Sequence[str], evidence: Sequence[str], declared: Sequence[PersonDraft]) -> list[str]:
    """Undeclared full-name candidates spoken in narration, most-mentioned first (CF-REQ-268).

    Candidates are runs of 2-4 capitalized words split at titles such as "Mayor"; they still need identity
    verification before they may be treated as people.
    """
    narration = [_ascii_hyphens(text) for text in narration]
    evidence = [_ascii_hyphens(text) for text in evidence]
    spoken = " ".join(narration)
    covered = [_ascii_hyphens(alias).casefold() for person in declared for alias in person_aliases(person)]
    counts: dict[str, int] = {}
    titled: set[str] = set()
    for text in [*narration, *evidence]:
        for match in _CAPITALIZED_RUN.finditer(text):
            words = [re.sub(r"['\u2019]s?$", "", word).rstrip(".,") for word in match.group().split()]
            preceding = text[: match.start()].split()[-1:]
            groups: list[tuple[bool, list[str]]] = [(bool(preceding) and _is_role(preceding[0]), [])]
            for word in words:
                if _is_title(word):
                    groups.append((_is_role(word), []))
                else:
                    groups[-1][1].append(word)
            for after_role, group in groups:
                while group and group[-1] in _SURNAME_PARTICLES:
                    group.pop()
                capitalized = [word for word in group if word not in _SURNAME_PARTICLES]
                if (
                    not 2 <= len(capitalized) <= 4
                    or not group[0][:1].isupper()
                    or not all(_capitalized(word) for word in capitalized)
                    or any(word.casefold() in _INSTITUTION_WORDS for word in group)
                ):
                    continue
                name = " ".join(group)
                if after_role:
                    titled.add(name)
                if name.casefold() in covered or name in counts:
                    continue
                mentions = len(mentions_in(spoken, person_aliases(PersonDraft(name=name))))
                if mentions:
                    counts[name] = mentions
    full_aliases = {alias.casefold() for name in counts for alias in person_aliases(PersonDraft(name=name))}
    for text in [*narration, *evidence]:
        for match in _SURNAME_CONTEXT.finditer(text):
            surname = match.group("titled") or match.group("governing")
            before = text[: match.start()].split()[-1:]
            if (
                match.group("governing")
                and before
                and before[0][:1].isupper()
                and before[0].casefold() not in _TITLE_WORDS
            ):
                continue  # "White House administration" is an institution, not a surname.
            folded = surname.casefold()
            if folded in covered or folded in _TITLE_WORDS or surname in counts or folded in full_aliases:
                continue
            # A bare surname only counts with a role or government context ("President X", "the X administration").
            mentions = len(mentions_in(spoken, (surname,)))
            if mentions:
                counts[surname] = mentions
                titled.add(surname)
    folded_names = [name.casefold() for name in counts]
    for name in list(counts):
        if any(other.endswith(" " + name.casefold()) for other in folded_names):
            del counts[name]  # "Von der Leyen" is the tail of "Ursula von der Leyen".
    ranked = sorted(counts, key=lambda name: (-counts[name], name not in titled, -len(name.split())))
    return ranked[:MAX_NAME_CANDIDATES]
