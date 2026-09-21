"""Named-entity recognition with spaCy's small English model (statistical, CPU, local).

PERSON is personal information. GPE and LOC (countries, cities, regions, places)
are context: shown and exported, but a place name alone does not change a verdict.

The model is `en_core_web_sm`, installed as a wheel alongside the package, so it
loads from disk and nothing is fetched at run time. It is a small model: it
misses names, more so in forms and OCR text than in prose. The labelled-name
rule below covers the commonest gap, and the evaluation reports what is left.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator

from rapidfuzz import fuzz

from usefulredact.detectors import Match
from usefulredact.models import CONTEXT, PI

MODEL = "en_core_web_sm"
PLACE_FUZZY_MIN = 88.0  # how close to a known place name an OCR misreading may be
PLACE_FUZZY_MIN_LEN = 6

_nlp = None
_load_error: str | None = None
_lock = threading.Lock()


def available() -> bool:
    """Load the model on first call. False (never raises) if it can't."""
    global _nlp, _load_error
    if _nlp is not None:
        return True
    if _load_error is not None:
        return False
    with _lock:
        if _nlp is not None:
            return True
        try:
            import spacy

            _nlp = spacy.load(MODEL, disable=["tagger", "parser", "attribute_ruler", "lemmatizer"])
            return True
        except Exception as exc:  # not installed, or the model did not load
            _load_error = repr(exc)
            return False


def load_error() -> str | None:
    return _load_error


# Words the model sometimes takes for a person in forms and letterheads.
_NOT_A_NAME = frozenset(
    "dob medicare tfn abn acn phone mobile email fax address name date signature signed ref "
    "reference invoice account customer applicant patient tenant member resident sir madam "
    "dear regards sincerely yours team department office pty ltd limited inc".split()
)
# A "person" with one of these words in it is an organisation the model misread.
_ORGANISATION_WORDS = frozenset(
    "water energy power gas electricity council shire city bank credit union insurance health "
    "medical clinic hospital dental pharmacy university college school institute academy "
    "services service solutions group holdings partners associates company corporation "
    "centre center agency authority commission board trust foundation society association "
    "club church network systems technologies consulting management properties realty "
    "transport logistics airlines telecom mobile internet library museum".split()
)
# The small model often reads an Australian place name as a person ("our Perth office").
# An entity made only of these words is a place, whatever label the model gave it.
_PLACES = frozenset(
    "australia nsw vic qld sa wa tas nt act victoria queensland tasmania new south wales western "
    "northern territory capital sydney melbourne brisbane perth adelaide hobart darwin canberra "
    "newcastle wollongong geelong townsville cairns toowoomba ballarat bendigo launceston mackay "
    "rockhampton bunbury bundaberg wagga mildura shepparton gladstone tamworth orange dubbo "
    "geraldton kalgoorlie albury wodonga devonport burnie warrnambool traralgon nowra bathurst "
    "lismore armidale goulburn fremantle parramatta penrith gosford frankston dandenong ipswich "
    "logan mandurah broome karratha whyalla gold coast sunshine alice springs mount gambier port "
    "macquarie coffs harbour hervey bay".split()
)
_NAME_SHAPE = re.compile(r"^[A-Za-z][A-Za-z'’.-]*(?: [A-Za-z][A-Za-z'’.-]*){0,4}$")


def _plausible_person(text: str) -> bool:
    if not _NAME_SHAPE.match(text) or not any(len(w) >= 3 for w in text.split()):
        return False
    words = [w.strip(".").lower() for w in text.split()]
    if any(w in _NOT_A_NAME or w in _ORGANISATION_WORDS for w in words):
        return False
    return text != text.lower()


def _is_place(text: str) -> bool:
    """Every word is a place name, or within an OCR misreading of one ("Neweastle")."""
    words = [w.strip(".,").lower() for w in text.split()]
    return bool(words) and all(w in _PLACES or _near_place(w) for w in words)


def _near_place(word: str) -> bool:
    if len(word) < PLACE_FUZZY_MIN_LEN:
        return False
    return any(
        abs(len(place) - len(word)) <= 1 and fuzz.ratio(word, place) >= PLACE_FUZZY_MIN
        for place in _PLACES
        if len(place) >= PLACE_FUZZY_MIN_LEN
    )


def find_entities(text: str) -> Iterator[Match]:
    if not text.strip() or not available():
        return
    for ent in _nlp(text).ents:
        if ent.label_ == "PERSON" and _is_place(ent.text.split("\n", 1)[0]):
            yield Match(
                ent.start_char,
                ent.start_char + len(ent.text.split("\n", 1)[0]),
                "ner_gpe",
                CONTEXT,
                "a known place name (the model read it as a person)",
            )
        elif ent.label_ == "PERSON":
            # The model often runs a name on into the next line; keep the first line.
            first_line = ent.text.split("\n", 1)[0].strip()
            if _plausible_person(first_line):
                start = ent.start_char + ent.text.index(first_line)
                yield Match(start, start + len(first_line), "ner_person", PI, "spaCy PERSON")
        elif ent.label_ in ("GPE", "LOC"):
            name = ent.text.strip()
            if len(name) >= 3 and "\n" not in name and not any(c.isdigit() for c in name):
                yield Match(
                    ent.start_char,
                    ent.end_char,
                    f"ner_{ent.label_.lower()}",
                    CONTEXT,
                    f"spaCy {ent.label_}: a place name, not personal information on its own",
                )


# ------------------------------------------------------------- labelled names
# "Name: Kylie Nguyen", "Dear Mr Tran": the label says a name follows, which a rule
# reads more reliably than a small statistical model reads a form.
_TITLE = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?"
# One word of a name: Kylie, McDonald, O'Neil, Mary-Anne, D'Angelo.
_NAME_WORD = r"(?:[A-Z][a-z]+(?:[A-Z][a-z]+)?|[A-Z])(?:['’-][A-Z]?[a-z]+)*"
_NAME = rf"{_NAME_WORD}(?:[ ]{_NAME_WORD}){{0,3}}"
LABELLED_NAME = re.compile(
    r"(?:\b(?:Full[ ]name|Name|Patient|Applicant|Tenant|Account[ ]holder|Card[ ]holder|"
    r"Policy[ ]holder|Employee|Contact[ ]person|Next[ ]of[ ]kin|Guardian|Attention|Attn)"
    r"[ ]?(?:name)?[ ]?[:\-][ ]*|\bDear[ ]+)"
    rf"((?:{_TITLE}[ ]+)?{_NAME})"
)
_GENERIC_ADDRESSEE = frozenset(
    "customer sir madam resident member applicant tenant patient colleague colleagues team "
    "parent parents guardian guardians valued client clients friend friends all everyone "
    "householder occupant owner supporter subscriber".split()
)


def find_labelled_names(text: str) -> Iterator[Match]:
    for m in LABELLED_NAME.finditer(text):
        words = [w.strip(".").lower() for w in m.group(1).split()]
        if any(w in _GENERIC_ADDRESSEE or w in _NOT_A_NAME for w in words):
            continue
        if not any(len(w) >= 3 for w in words):  # "Name: A" is a form's option, not a name
            continue
        yield Match(m.start(1), m.end(1), "name_label", PI, "a name beside a label or greeting")
