"""Reports: one JSON file with everything, and two CSVs (documents, findings).

A report contains the personal information that was found: that is the evidence
a person needs to confirm each finding. Keep reports where the documents are kept.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from usefulredact import __version__
from usefulredact.models import VERDICT_ORDER, DocResult

NOTICE = (
    "This report contains the personal information that was found. "
    "'No issues found' means nothing was detected; it is not a guarantee."
)

DOCUMENT_COLUMNS = [
    "file",
    "verdict",
    "pages",
    "recoverable",
    "pi",
    "context",
    "low_confidence",
    "error",
]
FINDING_COLUMNS = [
    "file",
    "verdict",
    "page",
    "kind",
    "detector",
    "text",
    "holds",
    "also",
    "covered",
    "source",
    "score",
    "x0",
    "y0",
    "x1",
    "y1",
    "detail",
]


def sort_results(results: list[DocResult]) -> list[DocResult]:
    """Most serious verdict first, then by name."""
    return sorted(results, key=lambda r: (VERDICT_ORDER.index(r.verdict), r.path.lower()))


def to_json(results: list[DocResult]) -> str:
    payload = {
        "tool": "usefulredact",
        "version": __version__,
        "generated": datetime.now().isoformat(timespec="seconds"),
        "notice": NOTICE,
        "documents": [r.to_dict() for r in sort_results(results)],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _counts(result: DocResult) -> dict[str, int]:
    counts = {"recoverable": 0, "pi": 0, "context": 0, "low_confidence": 0}
    for finding in result.findings:
        counts[finding.kind] = counts.get(finding.kind, 0) + 1
    return counts


def documents_csv(results: list[DocResult]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=DOCUMENT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for r in sort_results(results):
        writer.writerow(
            {"file": r.path, "verdict": r.verdict, "pages": len(r.pages), "error": r.error}
            | _counts(r)
        )
    return out.getvalue()


def findings_csv(results: list[DocResult]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FINDING_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for r in sort_results(results):
        for f in r.findings:
            box = [round(v, 1) for v in f.bbox] if f.bbox else ["", "", "", ""]
            writer.writerow(
                {
                    "file": r.path,
                    "verdict": r.verdict,
                    "page": f.page,
                    "kind": f.kind,
                    "detector": f.detector,
                    "text": f.text,
                    "holds": " ".join(f.holds),
                    "also": " ".join(f.also),
                    "covered": "yes" if f.covered else "",
                    "source": f.source,
                    "score": "" if f.score is None else round(f.score, 3),
                    "x0": box[0],
                    "y0": box[1],
                    "x1": box[2],
                    "y1": box[3],
                    "detail": f.detail,
                }
            )
    return out.getvalue()


def write_reports(results: list[DocResult], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "report.json": to_json(results),
        "documents.csv": documents_csv(results),
        "findings.csv": findings_csv(results),
    }
    written = []
    for name, content in files.items():
        path = out_dir / name
        # utf-8-sig so Excel on Windows reads names with accents correctly
        path.write_text(content, encoding="utf-8-sig" if name.endswith(".csv") else "utf-8")
        written.append(path)
    return written
