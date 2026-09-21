"""Evaluate the checker on the synthetic corpus: `python -m usefulredact.evaluate`.

Reads corpus/labels.csv and corpus/pi_items.csv, runs the full pipeline and a
naive baseline over every file, and writes eval/eval_report.md, one chart and
the per-document results.

The baseline is the check someone would script in ten minutes: pull the text
layer out of the PDF and run regular expressions over it. It has no OCR, no
name model and no idea what is under a box.

Everything here is measured on invented documents. It says how the checker
behaves on the failure modes the corpus contains, and nothing about documents
it has never seen.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from usefulredact import __version__, detectors
from usefulredact.corpus import CONTROLS, METHODS
from usefulredact.models import NO_ISSUES_FOUND, PI, PI_VISIBLE, DocResult
from usefulredact.pipeline import check_document

PI_TYPE_DETECTORS = {
    "name": {"name_label", "ner_person", "watchlist"},
    "dob": {"dob"},
    "address": {"address_au"},
    "email": {"email"},
    "phone": {"phone_au"},
    "medicare": {"medicare"},
    "tfn": {"tfn"},
}


@dataclass
class Row:
    file: str
    method: str
    variant: str
    style: str
    expected: str
    verdict: str = ""
    baseline: str = ""
    seconds: float = 0.0
    result: DocResult | None = None
    items: list[tuple[str, str]] = field(default_factory=list)  # (type, value)
    sender: list[str] = field(default_factory=list)  # the organisation's own details
    verdict_ignoring: str = ""  # the verdict with those details on the ignore list

    @property
    def expected_issue(self) -> bool:
        return self.expected != NO_ISSUES_FOUND

    @property
    def flagged(self) -> bool:
        return self.verdict != NO_ISSUES_FOUND

    @property
    def baseline_flagged(self) -> bool:
        return self.baseline != NO_ISSUES_FOUND

    @property
    def flagged_ignoring(self) -> bool:
        return self.verdict_ignoring != NO_ISSUES_FOUND


# ------------------------------------------------------------------- baseline
def baseline_verdict(path: Path) -> str:
    """Text layer + regex. An image has no text layer, so the baseline sees nothing."""
    if path.suffix.lower() != ".pdf":
        return NO_ISSUES_FOUND
    with pymupdf.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
    return PI_VISIBLE if any(m.kind == PI for m in detectors.find_all(text)) else NO_ISSUES_FOUND


# -------------------------------------------------------------------- running
def load(corpus: Path) -> list[Row]:
    items: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with open(corpus / "pi_items.csv", newline="", encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            pair = (r["type"], r["value"])
            if pair not in items[r["file"]]:
                items[r["file"]].append(pair)
    senders: dict[str, list[str]] = defaultdict(list)
    sender_file = corpus / "sender_details.csv"
    if sender_file.exists():
        with open(sender_file, newline="", encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                senders[r["file"]].append(r["detail"])
    with open(corpus / "labels.csv", newline="", encoding="utf-8") as handle:
        return [
            Row(r["file"], r["method"], r["variant"], r["style"], r["expected_verdict"],
                items=items.get(r["file"], []), sender=senders.get(r["file"], []))
            for r in csv.DictReader(handle)
        ]  # fmt: skip


def run(corpus: Path, rows: list[Row], quiet: bool = False) -> None:
    for index, row in enumerate(rows, start=1):
        path = corpus / row.file
        started = time.perf_counter()
        row.result = check_document(path)
        row.seconds = time.perf_counter() - started
        row.verdict = row.result.verdict
        row.baseline = baseline_verdict(path)
        # Only a flagged document can change, and only if the sender's details were found.
        row.verdict_ignoring = row.verdict
        if row.flagged and row.sender:
            row.verdict_ignoring = check_document(path, ignore=row.sender).verdict
        if not quiet:
            mark = "ok  " if row.verdict == row.expected else "MISS"
            print(f"[{index:>3}/{len(rows)}] {mark} {row.verdict:<22} {row.file}")


# -------------------------------------------------------------------- metrics
def _squash(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


def item_found(row: Row, kind: str, value: str) -> str | None:
    """The detector that caught this piece of PI, if any: a finding of the right
    kind whose text holds the value, or sits inside it (OCR may clip an end)."""
    want = _squash(value)
    for finding in row.result.findings:
        names = {finding.detector} | set(re.findall(r"also (\w+)", finding.detail))
        names |= set(re.findall(r"(\w+)", finding.detail.partition("holds: ")[2]))
        if not names & PI_TYPE_DETECTORS[kind]:
            continue
        got = _squash(finding.text)
        if got and (want in got or (len(got) >= 0.6 * len(want) and got in want)):
            return finding.detector
    return None


def confusion(rows: list[Row], flagged) -> dict[str, int]:
    c = Counter()
    for row in rows:
        c[
            ("T" if flagged(row) == row.expected_issue else "F") + ("P" if flagged(row) else "N")
        ] += 1
    return {k: c[k] for k in ("TP", "FN", "FP", "TN")}


def rates(c: dict[str, int]) -> dict[str, float | None]:
    def ratio(a: int, b: int) -> float | None:
        return a / b if b else None

    return {
        "recall": ratio(c["TP"], c["TP"] + c["FN"]),
        "precision": ratio(c["TP"], c["TP"] + c["FP"]),
        "specificity": ratio(c["TN"], c["TN"] + c["FP"]),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


# --------------------------------------------------------------------- report
def report(rows: list[Row], corpus: Path, seed_note: str) -> str:
    full = confusion(rows, lambda r: r.flagged)
    eased = confusion(rows, lambda r: r.flagged_ignoring)
    base = confusion(rows, lambda r: r.baseline_flagged)
    fr, er, br = rates(full), rates(eased), rates(base)
    exact = sum(r.verdict == r.expected for r in rows)
    exact_eased = sum(r.verdict_ignoring == r.expected for r in rows)
    out: list[str] = []
    add = out.append

    add("# Evaluation report\n")
    add(f"usefulredact {__version__} on {len(rows)} synthetic documents ({seed_note}).\n")
    add(
        "**Every document here is invented.** These figures describe how the checker behaves on "
        "the failure modes this corpus contains. They are not an accuracy claim about real "
        "documents, and 'no issues found' is never a guarantee.\n"
    )

    add("## Document level: issue or no issue\n")
    add(
        "An *issue* is any verdict other than `NO_ISSUES_FOUND`. The middle column is the same "
        "pipeline with each sender's own name, address and phone number on the ignore list, "
        "which is how the tool is meant to be used: it cannot tell an organisation's street "
        "address from a person's, so it flags both until told otherwise.\n"
    )
    add(
        "| | Full pipeline | Full pipeline, sender's details ignored "
        "| Baseline (text layer + regex) |"
    )
    add("|---|---|---|---|")
    for label, key in (
        ("Issues caught (true positives)", "TP"),
        ("Issues missed (false negatives)", "FN"),
        ("Clean documents flagged (false positives)", "FP"),
        ("Clean documents passed (true negatives)", "TN"),
    ):
        add(f"| {label} | {full[key]} | {eased[key]} | {base[key]} |")
    for label, key in (
        ("Recall", "recall"),
        ("Precision", "precision"),
        ("Specificity", "specificity"),
    ):
        add(f"| {label} | {_pct(fr[key])} | {_pct(er[key])} | {_pct(br[key])} |")
    add(
        f"| Exact verdict | {exact}/{len(rows)} ({exact / len(rows):.0%}) | "
        f"{exact_eased}/{len(rows)} ({exact_eased / len(rows):.0%}) | n/a: it has one answer |\n"
    )

    add("## By redaction method\n")
    add(
        "| Method | What was done | Expected | n | Full pipeline flagged | Exact verdict "
        "| Baseline flagged |"
    )
    add("|---|---|---|---|---|---|---|")
    for method, (expected, what) in METHODS.items():
        group = [r for r in rows if r.method == method]
        if not group:
            continue
        flagged = sum(r.flagged for r in group)
        matched = sum(r.verdict == r.expected for r in group)
        base_flagged = sum(r.baseline_flagged for r in group)
        add(
            f"| `{method}` | {what} | `{expected}` | {len(group)} | {flagged}/{len(group)} | "
            f"{matched}/{len(group)} | {base_flagged}/{len(group)} |"
        )
    add(
        "\nFor the three control methods the right number flagged is 0; for every other "
        "method it is all of them.\n"
    )

    add("## False positives on the controls\n")
    add(
        "By construction, half the letters in every method carry something of the sender's "
        "that looks like PI: one in four its street address, one in four a landline (and one "
        "in four is a firm named after people, to tempt the name model). The checker is "
        "expected to flag the first two until they are on the ignore list, so the figure "
        "that says something about the detectors is the one with the list in place.\n"
    )
    controls = [r for r in rows if r.method in CONTROLS]
    wrong = [r for r in controls if r.flagged]
    still = [r for r in controls if r.flagged_ignoring]
    add(
        f"{len(wrong)} of {len(controls)} control documents were flagged; {len(still)} of "
        f"{len(controls)} with the sender's own details on the ignore list.\n"
    )
    if wrong:
        add("| File | Verdict | What triggered it | With the ignore list |")
        add("|---|---|---|---|")
        for r in wrong:
            causes = []
            for f in r.result.findings:
                cause = f"{f.detector}: “{f.text[:40]}”"
                if f.kind != "context" and cause not in causes:
                    causes.append(cause)
            add(f"| {r.file} | `{r.verdict}` | {'; '.join(causes[:4])} | `{r.verdict_ignoring}` |")
        add("")

    add("## Misses\n")
    missed = [r for r in rows if r.expected_issue and not r.flagged]
    if missed:
        add("| File | Expected | Got |")
        add("|---|---|---|")
        for r in missed:
            add(f"| {r.file} | `{r.expected}` | `{r.verdict}` |")
        add("")
    else:
        add("No document with an issue was passed as clean.\n")
    softer = [r for r in rows if r.expected_issue and r.flagged and r.verdict != r.expected]
    if softer:
        add("Flagged, but with a different verdict than expected:\n")
        for r in softer:
            add(f"- {r.file}: expected `{r.expected}`, got `{r.verdict}`")
        add("")

    add("## Recall by PI type\n")
    add(
        "Each piece of PI the generator put on a page, and whether a finding of the right kind "
        "holds it. Counted where the PI is there to be read: unredacted documents (text layer) "
        "and scans under a see-through marker stroke (OCR).\n"
    )
    add("| PI type | Text layer (`m1_none`) | Through marker, 0.60 | Through marker, 0.85 |")
    add("|---|---|---|---|")
    groups = ("m1_none", "m6_scan_marker_60", "m6_scan_marker_85")
    name_by: Counter = Counter()
    for kind in PI_TYPE_DETECTORS:
        cells = []
        for method in groups:
            hit = total = 0
            for r in (r for r in rows if r.method == method):
                for item_kind, value in r.items:
                    if item_kind != kind:
                        continue
                    total += 1
                    detector = item_found(r, kind, value)
                    hit += detector is not None
                    if kind == "name" and method == "m1_none":
                        name_by[detector or "missed"] += 1
            cells.append(f"{hit}/{total} ({hit / total:.0%})" if total else "n/a")
        add(f"| {kind} | {' | '.join(cells)} |")
    if name_by:
        parts = ", ".join(f"{k}: {v}" for k, v in name_by.most_common())
        add(f"\nNames on unredacted documents, by what caught them: {parts}.\n")

    digital = [r.seconds for r in rows if not r.method.startswith("m6")]
    scans = [r.seconds for r in rows if r.method.startswith("m6")]
    add("## Speed\n")
    if digital:
        add(f"- Digital PDFs: {sum(digital) / len(digital):.1f} s per document on average")
    if scans:
        add(f"- Scans (OCR, plus the enhanced pass): {sum(scans) / len(scans):.1f} s per document")
    add("\nMeasured on the machine that ran this report, CPU only; the first document also pays "
        "for loading the models.\n")  # fmt: skip

    add("## How to reproduce\n")
    add("```")
    add("python -m usefulredact.corpus --n 60 --seed 42")
    add("python -m usefulredact.evaluate")
    add("```")
    return "\n".join(out) + "\n"


def write_results_csv(rows: list[Row], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "method", "variant", "style", "expected", "verdict",
                         "verdict_ignoring_sender", "baseline", "seconds", "pi_findings",
                         "recoverable_findings"])  # fmt: skip
        for r in rows:
            kinds = Counter(f.kind for f in r.result.findings)
            writer.writerow([r.file, r.method, r.variant, r.style, r.expected, r.verdict,
                             r.verdict_ignoring, r.baseline, f"{r.seconds:.2f}", kinds["pi"],
                             kinds["recoverable"]])  # fmt: skip


def read_results_csv(path: Path) -> list[Row]:
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            Row(r["file"], r["method"], r["variant"], r["style"], r["expected"], r["verdict"],
                r["baseline"], float(r["seconds"]), verdict_ignoring=r["verdict_ignoring_sender"])
            for r in csv.DictReader(handle)
        ]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m usefulredact.evaluate", description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("corpus"))
    parser.add_argument("--out", type=Path, default=Path("eval"))
    parser.add_argument("--note", default="seed 42", help="how the corpus was made, for the report")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--chart-only", action="store_true",
                        help="redraw the chart from the last run's results.csv")  # fmt: skip
    args = parser.parse_args(argv)
    if args.chart_only:
        from usefulredact.eval_chart import draw

        draw(read_results_csv(args.out / "results" / "results.csv"), args.out / "eval_chart.png")
        return 0
    if not (args.corpus / "labels.csv").exists():
        print(f"No labels.csv in {args.corpus}/. Generate it first:\n"
              f"  python -m usefulredact.corpus --out {args.corpus}", file=sys.stderr)  # fmt: skip
        return 2
    rows = load(args.corpus)
    run(args.corpus, rows, args.quiet)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "eval_report.md").write_text(report(rows, args.corpus, args.note), encoding="utf-8")
    (args.out / "results").mkdir(exist_ok=True)
    write_results_csv(rows, args.out / "results" / "results.csv")
    try:
        from usefulredact.eval_chart import draw

        draw(rows, args.out / "eval_chart.png")
    except ImportError as exc:  # matplotlib is a development extra
        print(f"chart skipped ({exc}); install the 'eval' extra for it")
    print(f"\nReport: {args.out / 'eval_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
