# Evaluation report

usefulredact 0.1.0 on 60 synthetic documents (seed 42).

**Every document here is invented.** These figures describe how the checker behaves on the failure modes this corpus contains. They are not an accuracy claim about real documents, and 'no issues found' is never a guarantee.

## Document level: issue or no issue

An *issue* is any verdict other than `NO_ISSUES_FOUND`. The middle column is the same pipeline with each sender's own name, address and phone number on the ignore list, which is how the tool is meant to be used: it cannot tell an organisation's street address from a person's, so it flags both until told otherwise.

| | Full pipeline | Full pipeline, sender's details ignored | Baseline (text layer + regex) |
|---|---|---|---|
| Issues caught (true positives) | 42 | 42 | 30 |
| Issues missed (false negatives) | 0 | 0 | 12 |
| Clean documents flagged (false positives) | 10 | 0 | 6 |
| Clean documents passed (true negatives) | 8 | 18 | 12 |
| Recall | 100% | 100% | 71% |
| Precision | 81% | 100% | 83% |
| Specificity | 44% | 100% | 67% |
| Exact verdict | 50/60 (83%) | 60/60 (100%) | n/a: it has one answer |

## By redaction method

| Method | What was done | Expected | n | Full pipeline flagged | Exact verdict | Baseline flagged |
|---|---|---|---|---|---|---|
| `m1_none` | no redaction: the PI is in plain view | `PI_VISIBLE` | 6 | 6/6 | 6/6 | 6/6 |
| `m2_proper` | redaction annotations, applied: the text is gone | `NO_ISSUES_FOUND` | 6 | 3/6 | 3/6 | 3/6 |
| `m3_drawn_box` | black rectangle drawn over live text | `FAIL_RECOVERABLE` | 6 | 6/6 | 6/6 | 6/6 |
| `m4_annotation` | black annotation over live text, never applied | `FAIL_RECOVERABLE` | 6 | 6/6 | 6/6 | 6/6 |
| `m5_see_through` | dark see-through fill or highlight over live text | `FAIL_RECOVERABLE` | 6 | 6/6 | 6/6 | 6/6 |
| `m6_scan_marker_60` | scan, marker stroke at opacity 0.60: readable through it | `PI_VISIBLE` | 6 | 6/6 | 6/6 | 0/6 |
| `m6_scan_marker_85` | scan, marker stroke at opacity 0.85: readable with effort | `PI_VISIBLE` | 6 | 6/6 | 6/6 | 0/6 |
| `m6_scan_marker_100` | scan, marker stroke fully opaque: nothing to read | `NO_ISSUES_FOUND` | 6 | 3/6 | 3/6 | 0/6 |
| `m7_control` | control: the document never held any PI | `NO_ISSUES_FOUND` | 6 | 4/6 | 2/6 | 3/6 |
| `m8_pasted_image` | black image pasted over live text | `FAIL_RECOVERABLE` | 6 | 6/6 | 6/6 | 6/6 |

These count documents *flagged*. For the three control methods the right number is 0, so anything above it is an error; for every other method it is all of them.

## False positives on the controls

By construction, half the letters in every method carry something of the sender's that looks like PI: one in four its street address, one in four a landline (and one in four is a firm named after people, to tempt the name model). The checker is expected to flag the first two until they are on the ignore list, so the figure that says something about the detectors is the one with the list in place.

10 of 18 control documents were flagged; 0 of 18 with the sender's own details on the ignore list.

| File | Verdict | What triggered it | With the ignore list |
|---|---|---|---|
| doc_012_m2_proper.pdf | `PI_VISIBLE` | address_au: “319 Herrera Road, Port Isaiah WA 2691” | `NO_ISSUES_FOUND` |
| doc_018_m6_scan_marker_100.pdf | `PI_VISIBLE` | address_au: “28/19 Walker Street, Baileybury QLD 2036” | `NO_ISSUES_FOUND` |
| doc_019_m7_control.pdf | `PI_VISIBLE` | address_au: “47 White Crescent, Benjaminchester TAS 2” | `NO_ISSUES_FOUND` |
| doc_022_m2_proper.pdf | `PI_VISIBLE` | phone_au: “(07) 9016 3854” | `NO_ISSUES_FOUND` |
| doc_028_m6_scan_marker_100.png | `PI_VISIBLE` | phone_au: “(03) 9850 8167” | `NO_ISSUES_FOUND` |
| doc_029_m7_control.pdf | `PI_VISIBLE` | phone_au: “(07) 9833 3868” | `NO_ISSUES_FOUND` |
| doc_039_m7_control.pdf | `PI_VISIBLE` | ner_person: “Johnson”; ner_person: “Johnson Plumbing” | `NO_ISSUES_FOUND` |
| doc_052_m2_proper.pdf | `PI_VISIBLE` | address_au: “414 Rush Road, Davisborough ACT 2253” | `NO_ISSUES_FOUND` |
| doc_058_m6_scan_marker_100.png | `PI_VISIBLE` | address_au: “23/201 Reese Street, Port Robert TAS 264” | `NO_ISSUES_FOUND` |
| doc_059_m7_control.pdf | `PI_VISIBLE` | address_au: “Unit 11, 81 Rodriguez Street, Roseport A” | `NO_ISSUES_FOUND` |

## Misses

No document with an issue was passed as clean.

## Recall by PI type

Each piece of PI the generator put on a page, and whether a finding of the right kind holds it. Counted where the PI is there to be read: unredacted documents (text layer) and scans under a see-through marker stroke (OCR).

| PI type | Text layer (`m1_none`) | Through marker, 0.60 | Through marker, 0.85 |
|---|---|---|---|
| name | 11/11 (100%) | 11/11 (100%) | 10/10 (100%) |
| dob | 3/3 (100%) | 3/3 (100%) | 4/5 (80%) |
| address | 9/10 (90%) | 7/8 (88%) | 8/8 (100%) |
| email | 5/5 (100%) | 4/4 (100%) | 5/5 (100%) |
| phone | 5/5 (100%) | 3/3 (100%) | 3/3 (100%) |
| medicare | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) |
| tfn | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) |

Names on unredacted documents, by what caught them: ner_person: 10, name_label: 1.

## Speed

- Digital PDFs: 0.1 s per document on average
- Scans (OCR, plus the enhanced pass): 6.2 s per document

Measured on the machine that ran this report, CPU only; the first document also pays for loading the models.

## How to reproduce

```
python -m usefulredact.corpus --n 60 --seed 42
python -m usefulredact.evaluate
```
