"""Command line: `python -m usefulredact check <paths>`.

Checks files (or folders of them) and writes report.json, documents.csv and
findings.csv. Runs entirely on this machine; the documents are only read.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from usefulredact import __version__, ner, ocr
from usefulredact.models import NO_ISSUES_FOUND, VERDICT_MEANING, VERDICT_ORDER
from usefulredact.pipeline import check_document, expand_paths
from usefulredact.report import NOTICE, sort_results, write_reports


def _read_list(path: Path | None) -> list[str]:
    if path is None:
        return []
    return path.read_text(encoding="utf-8-sig").splitlines()


def cmd_check(args: argparse.Namespace) -> int:
    files = expand_paths(args.paths)
    if not files:
        print("No PDF or image files found.", file=sys.stderr)
        return 2
    watchlist = _read_list(args.watchlist)
    ignore = _read_list(args.ignore)

    if not ocr.available():
        print(f"OCR engine unavailable ({ocr.import_error()}): scans cannot be read.")
    if not args.no_ner and not ner.available():
        print(f"NER model unavailable ({ner.load_error()}): names will rely on rules only.")

    results = []
    for index, path in enumerate(files, start=1):
        result = check_document(path, watchlist=watchlist, ignore=ignore, use_ner=not args.no_ner)
        results.append(result)
        print(f"[{index}/{len(files)}] {result.verdict:<22} {path}")

    written = write_reports(results, args.out)
    counts = Counter(r.verdict for r in results)
    print()
    for verdict in VERDICT_ORDER:
        if counts[verdict]:
            print(f"  {counts[verdict]:>4}  {verdict:<22} {VERDICT_MEANING[verdict]}")
    print(f"\nReports: {', '.join(str(p) for p in written)}")
    print(NOTICE)
    flagged = [r for r in sort_results(results) if r.verdict != NO_ISSUES_FOUND]
    return 1 if flagged and args.strict else 0


def _never_fail_to_print() -> None:
    """A file can be named in any script, and a Windows console that is piped or redirected
    writes cp1252: printing such a path would raise and stop the whole run. Better a
    question mark in a file name than a batch of documents left unchecked."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    _never_fail_to_print()
    parser = argparse.ArgumentParser(
        prog="usefulredact",
        description="Check whether the redaction in documents holds. Local only; files are "
        "never changed. 'No issues found' is not a guarantee.",
    )
    parser.add_argument("--version", action="version", version=f"usefulredact {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check files or folders (PDF, PNG, JPG)")
    check.add_argument("paths", nargs="+", type=Path)
    check.add_argument("--watchlist", type=Path, help="text file of names to look for, one a line")
    check.add_argument("--ignore", type=Path, help="text file of terms to leave alone, one a line")
    check.add_argument("--out", type=Path, default=Path("usefulredact_out"), help="report folder")
    check.add_argument("--no-ner", action="store_true", help="skip the spaCy name model")
    check.add_argument("--strict", action="store_true", help="exit 1 when any document is flagged")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
