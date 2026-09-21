# UsefulRedact — Handover and Next Steps

_Written 2026-09-22, at version 0.1.0. Milestones 1 to 4 of `BRIEF.md` are
complete: the checker and its command line, the synthetic corpus, the
evaluation, and the app. Four commits on `main` at
github.com/tuoa-tools/usefulredact, CI green on Ubuntu, Windows and macOS plus
the frontend job. The repository was created private; its owner makes it
public. `BRIEF.md` is the specification (its last section, "As built", lists
what differs from the plan) and `README.md` is the public account, including
the evaluation. Read both before this file. Section 6 is what to do next._

## 1. State of the repository

```
usefulredact/            the checker (import this; the app does)
  models.py              Finding, PageInfo, DocResult; how a verdict is reached
  pagetext.py            a page as one string plus tokens with boxes; span -> boxes
  pdf_checks.py          what the page hides: the render check and the mark checks
  detectors.py           rules: email, AU phone, DOB by label, Medicare, TFN, AU address
  ner.py                 spaCy en_core_web_sm, its filters, and the labelled-name rule
  watchlist.py           exact, fuzzy, part-of-name and short-form matching (rapidfuzz)
  pipeline.py            check_document(): pages, OCR and its second pass, metadata
  ocr.py                 RapidOCR wrapper, taken from UsefulText and kept in step with it
  report.py, cli.py      report.json / documents.csv / findings.csv; `usefulredact check`
  corpus.py              python -m usefulredact.corpus   (the labelled synthetic corpus)
  evaluate.py            python -m usefulredact.evaluate (report, results.csv, chart)
  eval_chart.py          the one chart (matplotlib, a development extra)
app/
  main.py                FastAPI: session, documents, page image, export, launch token
  session.py             temp copies, one worker thread, clean-up, the stale-folder sweep
  launcher.py            `usefulredact-app`: free port, token, browser tab, signals
frontend/                React 19 + Vite + TypeScript + Tailwind 4 + TanStack Query
  src/App.tsx            header, drop zone, lists, document list, export
  src/components/        DocumentView (page + boxes + findings), DropZone, ListsPanel, ...
  src/lib/               verdicts (all wording), boxes (percent positions), files, route
tests/                   94 tests (pytest); fixtures are generated, nothing is downloaded
eval/                    eval_report.md and eval_chart.png (tracked); results/ is ignored
docs/screenshot.png      the README picture, taken from the running app
PROJECT_DOCS/            BRIEF.md (specification), this file
```

Ignored and regenerated: `corpus/` (from its seed), `app/static/` (the built
UI), `eval/results/`, `usefulredact_out/`.

Environment: Python 3.13, `.venv` from `pip install -e ".[dev]"`. Verified
together: rapidocr 3.9.2, onnxruntime 1.23.2, pymupdf 1.28.2, spacy 3.8.16
with en_core_web_sm 3.8.0 (a pinned wheel URL in `pyproject.toml`), rapidfuzz
3.14.6, fastapi 0.141, numpy 2.5, pillow 12.3. Node 24 for the UI. The
development machine is an Intel Mac, so Windows and Apple Silicon are proven
only by CI.

```
.venv/bin/usefulredact check <paths> --out report/      the command line
.venv/bin/usefulredact-app                              the app (opens a browser tab)
cd frontend && npm ci && npm run build                  the UI, into app/static
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
cd frontend && npm run lint && npm run typecheck && npm test
.venv/bin/python -m usefulredact.corpus --n 60 --seed 42
.venv/bin/python -m usefulredact.evaluate               about five minutes on this machine
.venv/bin/python -m usefulredact.evaluate --chart-only  redraw the chart from results.csv
```

Live reload while working on the UI: `.venv/bin/uvicorn app.main:app --port 8000`
in one terminal (no token in this mode), `npm run dev` in `frontend/`, open
`http://localhost:5173`.

## 2. What the checker does per document

1. **PDF page with a text layer:** words with boxes (`get_text("words")`,
   rotated into display space) become a `PageText`. `pdf_checks.check_page`
   asks two questions of each word. *Does it render?* The page is drawn at
   110 dpi in grey; a word whose box spans under 30 grey levels (2nd to 98th
   percentile) is flat colour, so it cannot be read on the page although it is
   in the file. Tokens under three alphanumerics use the full range instead,
   and only count under a known mark. *Is it under a see-through mark?* A fill
   or highlight whose composite with white is 0.6 luminance or darker, a
   redaction annotation never applied, dark ink 4 pt or wider. Neighbouring
   hidden words become one `recoverable` finding.
2. **Scanned page or image file** (fewer than 25 extractable characters, or an
   image over 15% of a digital page): rendered at 200 dpi and read by OCR.
   Regions under 0.5 confidence are dropped and counted; a page under 0.70
   mean, or with many dropped regions, or with content and no text, gets a
   `low_confidence` finding. If the scan has dark blocks (20 or more 8 px
   blocks under 110), a copy with levels stretched (everything above 64 to
   white) is read too, and PI found only there is kept and says so.
