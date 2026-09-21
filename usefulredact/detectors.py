"""Rule-based PI detectors: regular expressions, two checksums and some context.

Every detector takes a string and yields Match(start, end, detector, kind, ...).
They know nothing about pages or boxes; pipeline.py maps spans back to boxes.

Australian formats throughout. The checksums are the published ones:
  Medicare  weights 1,3,7,9,1,3,7,9 on the first 8 digits; sum mod 10 = 9th digit
  TFN       weights 1,4,3,7,5,8,6,9,10 on the 9 digits; sum mod 11 = 0
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from usefulredact.models import CONTEXT, PI


@dataclass
class Match:
    start: int
    end: int
    detector: str
    kind: str = PI
    detail: str = ""
    score: float | None = None


# --------------------------------------------------------------------- checksums
MEDICARE_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9)
TFN_WEIGHTS = (1, 4, 3, 7, 5, 8, 6, 9, 10)


def medicare_valid(digits: str) -> bool:
    """`digits` is the 10-digit card number (an 11th digit, the person's line on
    the card, may follow and is ignored). The first digit is 2 to 6."""
    if len(digits) not in (10, 11) or not digits.isdigit() or digits[0] not in "23456":
        return False
    total = sum(int(d) * w for d, w in zip(digits[:8], MEDICARE_WEIGHTS, strict=True))
    return total % 10 == int(digits[8])


def tfn_valid(digits: str) -> bool:
    if len(digits) != 9 or not digits.isdigit():
        return False
    return sum(int(d) * w for d, w in zip(digits, TFN_WEIGHTS, strict=True)) % 11 == 0


# ------------------------------------------------------------------------- email
EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

# A shared mailbox names a role, not a person. Reported as context.
ROLE_MAILBOXES = frozenset(
    "info admin enquiries enquiry inquiries accounts account support contact hello office "
    "reception noreply no-reply donotreply help service services sales billing team mail "
    "feedback customerservice customercare privacy hr careers media".split()
)


def find_emails(text: str) -> Iterator[Match]:
    for m in EMAIL.finditer(text):
        local = m.group(0).split("@", 1)[0].lower()
        if local in ROLE_MAILBOXES:
            yield Match(m.start(), m.end(), "email", CONTEXT, "shared mailbox, not a person's")
        else:
            yield Match(m.start(), m.end(), "email")


# ------------------------------------------------------------------------- phone
# Mobiles (04..) and landlines (02, 03, 07, 08), with or without +61 and brackets.
# 13/1300/1800 numbers belong to organisations and are left alone.
PHONE = re.compile(
    r"(?<![\d+])"
    r"(?:\+61[ .-]?(?:\(0\)[ -]?)?[23478]|\(0[23478]\)|0[23478])"
    r"(?:[ .-]?\d){8}"
    r"(?!\d)"
)
# A local number with no area code only counts beside a word that says it is one.
PHONE_LOCAL = re.compile(
    r"(?i)\b(?:ph|phone|tel|telephone|mobile|mob|contact|call|fax)\b[^0-9\n]{0,20}"
    r"(?<!\d)(\d{4}[ .-]?\d{4})(?!\d)"
)


def find_phones(text: str) -> Iterator[Match]:
    seen: list[tuple[int, int]] = []
    for m in PHONE.finditer(text):
        seen.append(m.span())
        yield Match(m.start(), m.end(), "phone_au")
    for m in PHONE_LOCAL.finditer(text):
        span = m.span(1)
        if not any(s < span[1] and e > span[0] for s, e in seen):
            yield Match(span[0], span[1], "phone_au", detail="local number beside a phone label")


# ----------------------------------------------------------------- date of birth
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE = (
    r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?[ ]+{_MONTH},?[ ]+\d{{4}}"
    rf"|{_MONTH}[ ]+\d{{1,2}}(?:st|nd|rd|th)?,?[ ]+\d{{4}})"
)
# A date is only personal information here when the words beside it say it is a birth date.
DOB = re.compile(
    r"(?i)\b(?:d\.?\s?o\.?\s?b\.?|date\s+of\s+birth|birth\s*date|birthday|born(?:\s+on)?)\b"
    rf"[^0-9A-Za-z\n]{{0,12}}(?:is\s+|was\s+|on\s+)?({_DATE})"
)


def find_dobs(text: str) -> Iterator[Match]:
    for m in DOB.finditer(text):
        yield Match(m.start(1), m.end(1), "dob", detail="date beside a date-of-birth label")


# ---------------------------------------------------------------------- Medicare
MEDICARE = re.compile(r"(?<![\d-])([2-6]\d{3})[ -]?(\d{5})[ -]?(\d)(?:[ /-]?(\d))?(?![\d-])")


def find_medicare(text: str) -> Iterator[Match]:
    for m in MEDICARE.finditer(text):
        digits = "".join(g for g in m.groups() if g)
        if medicare_valid(digits):
            yield Match(m.start(), m.end(), "medicare", detail="passes the Medicare checksum")


# --------------------------------------------------------------------------- TFN
TFN = re.compile(r"(?<![\d-])(?<!\d )(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?![ -]?\d)")
_TFN_LABEL = re.compile(r"(?i)\b(?:tfn|tax\s+file)\b")


def find_tfns(text: str) -> Iterator[Match]:
    for m in TFN.finditer(text):
        if not tfn_valid("".join(m.groups())):
            continue
        labelled = bool(_TFN_LABEL.search(text[max(0, m.start() - 40) : m.start()]))
        detail = "passes the TFN checksum" + (", beside a TFN label" if labelled else "")
        yield Match(m.start(), m.end(), "tfn", detail=detail)


# ----------------------------------------------------------------------- address
# The common street types. Rarer ones ("Rise", "Nook", "Wynd") double as ordinary words,
# so they are only accepted by shape: see STREET_BY_SHAPE.
_STREET_TYPES = (
    "Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Crescent|Cres|Place|Pl|Lane|Ln|"
    "Parade|Pde|Highway|Hwy|Boulevard|Blvd|Terrace|Tce|Close|Cl|Way|Grove|Gr|Circuit|Cct|"
    "Esplanade|Square|Sq|Walk|Mews|Promenade|Quay"
)
_UNIT = (
    r"(?:(?:Unit|Apt|Apartment|Flat|Suite|Shop|Level|Lvl|U)\.?[ ]?\d+[A-Za-z]?[ ,/]+"
    r"|\d+[A-Za-z]?[ ]?/[ ]?)?"
)
_NUMBER = r"\d{1,5}[A-Za-z]?(?:-\d{1,5})?"
_NAME_WORD = r"[A-Z][A-Za-z'’-]+"
_STATE = (
    r"(?:VIC|NSW|QLD|SA|WA|TAS|NT|ACT|Victoria|New South Wales|Queensland|South Australia|"
    r"Western Australia|Tasmania|Northern Territory|Australian Capital Territory)"
)
STREET = re.compile(rf"\b{_UNIT}{_NUMBER}[ ]+(?:{_NAME_WORD}[ ]+){{1,3}}(?:{_STREET_TYPES})\b\.?")
LOCALITY = re.compile(rf"\b(?:{_NAME_WORD}[ ,]+){{1,3}}{_STATE}[ ,]+\d{{4}}\b")
# A number and capitalised words with a locality straight after: an address by its shape,
# whatever the street type is called and however OCR spelt it.
STREET_BY_SHAPE = re.compile(
    rf"\b{_UNIT}{_NUMBER}[ ]+{_NAME_WORD}(?:[ ]+{_NAME_WORD}){{0,3}}[ ]*[,\n][ ]*"
    rf"(?:{_NAME_WORD}[ ,]+){{1,3}}{_STATE}[ ,]+\d{{4}}\b"
)
_PO_BOX = re.compile(r"(?i)\b(?:G\.?P\.?O\.?|P\.?O\.?|Locked)\s*(?:Box|Bag)\b")


def find_addresses(text: str) -> Iterator[Match]:
    """A street line is PI; when the suburb, state and postcode follow within a
    line or two they join the same finding. A locality on its own (or after a
    PO box) says where an organisation is, so it is context."""
    claimed: list[tuple[int, int]] = []
    for m in STREET.finditer(text):
        end = m.end()
        nearby = LOCALITY.search(text, end, min(len(text), end + 80))
        if nearby:
            gap = text[end : nearby.start()]
            if len(gap) <= 40 and gap.count("\n") <= 2 and not re.search(r"[.!?]\s", gap):
                end = nearby.end()
        claimed.append((m.start(), end))
        yield Match(m.start(), end, "address_au")
    for m in STREET_BY_SHAPE.finditer(text):
        if _PO_BOX.search(text[max(0, m.start() - 12) : m.start() + 4]):
            continue
        if not any(s < m.end() and e > m.start() for s, e in claimed):
            claimed.append(m.span())
            yield Match(m.start(), m.end(), "address_au", detail="address by its shape")
    for m in LOCALITY.finditer(text):
        if any(s <= m.start() < e for s, e in claimed):
            continue
        detail = "suburb, state and postcode with no street line"
        if _PO_BOX.search(text[max(0, m.start() - 40) : m.start()]):
            detail = "locality of a PO box"
        yield Match(m.start(), m.end(), "locality_au", CONTEXT, detail)


# --------------------------------------------------------------------------- all
def find_all(text: str) -> list[Match]:
    """Every rule-based match, with number clashes settled: a span already taken
    by a Medicare number or a phone number is not also offered as a TFN."""
    matches: list[Match] = []
    matches += find_emails(text)
    matches += find_dobs(text)
    matches += find_medicare(text)
    numeric = [m for m in matches if m.detector == "medicare"]
    for m in find_phones(text):
        if not _overlaps(m, numeric):
            matches.append(m)
            numeric.append(m)
    matches += [m for m in find_tfns(text) if not _overlaps(m, numeric)]
    matches += find_addresses(text)
    return sorted(matches, key=lambda m: (m.start, m.end))


def _overlaps(match: Match, others: list[Match]) -> bool:
    return any(o.start < match.end and o.end > match.start for o in others)
