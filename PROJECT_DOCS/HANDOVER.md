# UsefulRedact — Handover and Next Steps

_Written 2026-09-22, now at version 0.1.2. Milestones 1 to 4 of `BRIEF.md` are
complete: the checker and its command line, the synthetic corpus, the
evaluation, and the app. The code is on `main` at
github.com/tuoa-tools/usefulredact, with CI green on Ubuntu, Windows and macOS
plus the frontend job. The repository was created private; its owner makes it
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
  console_win.py         the window's X, log off and shut down (Windows; see §4)
frontend/                React 19 + Vite + TypeScript + Tailwind 4 + TanStack Query
  src/App.tsx            header, drop zone, lists, document list, export
  src/components/        DocumentView (page + boxes + findings), DropZone, ListsPanel, ...
  src/lib/               verdicts (all wording), boxes, files, route, keepAlive (the
                         ping), unattended (closing a session that has been left alone)
tests/                   pytest; fixtures are generated, nothing is downloaded
eval/                    eval_report.md and eval_chart.png (tracked); results/ is ignored
docs/screenshot.png      the README picture, taken from the running app
PROJECT_DOCS/            BRIEF.md (specification), this file
constraints.txt          the exact versions the tests and the evaluation ran with
packaging/               UsefulRedact.spec (PyInstaller: macOS, Linux), windows.iss (Inno
                         Setup), the icons, RELEASE_NOTES.md; models/ is gathered, not kept
scripts/                 prepare_bundle, build_windows, smoke_bundle (drives a built app
                         end to end), make_icon
```

Ignored and regenerated: `corpus/` (from its seed), `app/static/` (the built
UI), `eval/results/`, `usefulredact_out/`.

Environment: Python 3.13, `.venv` from `pip install -e ".[dev]" -c constraints.txt`. Verified
together: rapidocr 3.9.2, onnxruntime 1.23.2, pymupdf 1.28.2, spacy 3.8.16
with en_core_web_sm 3.8.0 (a pinned wheel URL in `pyproject.toml`), rapidfuzz
3.14.6, fastapi 0.141, numpy 2.5, pillow 12.3. Node 24 for the UI. The
development machine is an Intel Mac; Windows 11 was gone over by hand on
2026-09-22 (§4A), and Apple Silicon is still proven only by CI.

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
- **SIGBREAK is Ctrl+Break, not the window's X.** Closing a console window sends
  CTRL_CLOSE_EVENT, which the signal module does not carry at all; the same goes
  for logging off and shutting down. They arrive only through
  SetConsoleCtrlHandler, which `app/console_win.py` now registers. Windows ends
  the process a few seconds after that handler returns, so it closes the session
  itself with a short wait rather than asking the server to stop and waiting on
  a worker that may be sixty seconds from finishing.
- A killed process cannot clean up, so each session locks a file in its folder
  and every start sweeps folders whose lock can be taken. Do not replace this
  with a process-id check: on Windows `os.kill(pid, 0)` ends the process.
- `print` is buffered when output is piped; the launch address is flushed.
- Never call `ocr.available()` or `ner.available()` from a request handler:
  they load models. The worker thread loads them and `/api/health` reports
  `null` until it has.
- **The keep-alive must keep going while the tab is hidden.** TanStack Query
  stops interval refetching in a background tab unless told otherwise
  (`refetchIntervalInBackground`). UsefulText sets it; it was dropped in the
  port, so two minutes with another tab in front stopped the app and deleted
  the results. Browsers also throttle a long-hidden tab's timers to once a
  minute, so the ping is every 30 s, not 60, to stay inside the server's 120 s.
  The settings and their reasons are in `frontend/src/lib/keepAlive.ts`, with a
  test, and a Python test holds the page's copy of the limit to the server's.
- **Left alone, this app closes the session; UsefulText, with the same machinery,
  waits.** The two want opposite things. Someone who leaves UsefulText and comes
  back wants to carry on. Someone who leaves this one has left personal
  information on a screen and copies on a disk. So once the ping was fixed and an
  open tab could keep the app alive for ever, a second clock was needed: 30
  minutes untouched with documents loaded, a two-minute warning, then what was
  found comes off the page *first* and the app is asked to stop. It is the wall
  clock, so a lid closed for an hour counts as an hour; it does not run with
  nothing loaded or while documents are being checked. `UNATTENDED_MS` in
  `frontend/src/lib/unattended.ts` is the one number; a setting for it would be
  the next step if thirty minutes is wrong for someone. Checked in a real
  browser by fast-forwarding headless Chrome (`--virtual-time-budget`).
- **On Windows the monotonic clock counts through sleep.** Open the lid after an
  hour and the idle watch's first check saw an hour without a ping and quit
  before the page could answer. A check that arrives far later than it was due
  now means the machine slept, and the page gets its two minutes afresh
  (`woke_from_sleep` in `app/main.py`; the same fix went into UsefulText).
- **Patch a clock only where the code under test reads it.** Replacing
  `time.monotonic` for the whole process starves the event loop running the
  test of real time, and it eats the fake timestamps. Replace `module.time`.
- **Chain a commit to its tests with `&&`.** A failing test went to UsefulText's
  public `main` because `pytest; git commit; git push` does not stop.
- **Packaging.** The pipeline is UsefulText's, file for file, and so are its
  reasons: on Windows no PyInstaller (Defender quarantines its exes) but
  python.org's signed embeddable runtime plus Inno Setup; only the three OCR
  models that are used, not the wheel's 260 MB. What this app added:
  - *The name model.* `spacy.load("en_core_web_sm")` looks the model up in the
    installed-distribution metadata, which a frozen app does not have; importing
    the package and calling its `load()` works everywhere. spaCy also finds its
    own components through entry points, so the spec copies the metadata of
    spacy, thinc and their relatives into the bundle.
  - *No console.* `pythonw.exe` and a windowed bundle have no `sys.stdout` at
    all; the launcher's `print` of the launch address would have been the first
    thing to crash. It now opens the null device in their place.
  - *The smoke test cannot read the app's output* (there may be none) and the
    app keeps no file it could read a port and secret from, so the test chooses
    both and passes the secret in `USEFULREDACT_TOKEN`. It also points the app's
    temp directory at a folder of its own, which is how it can assert that the
    session folder exists while the app runs and is gone after Quit.
  - An installer has an advantage the pip install lacks: the name model is inside
    it, so the flaky GitHub download in §4A never happens on a user's machine.
- **A clean-up cut short must still be sweepable.** A folder with no lock file
  used to fall back to a 24-hour age rule, so a partial delete that took the
  lock file and left a document would have sat for a day. Now `close()` keeps
  the lock file (open, so Windows cannot delete it) whenever the worker has not
  let go, and a folder with no lock at all is swept after 60 s, the grace being
  for a session that has made its folder and not yet its lock.
- The guard is on `/api/`, and `/api/health` is outside it so the page can ping
  without the cookie. A bare `http://127.0.0.1:<port>/` therefore serves the
  built UI with no cookie at all - it is a static shell, and every call it makes
  for data gets 401 until the tab has been opened from the launch address. (An
  earlier note here said `/` itself gave 401. It does not, and never did.)