3. **PI detection** over every string that could be read, including form-field
   values, annotation comments and metadata. Rules first, then the labelled-name
   rule, then spaCy. A match lying inside one already kept is folded into it
   (`also`). PI wholly under a mark is folded into the recovered-text finding
   (`holds`) rather than listed twice. GPE, LOC, a shared mailbox, a locality
   with no street line and a populated author field are `context`.
4. **Verdict:** any `recoverable` finding gives `FAIL_RECOVERABLE`; else any
   `pi` gives `PI_VISIBLE`; else any `low_confidence` gives
   `REVIEW_LOW_CONFIDENCE`; else `NO_ISSUES_FOUND`. An unreadable file is
   `NOT_CHECKED`, never a pass.

Boxes are in page units (points for a PDF, pixels for an image) beside the
page's own width and height, so the UI places them as percentages and never
measures the picture.

## 3. Results (synthetic, 60 documents, seed 42)

| | Full pipeline | With the sender's details ignored | Baseline: text layer + regex |
|---|---|---|---|
| Documents with an issue, flagged | 42 of 42 | 42 of 42 | 30 of 42 |
| Documents with no issue, flagged | 10 of 18 | 0 of 18 | 6 of 18 |
| Exactly the expected verdict | 50 of 60 | 60 of 60 | n/a |

Nine of the ten false positives are the sender's own street address or
landline, which half the letters in every method carry by construction; the
tenth is the name model reading "Johnson Plumbing" as a person. Misses show
only piece by piece: address 9 of 10 in the text layer and 7 of 8 through a
60% marker; date of birth 4 of 5 through an 85% marker. A digital PDF takes
about 0.1 s, a scanned page about 6 s.

These numbers are easy to over-read. The same hands wrote the generator and
the detectors, there are six documents per method, and every document is one
page. Section 6B is about that.

## 4. Things that were learned the hard way (keep)

**The checker**

- `get_drawings()` cannot see an image pasted over text, and says nothing about
  white boxes or white text. The render check covers all of them at once and
  also stops white-on-dark banners and tinted table cells being flagged. Keep
  it as the primary test for opaque covers; the vector and annotation checks
  only name the method and handle see-through marks.
- Percentiles forgive JPEG speckle in a cover but would wave a full stop
  through as "flat", hence the strict range for short tokens.
- The OCR engine reads through an 85% marker on its first pass more often than
  expected. The second pass earns its place on single items, not whole documents.
- OCR glues labels onto values when it loses the colon ("Emailerin.wilson12@").
  Expect the same for other fields.
- spaCy's small model calls Australian cities, OCR misspellings of them
  ("Neweastle") and company names PERSON. The place list (with a fuzzy match),
  the organisation-word filter and the labelled-name rule exist because of it.
- A fuzzy match needs a length guard: "protestcase" is 84% "testcase".
- `import pymupdf`, not `import fitz`: the old name warns on every run.

**The corpus and the evaluation**

- Faker's `en_AU` is not realistic where it matters: 200 street suffixes drawn
  evenly ("Kennedy Laneway", "Gary End"), phone formats without area codes, and
  companies made only of surnames. The corpus builds its own addresses and
  organisations for that reason.
- Faker's `date_between("today")` and `date_of_birth()` depend on the day they
  run. The corpus uses a fixed `TODAY` so a seed gives the same bytes on any day.
- "Dear Stephen," left a first name outside the redacted set, so a "properly
  redacted" letter genuinely leaked and its label was wrong. Every appearance
  of PI must be registered with `w.pi()`.
- With six documents per method, look-alike traits left to chance gave the
  controls 14 of 18 sender details in one draw. They are stratified by position
  within the method group (`Traits.for_position`). Do not fix a bad-looking
  number by changing the seed.

**The app**

- Windows will not delete an open file. Removing a document mid-check raised
  WinError 32; the copy is now remembered and deleted when the worker lets go.
- Under the launcher uvicorn runs in a thread and installs no signal handlers,
  so `kill` used to leave the document copies on disk. SIGTERM and SIGBREAK now
  take the Quit road, and the session has an exit hook.
- A killed process cannot clean up, so each session locks a file in its folder
  and every start sweeps folders whose lock can be taken. Do not replace this
  with a process-id check: on Windows `os.kill(pid, 0)` ends the process.
- `print` is buffered when output is piped; the launch address is flushed.
- Never call `ocr.available()` or `ner.available()` from a request handler:
  they load models. The worker thread loads them and `/api/health` reports
  `null` until it has.
- A bare `http://127.0.0.1:<port>/` gives 401 by design. The tab must be opened
  from the launch address, which sets the cookie.

## 5. Rules to keep

- **Fresh build, synthetic data only.** An earlier private prototype exists
  outside this repository. Nothing is copied from it, and no real document,
  organisation name or sector-specific wording goes into code, fixtures, tests
  or docs.
- **Never say "safe".** `frontend/src/lib/verdicts.test.ts` fails the build on
  "safe", "secure", "clean" or "passed" in verdict wording, and on a green
  "No issues found". Grey is deliberate.
