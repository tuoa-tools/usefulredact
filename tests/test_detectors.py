"""Rule-based detectors: checksums valid and invalid, and the edges of each pattern."""

from __future__ import annotations

import pytest

from usefulredact import detectors
from usefulredact.models import CONTEXT, PI


def found(text: str, detector: str, kind: str = PI) -> list[str]:
    return [
        text[m.start : m.end]
        for m in detectors.find_all(text)
        if m.detector == detector and m.kind == kind
    ]


# ------------------------------------------------------------------ checksums
@pytest.mark.parametrize("number", ["2123456701", "21234567011", "6123456741"])
def test_medicare_checksum_accepts_valid(number):
    assert detectors.medicare_valid(number)


@pytest.mark.parametrize(
    "number",
    [
        "2123456711",  # check digit wrong
        "1123456701",  # first digit must be 2 to 6
        "7123456701",
        "212345670",  # too short
        "21234567AB",
    ],
)
def test_medicare_checksum_rejects_invalid(number):
    assert not detectors.medicare_valid(number)


@pytest.mark.parametrize("number", ["123456782", "876543210"])
def test_tfn_checksum_accepts_valid(number):
    assert detectors.tfn_valid(number)


@pytest.mark.parametrize("number", ["123456789", "12345678", "1234567820", "12345678X"])
def test_tfn_checksum_rejects_invalid(number):
    assert not detectors.tfn_valid(number)


def test_medicare_in_text_needs_the_checksum():
    assert found("Medicare: 2123 45670 1", "medicare") == ["2123 45670 1"]
    assert found("Medicare: 2123456701", "medicare") == ["2123456701"]
    assert found("Medicare: 2123 45671 1", "medicare") == []


def test_tfn_in_text_needs_the_checksum():
    assert found("TFN 123 456 782", "tfn") == ["123 456 782"]
    assert found("Reference 481 220 337", "tfn") == []  # nine digits, fails the checksum


def test_a_number_is_not_offered_twice():
    # a mobile holds nine-digit runs, and so does a Medicare number
    text = "Mobile 0412 345 678, Medicare 2123 45670 1"
    assert found(text, "tfn") == []
    assert found(text, "phone_au") == ["0412 345 678"]
    assert found(text, "medicare") == ["2123 45670 1"]


# ---------------------------------------------------------------------- email
def test_email():
    assert found("write to kylie.nguyen85@mailbox.example today", "email") == [
        "kylie.nguyen85@mailbox.example"
    ]
    assert found("no at-sign here: kylie.nguyen.mailbox.example", "email") == []


def test_shared_mailbox_is_context():
    text = "Contact enquiries@harbourline.example"
    assert found(text, "email") == []
    assert found(text, "email", CONTEXT) == ["enquiries@harbourline.example"]


# ---------------------------------------------------------------------- phone
@pytest.mark.parametrize(
    "number",
    [
        "0412 345 678",
        "0412345678",
        "+61 412 345 678",
        "+61.412.345.678",
        "(03) 9123 4567",
        "(03)9123 4567",
        "03 9123 4567",
        "+61 3 9123 4567",
    ],
)
def test_phone_formats(number):
    assert found(f"Call {number} after five.", "phone_au") == [number]


def test_organisation_numbers_and_bare_digits_are_left_alone():
    assert found("Call 1300 555 010 or 13 22 58.", "phone_au") == []
    assert found("Invoice 9123 4567 is overdue.", "phone_au") == []


def test_local_number_counts_beside_a_phone_label():
    assert found("Phone: 9123 4567", "phone_au") == ["9123 4567"]


# ------------------------------------------------------------------------ dob
@pytest.mark.parametrize(
    "text, date",
    [
        ("Date of birth: 14/03/1985", "14/03/1985"),
        ("DOB 14-03-85", "14-03-85"),
        ("D.O.B.: 1985-03-14", "1985-03-14"),
        ("She was born on 14 March 1985 in Geelong.", "14 March 1985"),
        ("Birth date: March 14, 1985", "March 14, 1985"),
    ],
)
def test_dob_needs_its_label(text, date):
    assert found(text, "dob") == [date]


def test_a_date_without_a_birth_label_is_not_pi():
    assert found("Issued: 2 June 2026. Due 30/06/2026.", "dob") == []


# -------------------------------------------------------------------- address
def test_street_address_takes_its_locality():
    text = "Address: 17 Kennedy Street, Richmond VIC 3121"
    assert found(text, "address_au") == ["17 Kennedy Street, Richmond VIC 3121"]


def test_address_across_two_lines_and_with_a_unit():
    text = "Unit 7, 50 Miller Grove\nJohnsonland QLD 2688"
    assert found(text, "address_au") == [text]
    assert found("4/8 Patrick Road", "address_au") == ["4/8 Patrick Road"]


def test_rare_street_type_is_found_by_shape():
    text = "17 Kennedy Laneway\nEast Tony, VIC, 2609"
    assert found(text, "address_au") == [text]


def test_locality_alone_is_context():
    text = "PO Box 410, Melbourne VIC 3001"
    assert found(text, "address_au") == []
    assert found(text, "locality_au", CONTEXT) == ["Melbourne VIC 3001"]


def test_ordinary_sentences_are_not_addresses():
    assert found("We sent 3 Reminders in May and 12 Monthly statements.", "address_au") == []
