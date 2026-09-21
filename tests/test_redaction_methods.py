"""One generated document per redaction method: does the checker reach the right verdict,
for the right reason? Plus the look-alikes that must not be flagged."""

from __future__ import annotations

import pymupdf
import pytest

from usefulredact import corpus
from usefulredact.models import (
    CONTEXT,
    FAIL_RECOVERABLE,
    LOW_CONFIDENCE,
    NO_ISSUES_FOUND,
    NOT_CHECKED,
    PI,
    PI_VISIBLE,
    RECOVERABLE,
    REVIEW_LOW_CONFIDENCE,
)
from usefulredact.pipeline import check_document

LINES = [
    "Dear Kylie Nguyen,",
    "Date of birth: 14/03/1985",
    "Email: kylie.nguyen85@mailbox.example",
    "Your account was reviewed on 2 June 2026. Reference 481 220 337.",
]
SECRETS = ["Kylie Nguyen", "14/03/1985", "kylie.nguyen85@mailbox.example"]


def page_with_lines():
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(LINES):
        page.insert_text((72, 100 + 22 * i), line, fontsize=11)
    rects = [r + (-1, -1, 1, 1) for s in SECRETS for r in page.search_for(s)]
    return doc, page, rects


def detectors_of(result, kind):
    return {f.detector for f in result.findings if f.kind == kind}


@pytest.mark.parametrize("method", list(corpus.METHODS))
def test_each_method_reaches_its_expected_verdict(method, checked):
    result = checked[method]
    sender_only = {"address_au", "phone_au", "ner_person"}  # the letterhead's own details
    if method in corpus.CONTROLS and result.verdict != NO_ISSUES_FOUND:
        assert detectors_of(result, PI) <= sender_only, result.to_dict()
        assert not detectors_of(result, RECOVERABLE)
        return
    assert result.verdict == corpus.METHODS[method][0], result.to_dict()


def test_recovered_text_is_reported_with_what_it_holds(made, checked):
    _, letter = made["m3_drawn_box"]
    result = checked["m3_drawn_box"]
    recovered = " ".join(f.text for f in result.findings if f.kind == RECOVERABLE)
    for item in letter.items:
        assert item.value.split()[-1] in recovered
    assert detectors_of(result, RECOVERABLE) == {"drawn_shape"}
    assert any("holds: " in f.detail for f in result.findings if f.kind == RECOVERABLE)
    assert all(f.bbox and f.boxes for f in result.findings if f.kind == RECOVERABLE)


@pytest.mark.parametrize(
    "method, detector",
    [
        ("m3_drawn_box", "drawn_shape"),
        ("m8_pasted_image", "pasted_image"),
    ],
)
def test_the_mark_is_named(method, detector, checked):
    assert detector in detectors_of(checked[method], RECOVERABLE)


def test_properly_redacted_text_is_gone(made, checked):
    path, letter = made["m2_proper"]
    with pymupdf.open(path) as doc:
        text = doc[0].get_text()
    assert not any(item.value in text for item in letter.items)
    assert not detectors_of(checked["m2_proper"], RECOVERABLE)


def test_annotation_variants(tmp_path):
    variants = (
        ("filled_square", "annotation"),
        ("unapplied_redaction", "unapplied_redaction"),
    )
    for variant, detector in variants:
        doc, page, rects = page_with_lines()
        for rect in rects:
            if variant == "unapplied_redaction":
                page.add_redact_annot(rect, fill=(0, 0, 0))
            else:
                annot = page.add_rect_annot(rect)
                annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
                annot.update()
        path = tmp_path / f"{variant}.pdf"
        doc.save(path)
        result = check_document(path)
        assert result.verdict == FAIL_RECOVERABLE
        assert detectors_of(result, RECOVERABLE) == {detector}


def test_see_through_variants(tmp_path):
    doc, page, rects = page_with_lines()
    for rect in rects:
        page.draw_rect(rect, color=None, fill=(0, 0, 0), fill_opacity=0.6)
    doc.save(tmp_path / "fill.pdf")
    doc, page, rects = page_with_lines()
    for rect in rects:
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=(0.08, 0.08, 0.08))
        annot.set_opacity(0.7)
        annot.update()
    doc.save(tmp_path / "highlight.pdf")
    assert detectors_of(check_document(tmp_path / "fill.pdf"), RECOVERABLE) == {"see_through_shape"}
    assert detectors_of(check_document(tmp_path / "highlight.pdf"), RECOVERABLE) == {
        "see_through_annotation"
    }


def test_white_box_and_white_text_are_caught(tmp_path):
    doc, page, rects = page_with_lines()
    for rect in rects:
        page.draw_rect(rect, color=None, fill=(1, 1, 1))
    doc.save(tmp_path / "white_box.pdf")
    assert check_document(tmp_path / "white_box.pdf").verdict == FAIL_RECOVERABLE

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Nothing to see in this notice about billing periods.", fontsize=11)
    page.insert_text((72, 130), "Kylie Nguyen 0412 345 678", fontsize=11, color=(1, 1, 1))
    doc.save(tmp_path / "white_text.pdf")
    result = check_document(tmp_path / "white_text.pdf")
    assert result.verdict == FAIL_RECOVERABLE
    assert detectors_of(result, RECOVERABLE) == {"hidden_text"}