- **Local only, nothing kept.** No network at run time, no telemetry, no log
  file, no persistence. A new feature that wants to remember something between
  sessions needs a decision from the owner first.
- **It is a checker.** It never writes to a document.
- **Seed 42 is the reported corpus.** Tune on other seeds, run 42 once for the
  figures, and say in the README what was done if that is ever not true.
- **Evaluation claims stay labelled synthetic**, in the README and anywhere
  else they are quoted.
- Code style follows UsefulText: ruff at 100 columns, comments that say why,
  commit messages with a short subject and prose paragraphs.

## 6. Next steps, in order

### A. Before the repository goes public (an hour or two)

1. **Run it on a real Windows machine.** CI proves the tests; it does not prove
   the browser tab opening, the folder picker, Quit, or that closing the console
   window cleans up `%TEMP%\usefulredact-session-*`. Check each by hand.
2. **Read the README on GitHub as a stranger would.** Do both pictures render,
   do the wide tables fit. The clone-and-run steps were followed from a clean
   clone on macOS on 2026-09-22 and work as written, with `pip install -e .`
   alone; the same has not been done on Windows.
3. **Tag `v0.1.0`**, make the repository public, and add topics (redaction,
   privacy, pdf, ocr). The README's clone address only works once it is public.
4. **In UsefulText**, reword the first line of `usefultext/ocr.py`'s docstring,
   which still describes where that file came from before UsefulText.

### B. Make the evaluation harder to argue with (the most valuable work)

5. **Several seeds.** `evaluate --seeds 5`: mean and range per method and per PI
   type. One document is 17 points of a method's score today.
6. **Harder corpus methods**, each a failure seen in real documents:
   - a scanned PDF that carries a hidden OCR text layer, with the marker burnt
     into the image only (the render check should catch it; nothing tests it);
   - a box over part of a word, or over a first name and not the surname;
   - white box and white text (unit-tested, not in the corpus);
   - a properly redacted file whose metadata still names the person;
   - a picture of text inside a digital page (the mixed-page OCR path in
     `_check_pdf_page` has no test at all);
   - pages with `/Rotate 90` (the rotation matrix is applied everywhere and has
     never been exercised);
   - documents of several pages (every corpus file is one page, so page
     navigation in the app has only been tried by hand);
   - marker at 90% and 95%, and scans at lower resolution with heavier JPEG,
     to find where reading-through stops.
7. **Finding-level precision.** Only document-level false positives and
   item-level recall are measured. Count findings on unredacted documents that
   match neither a `pi_items.csv` row nor a sender detail.
8. **Ablations.** Name model on and off (`--no-ner` exists), second OCR pass on
   and off, render check against marks-only. Shows what each part buys.

### C. New checks, by how often the failure happens

9. **Earlier versions inside the PDF.** A PDF saved incrementally keeps its
   previous revision; redact and "Save" rather than "Save as", and the
   unredacted text is still in the file. Detect a file with more than one
   revision and compare the text of each. This is the biggest known gap.
10. **Image metadata.** EXIF in a JPG or PNG: GPS position, author, device.
11. **Hidden layers, off-page text, attachments.** Optional content that is
    switched off, text outside the crop box, embedded files, XMP metadata. The
    render check may already catch the first two; prove it with a test.
12. **More Australian identifiers**, each with its test: driver licence,
    passport, BSB and account number, Centrelink CRN, Individual Healthcare
    Identifier (it has a checksum).

### D. The app

13. **"Ignore this" on a finding**: adds its text to the ignore list and checks
    again. The ignore list answers the main class of false positive, and typing
    into it is the friction.
14. **Reviewer decisions.** Mark a finding confirmed or not an issue, for the
    session, and carry that into the export, which then becomes a review record.
15. **Keys and zoom.** Next and previous finding from the keyboard; zoom on the
    page. Zoom was the first thing cut.
16. **Install without Node.** A release workflow that builds the UI, builds a
    wheel with `app/static` inside, and attaches it to a GitHub Release, so
    `pip install <wheel>` gives the app. Then UsefulText's packaging pipeline
    for a macOS bundle and a Windows installer (Milestone 5); the spaCy model
    has to be bundled beside the three OCR models.
17. **An option to mask matched text in exports**, and DOCX input (Milestone 5).

## 7. Parking lot

- A larger name model (`en_core_web_md` or `trf`) measured against the small
  one on the corpus: recall gained against size and speed.
- Pixelated or blurred regions in an image. They can sometimes be reversed;
  detecting them is a different problem from anything here.
- Handwriting, faces, signatures, photographs.
- Formats beyond Australia.
- A dark theme. Status colours would need re-choosing, not inverting.

## 8. Starting a fresh conversation

Open it in `/Users/adam/data/Python stuff/usefulredact` and start with:

> Read `PROJECT_DOCS/HANDOVER.md`, then `PROJECT_DOCS/BRIEF.md` and
> `README.md`. We are at v0.1.0 with Milestones 1 to 4 done. Keep the rules in
> section 5 of the handover. I want to work on section 6, starting with
> item __. Before changing anything, run the tests and tell me they pass.
