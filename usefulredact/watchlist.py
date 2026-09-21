"""The optional watchlist: names a person wants checked for, by exact and fuzzy match.

A watchlist is what the user types or pastes for one run. Nothing is stored.

For each entry, in falling order of certainty:
  exact        the whole entry, on word boundaries, any case
  fuzzy        the whole entry within OCR noise ("Benjamin Sampleton" ~ "Benjamln Samplcton")
  part         one word of a multi-word entry on its own ("Sampleton")
  fuzzy part   one word within OCR noise, for words of five letters or more
  short form   a capitalised word of three letters or more that starts a word of the
               entry ("Ben" for "Benjamin"); the weakest signal, and scored as such
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from rapidfuzz import fuzz

from usefulredact.detectors import Match

FUZZY_FULL_MIN = 85.0
FUZZY_PART_MIN = 84.0
FUZZY_PART_MIN_LEN = 5
FUZZY_LENGTH_SLACK = (
    2  # OCR drops or adds a character or two; a word three letters longer is another word
)
PART_MIN_LEN = 3
SHORT_FORM_MIN_LEN = 3

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
# Short capitalised words that start many names but are not short forms of them.
_NOT_A_SHORT_FORM = frozenset(
    "jan feb mar apr may jun jul aug sep sept oct nov dec mon tue wed thu fri sat sun "
    "the and for but not you all any can her his our out she was who per due "
    "mr mrs ms miss dr st rd ave".split()
)


def parse(raw: str | list[str] | None) -> list[str]:
    """One entry per line (or per item); blanks and duplicates dropped."""
    if not raw:
        return []
    lines = raw.splitlines() if isinstance(raw, str) else raw
    seen: set[str] = set()
    entries = []
    for line in lines:
        entry = " ".join(str(line).split())
        if len(entry) >= 2 and entry.lower() not in seen:
            seen.add(entry.lower())
            entries.append(entry)
    return entries


def find_watchlist(text: str, entries: list[str]) -> Iterator[Match]:
    if not entries or not text.strip():
        return
    words = [(m.group(0), m.start(), m.end()) for m in _WORD.finditer(text)]
    taken: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return not any(s < end and e > start for s, e in taken)

    def claim(start: int, end: int, detail: str, score: float) -> Match:
        taken.append((start, end))
        return Match(start, end, "watchlist", detail=detail, score=score)

    for entry in entries:
        pattern = re.compile(
            r"(?<!\w)" + r"\s+".join(map(re.escape, entry.split())) + r"(?!\w)", re.I
        )
        for m in pattern.finditer(text):
            if free(m.start(), m.end()):
                yield claim(m.start(), m.end(), f"watchlist entry '{entry}'", 100.0)

    for entry in entries:
        parts = _WORD.findall(entry)
        n = len(parts)
        if n == 0:
            continue
        target = " ".join(parts).lower()
        # The whole entry, within OCR noise: compare every run of n words.
        for i in range(len(words) - n + 1):
            start, end = words[i][1], words[i + n - 1][2]
            if "\n" in text[start:end] or not free(start, end):
                continue
            candidate = " ".join(w[0] for w in words[i : i + n]).lower()
            if abs(len(candidate) - len(target)) > FUZZY_LENGTH_SLACK:
                continue
            score = fuzz.ratio(candidate, target)
            if score >= FUZZY_FULL_MIN and len(target) >= FUZZY_PART_MIN_LEN:
                yield claim(start, end, f"close to watchlist entry '{entry}'", score)
        if n < 2:
            continue
        # A shortened name: one word of the entry on its own.
        for word, start, end in words:
            if not free(start, end) or len(word) < PART_MIN_LEN:
                continue
            low = word.lower()
            for part in parts:
                p = part.lower()
                if len(p) < PART_MIN_LEN:
                    continue
                if low == p:
                    yield claim(start, end, f"part of watchlist entry '{entry}'", 95.0)
                    break
                if (
                    len(p) >= FUZZY_PART_MIN_LEN
                    and len(low) >= FUZZY_PART_MIN_LEN
                    and abs(len(p) - len(low)) <= FUZZY_LENGTH_SLACK
                ):
                    score = fuzz.ratio(low, p)
                    if score >= FUZZY_PART_MIN:
                        yield claim(
                            start, end, f"close to part of watchlist entry '{entry}'", score
                        )
                        break
                if (
                    word[0].isupper()
                    and SHORT_FORM_MIN_LEN <= len(low) < len(p)
                    and p.startswith(low)
                    and low not in _NOT_A_SHORT_FORM
                ):
                    yield claim(start, end, f"possible short form of '{part}' ('{entry}')", 70.0)
                    break
