# BRIEF – UsefulRedact (working name)

A local-only app that checks whether the redaction in a document actually
holds, before you send it anywhere. Drop documents in, get a verdict for each,
then open a document and see every finding highlighted on the page.

Revision 2, 21 September 2026. What changed from revision 1 is listed at the end.

## Context

- Portfolio proof of concept, time-boxed to about two days. Ship the minimum
  that works and is measured.
- **Synthetic data only.** No real documents are used in development, tests or
  evaluation.
- **Generic by design.** No sector-specific document types, identifiers,
  rosters or tracking spreadsheets. The only list a user supplies is an
  optional watchlist of names, typed or pasted in for the session.
- **Origin framing for the README:** "prompted by seeing how often documents
  arrive with redaction that doesn't hold." Name no organisations.
- **Template:** UsefulText (`tuoa-tools/usefultext`). Reuse its `ocr.py`
  (RapidOCR), the FastAPI + React/Vite/TypeScript/Tailwind UI pattern, the
  launch-token guard on the local API, the project layout, packaging config
  and CI. This repo is `tuoa-tools/usefulredact`.
- **Environment:** Windows and Mac, Python 3.13. Everything pip-installable
  (no Tesseract or other standalone installers).

## Principles

1. **Local only.** No network calls at runtime. Documents never leave the
   machine; the UI and the README say so.
2. **It's a checker, not a redactor.** It never modifies files.
3. **Never say "safe".** The best verdict is "no issues found".
4. **Human in the loop.** Every finding is shown at its location on the page
   so a person can confirm it.
5. **Honest ML.** A neural OCR model plus statistical named-entity recognition
   (NER) inside a mostly rules-based pipeline. Described exactly that way; no
   LLMs.
6. **Nothing is kept.** Uploaded copies and results live for the session only,
   in a temporary folder removed on exit. The only files the app writes are
   the reports you export. A report contains the PI that was found (that is
   the evidence), and the UI and README say so.

## Verdicts (per document)

| Verdict | Meaning |
|---|---|
| `FAIL_RECOVERABLE` | Text is still extractable under a redaction mark (box, annotation, layer, pasted image) |
| `PI_VISIBLE` | Personal information (PI) detected in visible or OCR-readable text, or in document metadata |
| `REVIEW_LOW_CONFIDENCE` | OCR confidence too low to assess; needs a human look |
| `NO_ISSUES_FOUND` | Nothing detected – not a guarantee |

- Precedence when several apply: `FAIL_RECOVERABLE` > `PI_VISIBLE` >
  `REVIEW_LOW_CONFIDENCE` > `NO_ISSUES_FOUND`.
- **Context findings.** Place names (spaCy GPE and LOC) and a populated
  metadata author field are shown and exported, but do not change the verdict
  on their own. A city in a letterhead is not personal information.

## How a page is read

Every page becomes one text string plus a list of tokens with boxes: words
from the PDF text layer, or lines from OCR when the page is a scan. Detectors
work on the string and return character spans; spans map back to token boxes.
Boxes are stored in PDF points together with the page size, so the UI can draw
them at any zoom. This is what makes "highlight it on the page" cheap.

## Milestones (in order – stop where time runs out)

### M1 – CLI core

**Input:** PDF (digital and scanned), PNG and JPG.

**Digital PDF checks (PyMuPDF):**

- Filled dark shapes from `page.get_drawings()` intersected with word boxes
  from `page.get_text("words")`. Shapes below a small area floor are ignored
  as decoration.
- Annotations that are square, ink or highlight, plus redact annotations that
  were never applied, covering text.
- Semi-transparent fills over live text (`fill_opacity`).
- **Render check (catch-all):** render the page and look at the pixels inside
  each word box. A word whose box renders as near-uniform dark pixels is
  covered, whatever covered it, including a black image pasted over the text,
  which `get_drawings()` cannot see. White text on a dark banner keeps its
  contrast, so it is not flagged.
- Form-field values and document metadata (author, title, subject, keywords)
  go through the PI detectors.
- A properly applied redaction (no text under the box) must **pass**.

**Scans and images:** render, OCR through the reused `ocr.py`, gate
low-confidence pages to `REVIEW_LOW_CONFIDENCE`, and send OCR text through the
same PI detectors, so marker or semi-transparent redaction that OCR can read
through is caught as `PI_VISIBLE`.

**PI detectors:**

- Regex: email; AU phone; dates in date-of-birth contexts; Medicare number
  with checksum (weights 1,3,7,9,1,3,7,9 on the first 8 digits, mod 10 = 9th
  digit); TFN with checksum (weights 1,4,3,7,5,8,6,9,10, sum mod 11 = 0); AU
  street address plus postcode heuristic.
- spaCy `en_core_web_sm`: PERSON changes the verdict; GPE and LOC are context.
  The model is a pinned wheel in `pyproject.toml`, so one `pip install` brings
  it and nothing is fetched at run time.
- Optional **watchlist** of names, with word-boundary and fuzzy matching
  (`rapidfuzz`) for OCR noise and shortened names.

**Output:** a verdict per document plus findings (page, box, kind, detector,
matched text, and for covered text what was recovered), as JSON and CSV.
`python -m usefulredact check <paths> [--watchlist names.txt] [--out dir]`.

### M2 – Synthetic labelled corpus

- `python -m usefulredact.corpus --n 60 --seed 42`, deterministic from the seed.
- Faker `en_AU` for names, DOBs, addresses, emails and phones; Medicare and
  TFN numbers generated with valid checksums.
