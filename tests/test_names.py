"""Names: the labelled-name rule, the spaCy model's filters, and the watchlist."""

from __future__ import annotations

import pytest

from usefulredact import ner
from usefulredact.models import CONTEXT, PI
from usefulredact.watchlist import find_watchlist, parse


def labelled(text: str) -> list[str]:
    return [text[m.start : m.end] for m in ner.find_labelled_names(text)]


def test_name_beside_a_label_or_greeting():
    assert labelled("Full name: Kylie Nguyen") == ["Kylie Nguyen"]
    assert labelled("Dear Dr Tran,") == ["Dr Tran"]
    assert labelled("Patient: Mary-Anne O'Neil") == ["Mary-Anne O'Neil"]


@pytest.mark.parametrize("text", ["Dear Customer,", "Dear Sir or Madam", "Full name: ________"])
def test_generic_addressee_is_not_a_name(text):
    assert labelled(text) == []


def test_model_finds_a_name_in_prose():
    assert ner.available(), ner.load_error()
    text = "We confirm that Benjamin Sampleton has held an account with us since 2019."
    people = [text[m.start : m.end] for m in ner.find_entities(text) if m.kind == PI]
    assert "Benjamin Sampleton" in people


def test_place_names_are_context_whatever_the_model_called_them():
    text = "Payments can be made at any Perth branch or at our Hobart office in Tasmania."
    matches = list(ner.find_entities(text))
    assert [m for m in matches if m.kind == PI] == []
    assert all(m.kind == CONTEXT for m in matches)


def test_is_place_needs_every_word_to_be_one():
    assert ner._is_place("Hobart SA")
    assert not ner._is_place("Sydney Smith")  # a person with a city's name


def test_ocr_misspelt_place_is_still_a_place():
    assert ner._is_place("Neweastle")  # Newcastle, as OCR read it
    assert not ner._is_place("Sidney")  # a name, and too far from Sydney


def test_organisations_are_not_people():
    assert not ner._plausible_person("Harbourline Water")
    assert ner._plausible_person("Kylie Nguyen")


# ------------------------------------------------------------------ watchlist
def hits(text: str, entries: list[str]) -> list[tuple[str, float]]:
    return [(text[m.start : m.end], m.score) for m in find_watchlist(text, entries)]


def test_watchlist_parse_drops_blanks_and_duplicates():
    assert parse("Benjamin Sampleton\n\n  benjamin   sampleton \nKylie") == [
        "Benjamin Sampleton",
        "Kylie",
    ]


def test_watchlist_exact_is_case_blind_and_on_word_boundaries():
    assert hits("re: BENJAMIN SAMPLETON (file 3)", ["Benjamin Sampleton"]) == [
        ("BENJAMIN SAMPLETON", 100.0)
    ]
    # inside a longer word it is not an exact match, only a close one
    assert hits("the Sampletons were out", ["Sampleton Jones"]) == [
        ("Sampletons", pytest.approx(94.7, abs=0.1))
    ]
    assert hits("an unsampletonian file", ["Sampleton Jones"]) == []


def test_watchlist_survives_ocr_noise():
    found = hits("Applicant: Benjamln Samplcton", ["Benjamin Sampleton"])
    assert [text for text, _ in found] == ["Benjamln Samplcton"]
    assert 85 <= found[0][1] < 100


def test_watchlist_finds_a_shortened_name():
    assert [t for t, _ in hits("Please call Sampleton today.", ["Benjamin Sampleton"])] == [
        "Sampleton"
    ]
    short = hits("Thanks, Ben", ["Benjamin Sampleton"])
    assert short == [("Ben", 70.0)]  # the weakest signal, scored as such


def test_month_is_not_a_short_form():
    assert hits("Due 3 Mar 2026", ["Margaret Marlow"]) == []
