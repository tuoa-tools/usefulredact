"""Spans to boxes, the report files, and the corpus generator's guarantees."""

from __future__ import annotations

import csv
import io
import json

from usefulredact import corpus, report
from usefulredact.detectors import medicare_valid, tfn_valid
from usefulredact.models import DocResult, Finding, PageInfo
from usefulredact.ocr import OcrRegion
from usefulredact.pagetext import PageText


def quad(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_words_become_lines_and_spans_map_back_to_boxes():
    words = [
        (10, 10, 40, 20, "Dear", 0, 0, 0),
        (45, 10, 80, 20, "Kylie", 0, 0, 1),
        (10, 30, 60, 40, "Nguyen,", 0, 1, 0),
    ]
    page = PageText.from_words(words)
    assert page.text == "Dear Kylie\nNguyen,"
    start = page.text.index("Kylie")
    boxes = page.boxes_for_span(start, start + len("Kylie\nNguyen"))
    assert boxes == [(45.0, 10.0, 80.0, 20.0), (10.0, 30.0, 60.0, 40.0)]  # one box per line


def test_ocr_regions_on_one_row_join_and_a_span_takes_its_share():
    regions = [
        OcrRegion("Date of birth:", 0.99, quad(100, 100, 300, 130)),
        OcrRegion("14/03/1985", 0.98, quad(320, 102, 520, 132)),
        OcrRegion("Next line", 0.97, quad(100, 160, 260, 190)),
    ]
    page = PageText.from_ocr_regions(regions, scale=0.5)
    assert page.text == "Date of birth: 14/03/1985\nNext line"
    start = page.text.index("03")
    (box,) = page.boxes_for_span(start, start + 2)
    assert 160 < box[0] < box[2] < 260 and box[1] == 51.0  # inside the second region, scaled


def test_reports_have_the_same_documents_and_findings():
    result = DocResult(
        path="a.pdf",
        pages=[PageInfo(1, 595, 842, "text_layer")],
        findings=[Finding(1, "pi", "email", "k@example.com", (1, 2, 3, 4), [(1, 2, 3, 4)])],
    )
    clean = DocResult(path="b.pdf", pages=[PageInfo(1, 595, 842, "text_layer")])
    payload = json.loads(report.to_json([clean, result]))
    assert [d["verdict"] for d in payload["documents"]] == ["PI_VISIBLE", "NO_ISSUES_FOUND"]
    assert "not a guarantee" in payload["notice"]
    docs = list(csv.DictReader(io.StringIO(report.documents_csv([clean, result]))))
    assert docs[0]["file"] == "a.pdf" and docs[0]["pi"] == "1"
    rows = list(csv.DictReader(io.StringIO(report.findings_csv([clean, result]))))
    assert len(rows) == 1 and rows[0]["detector"] == "email" and rows[0]["x1"] == "3"


def test_corpus_is_deterministic_and_labelled(tmp_path):
    a = corpus.generate(10, 99, tmp_path / "a")
    b = corpus.generate(10, 99, tmp_path / "b")
    names = sorted(p.name for p in a.iterdir())
    assert names == sorted(p.name for p in b.iterdir()) and len(names) == 13
    for name in names:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    labels = list(csv.DictReader(open(a / "labels.csv", encoding="utf-8")))
    assert [r["method"] for r in labels] == list(corpus.METHODS)
    control = next(r["file"] for r in labels if r["method"] == "m7_control")
    items = list(csv.DictReader(open(a / "pi_items.csv", encoding="utf-8")))
    assert not [i for i in items if i["file"] == control]  # a control holds no PI at all


def test_generated_numbers_pass_and_fail_their_checksums():
    import random

    rng = random.Random(3)
    for _ in range(50):
        assert medicare_valid(corpus.medicare_number(rng).replace(" ", ""))
        assert tfn_valid(corpus.tfn_number(rng).replace(" ", ""))
        assert not tfn_valid(corpus.reference_number(rng).replace(" ", ""))


def test_look_alikes_are_stratified_and_dates_do_not_move():
    from usefulredact.corpus import TODAY, Traits

    six = [Traits.for_position(i) for i in range(6)]
    assert sum(t.sender_street for t in six) == 2
    assert sum(t.sender_landline for t in six) == 1
    assert sum(t.firm_named_after_people for t in six) == 1
    assert not any(t.sender_street and t.sender_landline for t in six)
    assert TODAY.year == 2026  # a constant, never date.today()