def test_look_alikes_are_not_redaction(tmp_path):
    """White text on a dark banner, text on a tinted cell, a yellow highlight, a boxed word."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(0, 0, 595, 70), color=None, fill=(0.12, 0.17, 0.30))
    page.insert_text((72, 42), "Harbourline Water  -  Account notice", fontsize=16, color=(1, 1, 1))
    page.draw_rect(pymupdf.Rect(60, 96, 540, 118), color=None, fill=(0.9, 0.92, 0.95))
    page.insert_text((72, 111), "Billing periods change from 1 July 2026.", fontsize=11)
    page.insert_text((72, 150), "No action is needed. Reference 481 220 337.", fontsize=11)
    for rect in page.search_for("No action is needed"):
        page.add_highlight_annot(rect).update()
    for rect in page.search_for("Reference"):
        box = page.add_rect_annot(rect + (-2, -2, 2, 2))
        box.set_colors(stroke=(1, 0, 0))
        box.update()
    doc.save(tmp_path / "look_alikes.pdf")
    result = check_document(tmp_path / "look_alikes.pdf")
    assert result.verdict == NO_ISSUES_FOUND, result.to_dict()


def test_metadata_and_form_fields_are_read(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(
        (72, 100), "General notice about billing periods and opening hours.", fontsize=11
    )
    widget = pymupdf.Widget()
    widget.field_name = "contact"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(72, 130, 300, 150)
    widget.field_value = "kylie.nguyen85@mailbox.example"
    page.add_widget(widget)
    doc.set_metadata({"author": "Kylie Nguyen", "title": "Notice", "keywords": "0412 345 678"})
    doc.save(tmp_path / "meta.pdf")
    result = check_document(tmp_path / "meta.pdf")
    assert result.verdict == PI_VISIBLE
    by_source = {(f.source, f.detector) for f in result.findings if f.kind == PI}
    assert ("form_field", "email") in by_source
    assert ("metadata", "phone_au") in by_source
    assert any(
        f.detector == "metadata_author" and f.kind == CONTEXT for f in result.findings
    ) or any(f.source == "metadata" and f.text == "Kylie Nguyen" for f in result.findings)


def test_watchlist_and_ignore_list(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(
        (72, 100), "The Sampleton matter was closed. Call (03) 9123 4567.", fontsize=11
    )
    doc.save(tmp_path / "w.pdf")
    plain = check_document(tmp_path / "w.pdf")
    assert "phone_au" in detectors_of(plain, PI) and "watchlist" not in detectors_of(plain, PI)
    watched = check_document(tmp_path / "w.pdf", watchlist=["Benjamin Sampleton"])
    assert "watchlist" in detectors_of(watched, PI)  # a surname alone is a shortened name
    partly = check_document(tmp_path / "w.pdf", use_ner=False, ignore="(03)9123 4567")
    assert partly.verdict == NO_ISSUES_FOUND  # spacing does not have to match
    eased = check_document(tmp_path / "w.pdf", ignore="(03) 9123 4567\nSampleton")
    assert eased.verdict == NO_ISSUES_FOUND


def test_scan_findings_carry_boxes_in_page_units(made, checked):
    result = checked["m6_scan_marker_60"]
    page = result.pages[0]
    assert page.source == "ocr" and page.ocr_regions > 0
    found = [f for f in result.findings if f.kind == PI]
    assert found
    for f in found:
        assert f.bbox and 0 <= f.bbox[0] < f.bbox[2] <= page.width + 1
        assert 0 <= f.bbox[1] < f.bbox[3] <= page.height + 1


def test_unreadable_files_are_not_a_pass(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.7 not really")
    (tmp_path / "notes.docx").write_bytes(b"PK")
    assert check_document(tmp_path / "broken.pdf").verdict == NOT_CHECKED
    assert check_document(tmp_path / "notes.docx").verdict == NOT_CHECKED

    doc, _, _ = page_with_lines()
    doc.save(tmp_path / "locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    locked = check_document(tmp_path / "locked.pdf")
    assert locked.verdict == NOT_CHECKED and "password" in locked.error


def test_a_page_the_engine_cannot_read_asks_for_a_human(tmp_path):
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(5)
    noise = rng.integers(0, 255, (600, 800), dtype=np.uint8)
    Image.fromarray(noise).save(tmp_path / "static.png")
    result = check_document(tmp_path / "static.png")
    # Static has nothing to read. Whatever the engine makes of it, the verdict must not be
    # one that claims PI, and a low-confidence verdict must come with its finding.
    assert result.verdict in (REVIEW_LOW_CONFIDENCE, NO_ISSUES_FOUND)
    if result.verdict == REVIEW_LOW_CONFIDENCE:
        assert any(f.kind == LOW_CONFIDENCE for f in result.findings)