## 4A. Proven on Windows (2026-09-22)

The development machine is an Intel Mac, so everything below had only CI behind
it. A clean Windows 11 machine, Python 3.13.15, Node 24.19.0, from a fresh clone.

**What held.** `ruff` clean and 94 tests green in 36 s. `npm ci` (252 packages, no
vulnerabilities) and the Vite build into `app/static`. The checker over a
twenty-document corpus in 42 s, every failure mode caught and every verdict the
expected one bar the sender's own address on three controls - the documented
false positive, and the ignore list took it from three to none with no recall
lost. Both models load (`ocr` and `ner` both true in `/api/health`). A free port,
the launch token, the HttpOnly cookie, 401 without it and 403 on a wrong one.
Upload, verdict, page image and export. The browser tab opens by itself, the
folder picker reads a folder, the boxes land on the page.

**What the temporary folder does on each road out**, checked one at a time:
Quit and Ctrl+Break delete it; closing the tab deletes it two minutes later; a
`taskkill /F` leaves it and the next start sweeps it, document copies and all.
Closing the console window used to leave it too - that is what §4 and
`console_win.py` are now about.

**What could not be tested, and why.** CTRL_CLOSE_EVENT cannot be generated:
`GenerateConsoleCtrlEvent` only sends Ctrl+C and Ctrl+Break, and on Windows 11 a
console app's window belongs to Windows Terminal, so `FindWindow` cannot reach it
to post WM_CLOSE either. It takes a person clicking the X. Ctrl+C is no easier:
sending it needs the child in its own process group, and `CREATE_NEW_PROCESS_GROUP`
disables Ctrl+C for that group, so a test of it proves nothing either way.

**Two things to know before trusting a fresh install.**

- `pip install -e .` fetches the name model from the spaCy releases page, and
  GitHub answered 504 to that one asset twice in a row while serving every other
  asset normally - and served the same URL to `curl` without complaint. It looks
  like HEAD on that path, which is what pip sends first. The README now says to
  try again or fetch the wheel by hand. It is the only download that is not PyPI,
  and it is the only part of the install that can fail this way.