- Everyday letter and form styles: an account letter, an appointment letter,
  an application form, a reference letter.
- One method per document:
  1. no redaction (PI visible)
  2. proper redaction (`add_redact_annot` + `apply_redactions`)
  3. black rectangle drawn over live text
  4. black annotation, never applied
  5. semi-transparent highlight over text
  6. simulated scan with a marker stroke at opacity 0.6, 0.85 and 1.0 (render
     to image, draw with PIL, add slight noise and rotation)
  7. control document with no PI at all
  8. black image pasted over live text
- **Hard negatives** in methods 2 and 7 so the false-positive figure means
  something: an organisation letterhead with a city, dates that are not dates
  of birth, nine-digit reference numbers that fail the TFN checksum, a dark
  header banner with white text.
- Labels by construction: `labels.csv` (file, method, expected verdict) and
  `pi_items.csv` (file, page, PI type, value, box). Marker opacity 0.6 and
  0.85 expect `PI_VISIBLE` because a person can read through them, so an OCR
  miss there is reported as a miss. Opacity 1.0 expects `NO_ISSUES_FOUND` and
  serves as a third control group.

### M3 – Evaluation (the key deliverable)

- Run the pipeline over the corpus.
- Doc-level confusion matrix (issue vs no issue), exact-verdict accuracy,
  **recall per redaction method**, and false positives on the controls
  (method 2, method 7, method 6 at opacity 1.0).
- Recall per PI type on the unredacted documents, from `pi_items.csv`. This is
  where the small NER model's weakness on names will show; report it.
- **Baseline comparison:** a naive "extract text layer + regex" check against
  the full pipeline on the same corpus.
- Output `eval/eval_report.md` plus one chart PNG. The results table goes into
  the README, labelled as synthetic.

### M4 – The app (UsefulText pattern)

- **Drop in** files or a folder; optional watchlist box (held in memory only).
- **Document list:** verdict badge per file, finding counts, progress while
  checking. OCR runs off the event loop so the page stays responsive.
- **Document view:** the page image with a box on every finding, coloured by
  kind (recoverable under a mark / PI visible / context), and the findings
  list beside it. Click a box or a row to find the other. A covered-text
  finding shows what was recovered from under the mark.
- Export the report as CSV or JSON, for one document or all.
- A visible "runs locally – nothing is uploaded" note, and verdict wording
  that never says "safe".
- Backend: FastAPI on loopback behind UsefulText's launch token; session store
  in a temp folder; opens in a browser tab. No library, no corrections, no
  desktop window.
- If time runs short, cut in this order: zoom, click-to-find, filter by kind.
  Never cut: verdict badges, boxes on the page, export, the local-only note.

### M5 – Stretch

Packaged release via the UsefulText release pipeline; desktop window; DOCX
input; an option to mask matched text in exported reports.

## Tests

- pytest for each detector: valid and invalid checksums, regex edge cases.
- pytest for each redaction method, using small generated fixtures.
- API tests for upload, verdict, page image and export.
- Tests stay offline. CI as in UsefulText: ruff and pytest on Ubuntu, Windows
  and macOS, plus the frontend lint, typecheck, test and build job.

## Out of scope

- Automatic redaction or fixing documents
- LLMs or any cloud service
- Face detection
- Accuracy claims beyond the synthetic corpus

## README must include

- Purpose and the "not infallible" caveat, stated up front
- A screenshot of the document view on a synthetic document
- How it works (pipeline diagram or list) and an honest description of the ML
- Evaluation results table and baseline comparison, **clearly labelled as
  synthetic data**
- Limitations: handwritten scans, images of faces, PI types not covered, OCR
  errors, names the NER model misses
- Privacy statement: local only, no telemetry, nothing kept, and the warning
  that exported reports contain the PI that was found

## Definition of done

M1 + M2 + M3 + a working M4, with the README showing evaluation results and
the screenshot; CI green on all three platforms; repo public on `tuoa-tools`.

## Changes from revision 1

- The app is the product, not a minimal add-on: the page view with findings
  highlighted moved from stretch to core, and the UI uses UsefulText's React
  stack.
- GPE and LOC became context findings that do not change the verdict alone.
- Added the render check and corpus method 8 (pasted image over text).
- Added hard negatives, `pi_items.csv` and recall per PI type.
- Added principle 6 (nothing is kept) and the session-only design.
- Settled: verdict precedence, labels for the three marker opacities, the
  spaCy model as a pinned wheel.

## As built (version 0.1.0)

Milestones 1 to 4 are done. What differs from the plan above:

- **An ignore list**, beside the watchlist. The first evaluation run made the need
  plain: the checker cannot tell an organisation's own street address or landline from a
  person's, so it flags both until told which are fine.
- **`NOT_CHECKED`**, a fifth status for a file that cannot be opened (damaged,
  password-protected, unsupported). It is not a verdict about the document, and it must
  never read as a pass.
- **Look-alikes in the corpus are stratified, not random.** With six documents per
  method, leaving the sender's address and landline to chance handed the controls most
  of them in one draw and made the methods incomparable.
- **A second OCR pass** on a contrast-stretched copy of a scan that has dark strokes.
- **The page drawn without its annotations**, in the app, for a PDF whose marks are
  annotations: the quickest way to see what they were covering.
- **The address bar remembers** which document and finding are open (ids only).
- **A place-name list and a labelled-name rule** around the name model, after it read
  Australian cities and company names as people.
- Not done: zoom in the page view; everything in Milestone 5.