- The pins resolved to onnxruntime **1.30.0** here against the 1.23.2 in §1. Both
  satisfy `>=1.20,<2`, so an install today does not reproduce the runtime the
  evaluation figures were measured on. Nothing looked different, but if a number
  ever moves without the code moving, look here first.

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

1. ~~**Run it on a real Windows machine.**~~ Done 2026-09-22, see §4A. The tab,
   the folder picker, Quit and every other road out were checked by hand;
   closing the console window turned out to leave `%TEMP%\usefulredact-session-*`
   behind and now does not. What remains from it: the two install notes at the
   end of §4A, and items 18 and 19 below.
2. ~~**Read the README on GitHub as a stranger would.**~~ Done 2026-09-22, by
   rendering it with GitHub's own markdown API and reading the result. Both
   pictures render, every table fits the column, and the clone-and-run steps
   work from a clean clone on macOS and on Windows (§4A). What reading it
   changed: a "Results at a glance" table now sits straight after the
   introduction (recall per redaction method, full pipeline against the naive
   baseline, labelled synthetic), since that is what a visitor came for and it
   was two screens down; the per-method table was split into recall and false
   positives, because "3/6 flagged" is a score on one and an error count on the
   other; "every failed redaction was caught" became "every document with a
   failed redaction was flagged", which is what was measured; and a line now
   ties the chart (documents handled correctly) to the tables (documents
   flagged). One trap: the API's `gfm` mode renders as a *comment* does and
   turns every source line break into `<br>`; a README file is `markdown` mode.
3. **Make the repository public.** The tags (`v0.1.0`, `v0.1.1`) and the topics
   are in place. Pushing a tag runs `.github/workflows/release.yml`, which
   builds the four downloads and the wheel, smoke-tests each, and publishes
   them on the releases page; "Run workflow" does everything but publish, and
   is worth doing before any tag. A new version means changing `__version__`,
   `frontend/package.json` (and its lock) and the wheel address in the README,
   then tagging once CI and a trial run of the release workflow are green. The README's clone address and
   its wheel address only work once the repository is public.
4. ~~**In UsefulText**, reword where `ocr.py` came from.~~ Done, there and in its
   brief and handover.

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
16. ~~**Installers.**~~ Done in 0.1.2, the same way as UsefulText: a macOS app for
    Apple Silicon and one for Intel, a Windows installer, a Linux tarball, and the
    wheel, all built by `release.yml` and each started and driven end to end by
    `scripts/smoke_bundle.py` on the system it is for before anything is
    published. See "Packaging" in §4 for why each piece is the way it is. Left
    rough: opening the app a second time starts a second, separate session in a
    new tab rather than bringing back the first (UsefulText remembers a running
    instance in its data folder; this app keeps no such folder, on purpose); and
    on macOS, Quit from the Dock does nothing useful, because there is no window
    and no Cocoa event loop to hear it, so the page's Quit button is the way out.
    Neither loses anything: every road out still deletes the session.
17. **An option to mask matched text in exports**, and DOCX input (Milestone 5).

### E. Found while testing on Windows (§4A)

18. ~~**The tab outlives its server.**~~ Done (pull request #2). When the health
    ping fails after its retries, the page is covered and made `inert` and says
    the app is no longer running; it does not claim the copies were deleted,
    because from inside the page there is no telling. The cause of the commonest
    case was found afterwards and is in §4: the ping stopped whenever the tab was
    hidden, so the app was stopping itself under people who were reading
    something else.
19. ~~**Pin onnxruntime.**~~ Done. `constraints.txt` records every version the
    tests and the evaluation were run with; CI installs with it on all three
    systems, so that set is what is proven, and a new upstream release cannot
    turn a build red. `pyproject.toml` keeps its ranges, and the README says
    which install gives which. Regenerate the file whenever the evaluation is
    re-run (the command is at the top of it).
20. ~~**A wheel with `app/static` inside.**~~ Done. `release.yml` builds the UI,
    builds the wheel, checks the UI is in it and the version matches the tag,
    installs it into an empty environment and starts the app, then publishes it.
    "Run workflow" does all but the last step. Checked by hand as well: the
    160 KB wheel, installed into an empty venv in another folder, serves the UI
    and catches a failed redaction. It does not end the name-model download,
    which still comes from GitHub at install time (§4A).
21. ~~**`.gitattributes`.**~~ Done. Text is stored with LF on every machine. No
    file in the repository had CRLF when it went in, so nothing else changed.

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
> `README.md`. We are at v0.1.2: Milestones 1 to 4, and the packaged releases of Milestone 5. Keep the rules in
> section 5 of the handover. I want to work on section 6, starting with
> item __. Before changing anything, run the tests and tell me they pass.
