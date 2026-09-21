"""Check one document: read every page, look under the marks, look for PI, reach a verdict.

  PDF page with a text layer   words -> pdf_checks (what the page hides) -> PI detectors
  scanned page or image file   render -> OCR -> PI detectors, then a second OCR pass on a
                               contrast-stretched copy when the scan has dark strokes,
                               to read what a marker pen let through
  the document itself          metadata, form-field values, annotation comments

The file is opened read-only and never written to.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageOps
from rapidfuzz import fuzz

from usefulredact import detectors, ner, ocr, pdf_checks
from usefulredact import watchlist as wl
from usefulredact.detectors import Match
from usefulredact.models import (
    CONTEXT,
    FORM_FIELD,
    LOW_CONFIDENCE,
    METADATA,
    OCR,
    OCR_ENHANCED,
    PI,
    TEXT_LAYER,
    DocResult,
    Finding,
    PageInfo,
    union,
)
from usefulredact.pagetext import PageText

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS

TEXT_LAYER_MIN_CHARS = 25  # fewer extractable characters than this: treat the page as a scan
BIG_IMAGE_SHARE = 0.15  # an image this large on a digital page gets OCR of its own
DROPPED_SHARE_MAX = 0.3  # more unreadable regions than this: the page was only partly read
IGNORE_FUZZY_MIN = 90.0  # how close a finding must be to an ignore-list entry to be dropped
BLANK_STD_MAX = 6.0  # grey-level spread under which a page with no text is simply blank

# The second OCR pass. A marker stroke leaves the page under it dark but not black; a
# levels stretch that sends everything above ENHANCE_CEILING to white turns "dark grey
# on black" back into "light grey on black", which the engine can read.
ENHANCE_CEILING = 64
DARK_BLOCK = 8  # px: the scan is averaged over blocks this size ...
DARK_BLOCK_MAX = 110  # ... and a block this dark is ink laid on, not text
DARK_BLOCKS_MIN = 20  # this many dark blocks: there is a stroke worth looking under

# Which detector's finding is kept when two cover the same words.
_PRIORITY = {"watchlist": 0, "name_label": 2, "ner_person": 3}
_RULES_PRIORITY = 1
_CONTEXT_PRIORITY = 9

Progress = Callable[[int, int], None]


# ---------------------------------------------------------------- PI on a page
def _priority(match: Match) -> int:
    if match.kind == CONTEXT:
        return _CONTEXT_PRIORITY
    return _PRIORITY.get(match.detector, _RULES_PRIORITY)


def find_matches(text: str, watchlist: list[str], use_ner: bool = True) -> list[Match]:
    """Every detector over one string, with duplicates folded: a match that sits
    inside one already kept is dropped, and named in the kept one's `also`."""
    candidates: list[Match] = list(wl.find_watchlist(text, watchlist))
    candidates += detectors.find_all(text)
    candidates += ner.find_labelled_names(text)
    if use_ner:
        candidates += ner.find_entities(text)
    candidates.sort(key=lambda m: (_priority(m), -(m.end - m.start), m.start))
    kept: list[Match] = []
    for match in candidates:
        holder = next((k for k in kept if k.start <= match.start and match.end <= k.end), None)
        if holder is None:
            kept.append(match)
        elif match.kind == PI and match.detector not in (holder.detector, *holder.also):
            holder.also.append(match.detector)
    return sorted(kept, key=lambda m: (m.start, m.end))


def _ignored(text: str, ignore: list[str]) -> bool:
    """On the ignore list: the same characters once spacing and punctuation are set
    aside (OCR rarely spaces a phone number the way it was typed), one inside the
    other, or within a couple of misread characters."""
    got = _squash(text)
    for entry in ignore:
        want = _squash(entry)
        if len(want) < 3 or not got:
            continue
        if want in got or got in want or fuzz.ratio(want, got) >= IGNORE_FUZZY_MIN:
            return True
    return False


def pi_findings(
    page_text: PageText,
    page_number: int,
    watchlist: list[str],
    ignore: list[str],
    use_ner: bool = True,
) -> list[Finding]:
    findings = []
    for match in find_matches(page_text.text, watchlist, use_ner):
        text = page_text.text[match.start : match.end].replace("\n", " ")
        if _ignored(text, ignore):
            continue
        boxes = page_text.boxes_for_span(match.start, match.end)
        covered = page_text.span_marked(match.start, match.end)
        detail = match.detail
        if covered:
            detail = f"{detail}; under a mark, still extractable" if detail else "under a mark"
        findings.append(
            Finding(
                page=page_number,
                kind=match.kind,
                detector=match.detector,
                text=text,
                bbox=union(boxes),
                boxes=boxes,
                source=page_text.source,
                detail=detail,
                score=match.score,
                covered=covered,
                also=list(match.also),
            )
        )
    return findings


def _fold_covered(found: list[Finding], under_marks: list[Finding]) -> list[Finding]:
    """PI that sits wholly under a mark is already reported as recovered text. Rather
    than list it twice, say in the recovered-text finding what kind of PI it holds."""
    kept = []
    for finding in found:
        holder = None
        if finding.covered:
            holder = next((r for r in under_marks if _same_place(finding, r)), None)
        if holder is None:
            kept.append(finding)
        elif finding.kind == PI:
            for detector in (finding.detector, *finding.also):
                if detector not in holder.holds:
                    holder.holds.append(detector)
    return kept


def _loose_text_findings(
    text: str, page_number: int, source: str, where: str, bbox, watchlist, ignore, use_ner
) -> list[Finding]:
    """PI in text that has no place in the page's reading order: a metadata value,
    a form field, an annotation's comment."""
    findings = []
    for match in find_matches(text, watchlist, use_ner):
        matched = text[match.start : match.end].replace("\n", " ")
        if _ignored(matched, ignore):
            continue
        detail = f"in {where}" + (f"; {match.detail}" if match.detail else "")
        findings.append(
            Finding(
                page=page_number,
                kind=match.kind,
                detector=match.detector,
                text=matched,
                bbox=bbox,
                boxes=[bbox] if bbox else [],
                source=source,
                detail=detail,
                score=match.score,
                also=list(match.also),
            )
        )
    return findings


# ------------------------------------------------------------------------ OCR
def _grey(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"))


def has_dark_strokes(grey: np.ndarray) -> bool:
    height, width = grey.shape
    h, w = height - height % DARK_BLOCK, width - width % DARK_BLOCK
    if h == 0 or w == 0:
        return False
    blocks = grey[:h, :w].reshape(h // DARK_BLOCK, DARK_BLOCK, w // DARK_BLOCK, DARK_BLOCK)
    return int((blocks.mean(axis=(1, 3)) < DARK_BLOCK_MAX).sum()) >= DARK_BLOCKS_MIN


def enhance(grey: np.ndarray) -> Image.Image:
    stretched = np.clip(grey.astype(np.float32) * (255.0 / ENHANCE_CEILING), 0, 255)
    return Image.fromarray(stretched.astype(np.uint8)).convert("RGB")


def _same_place(a: Finding, b: Finding) -> bool:
    if a.bbox is None or b.bbox is None:
        return False
    x0, y0 = max(a.bbox[0], b.bbox[0]), max(a.bbox[1], b.bbox[1])
    x1, y1 = min(a.bbox[2], b.bbox[2]), min(a.bbox[3], b.bbox[3])
    if x1 <= x0 or y1 <= y0:
        return False
    smaller = min(
        (a.bbox[2] - a.bbox[0]) * (a.bbox[3] - a.bbox[1]),
        (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]),
    )
    return smaller > 0 and (x1 - x0) * (y1 - y0) / smaller > 0.3


def _squash(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()


def ocr_image_page(
    img: Image.Image,
    scale: float,
    page_number: int,
    watchlist: list[str],
    ignore: list[str],
    use_ner: bool = True,
    skip_boxes: list | None = None,
) -> tuple[list[Finding], float | None, int, bool]:
    """OCR one page image. Returns (findings, mean confidence, regions read,
    whether the enhanced pass ran). `skip_boxes` are page-unit boxes the text
    layer already covers; regions over them are left to the text layer."""
    if not ocr.available():
        return (
            [
                Finding(
                    page=page_number,
                    kind=LOW_CONFIDENCE,
                    detector="ocr_unavailable",
                    text="",
                    source=OCR,
                    detail=f"the OCR engine could not start, so this page was not read "
                    f"({ocr.import_error()})",
                )
            ],
            None,
            0,
            False,
        )
    img = img.convert("RGB")
    result = ocr.ocr_image(img, box_thresh=0.5)
    regions = result.regions
    if skip_boxes:
        regions = [r for r in regions if not _over_text_layer(r, scale, skip_boxes)]
    findings: list[Finding] = []
    total = result.n_regions + result.dropped_regions
    partly_read = result.dropped_regions >= 3 and result.dropped_regions / total > DROPPED_SHARE_MAX
    grey = _grey(img)
    if skip_boxes is None:
        if result.low_confidence or partly_read:
            findings.append(
                Finding(
                    page=page_number,
                    kind=LOW_CONFIDENCE,
                    detector="ocr_confidence",
                    text="",
                    source=OCR,
                    score=result.mean_conf,
                    detail=f"read quality {result.mean_conf:.2f} over {result.n_regions} lines, "
                    f"{result.dropped_regions} more unreadable; check this page by eye",
                )
            )
        elif total == 0 and float(grey.std()) > BLANK_STD_MAX:
            findings.append(
                Finding(
                    page=page_number,
                    kind=LOW_CONFIDENCE,
                    detector="ocr_no_text",
                    text="",
                    source=OCR,
                    detail="the page is not blank but no text could be read from it "
                    "(handwriting or a picture, perhaps); check this page by eye",
                )
            )
    page_text = PageText.from_ocr_regions(regions, scale, OCR)
    first = pi_findings(page_text, page_number, watchlist, ignore, use_ner)
    findings += first

    enhanced = False
    if skip_boxes is None and has_dark_strokes(grey):
        enhanced = True
        second = ocr.ocr_image(enhance(grey), box_thresh=0.5)
        text2 = PageText.from_ocr_regions(second.regions, scale, OCR_ENHANCED)
        seen = [f for f in first if f.kind == PI]
        for finding in pi_findings(text2, page_number, watchlist, ignore, use_ner):
            if finding.kind != PI:
                continue
            if any(
                _same_place(finding, f) or _squash(finding.text) == _squash(f.text) for f in seen
            ):
                continue
            note = "read only after the scan's contrast was stretched: likely under a marker stroke"
            finding.detail = f"{finding.detail}; {note}" if finding.detail else note
            findings.append(finding)
            seen.append(finding)
    return findings, result.mean_conf, len(regions), enhanced


def _over_text_layer(region, scale: float, boxes: list) -> bool:
    x0, y0, x1, y1 = (v * scale for v in region.bbox)
    return any(x0 <= (b[0] + b[2]) / 2 <= x1 and y0 <= (b[1] + b[3]) / 2 <= y1 for b in boxes)


# ------------------------------------------------------------------ documents
def _check_image_file(path: Path, result: DocResult, watchlist, ignore, use_ner) -> None:
    with Image.open(path) as opened:
        img = ImageOps.exif_transpose(opened).convert("RGB")
    findings, conf, n_regions, enhanced = ocr_image_page(img, 1.0, 1, watchlist, ignore, use_ner)
    result.pages.append(
        PageInfo(
            number=1,
            width=float(img.width),
            height=float(img.height),
            source=OCR if n_regions else "empty",
            ocr_mean_conf=conf,
            ocr_regions=n_regions,
            enhanced_pass=enhanced,
        )
    )
    result.findings += findings


def _rotated_words(page: pymupdf.Page) -> list[tuple]:
    """Words with their boxes in the page as displayed (rotation applied), which is
    also the space the render and the OCR image live in."""
    rot = page.rotation_matrix
    words = []
    for w in page.get_text("words"):
        rect = pymupdf.Rect(w[:4]) * rot
        words.append((rect.x0, rect.y0, rect.x1, rect.y1, *w[4:]))
    return words


def _page_image(page: pymupdf.Page) -> Image.Image:
    pix = page.get_pixmap(dpi=ocr.OCR_DPI, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _check_pdf_page(page: pymupdf.Page, number: int, result: DocResult, watchlist, ignore, use_ner):
    rect = page.rect
    info = PageInfo(number=number, width=rect.width, height=rect.height, source="empty")
    page_text = PageText.from_words(_rotated_words(page))
    has_text_layer = len(page_text.text.strip()) >= TEXT_LAYER_MIN_CHARS

    if page_text.tokens:
        # What the page hides is asked of any text layer, however thin: a scan with a
        # searchable layer under a burnt-in marker stroke is the same failure.
        under_marks = pdf_checks.check_page(page, page_text, number)
        found = pi_findings(page_text, number, watchlist, ignore, use_ner)
        result.findings += under_marks + _fold_covered(found, under_marks)
        info.source = TEXT_LAYER

    big_image = any(
        pymupdf.Rect(i["bbox"]).get_area() >= BIG_IMAGE_SHARE * rect.get_area()
        for i in page.get_image_info()
    )
    if not has_text_layer or big_image:
        skip = [t.bbox for t in page_text.tokens] if has_text_layer else None
        findings, conf, n_regions, enhanced = ocr_image_page(
            _page_image(page), 72.0 / ocr.OCR_DPI, number, watchlist, ignore, use_ner, skip
        )
        if has_text_layer:  # OCR only adds what the text layer did not already give
            taken = [f for f in result.findings if f.page == number]
            findings = [
                f for f in findings if not any(_squash(f.text) == _squash(t.text) for t in taken)
            ]
        elif n_regions:
            info.source = OCR
        result.findings += findings
        info.ocr_mean_conf, info.ocr_regions, info.enhanced_pass = conf, n_regions, enhanced

    for widget in page.widgets() or []:
        value = str(widget.field_value or "").strip()
        if value and widget.field_type_string not in ("CheckBox", "RadioButton", "Button"):
            box = tuple(widget.rect * page.rotation_matrix)
            where = f"form field '{widget.field_name or 'unnamed'}'"
            result.findings += _loose_text_findings(
                value, number, FORM_FIELD, where, box, watchlist, ignore, use_ner
            )
    for annot in page.annots() or []:
        comment = str((annot.info or {}).get("content") or "").strip()
        if comment:
            box = tuple(annot.rect * page.rotation_matrix)
            result.findings += _loose_text_findings(
                comment,
                number,
                FORM_FIELD,
                "an annotation's comment",
                box,
                watchlist,
                ignore,
                use_ner,
            )
    result.pages.append(info)


def _check_metadata(doc: pymupdf.Document, result: DocResult, watchlist, ignore, use_ner) -> None:
    meta = doc.metadata or {}
    for key in ("author", "title", "subject", "keywords"):
        value = str(meta.get(key) or "").strip()
        if not value:
            continue
        found = _loose_text_findings(
            value, 0, METADATA, f"document metadata ({key})", None, watchlist, ignore, use_ner
        )
        result.findings += found
        if key == "author" and not any(f.kind == PI for f in found) and not _ignored(value, ignore):
            result.findings.append(
                Finding(
                    page=0,
                    kind=CONTEXT,
                    detector="metadata_author",
                    text=value,
                    source=METADATA,
                    detail="the file names its author; remove it if that is a person",
                )
            )


def _entries(value: Iterable[str] | str | None) -> list[str]:
    return wl.parse(value if value is None or isinstance(value, str) else list(value))


def check_document(
    path: str | Path,
    *,
    watchlist: Iterable[str] | str | None = None,
    ignore: Iterable[str] | str | None = None,
    use_ner: bool = True,
    progress: Progress | None = None,
) -> DocResult:
    """Check one file. Never raises for a bad file: the error is in the result,
    and the verdict is NOT_CHECKED rather than anything that reads as a pass."""
    path = Path(path)
    result = DocResult(path=str(path))
    watch = _entries(watchlist)
    skip = [entry.lower() for entry in _entries(ignore)]
    ext = path.suffix.lower()
    try:
        if ext in IMAGE_EXTS:
            _check_image_file(path, result, watch, skip, use_ner)
            if progress:
                progress(1, 1)
        elif ext in PDF_EXTS:
            with pymupdf.open(path) as doc:
                if doc.needs_pass:
                    result.error = "the PDF is password-protected"
                    return result
                _check_metadata(doc, result, watch, skip, use_ner)
                for index, page in enumerate(doc, start=1):
                    _check_pdf_page(page, index, result, watch, skip, use_ner)
                    if progress:
                        progress(index, doc.page_count)
        else:
            result.error = f"unsupported file type '{ext or path.name}'"
    except Exception as exc:  # a corrupt file must not stop the batch
        result.error = f"could not be read: {exc!r}"[:200]
    result.findings.sort(key=lambda f: (f.page, (f.bbox or (0, 0, 0, 0))[1], f.kind))
    return result


def expand_paths(paths: Iterable[str | Path]) -> list[Path]:
    """Files as given; folders walked for supported files, in name order."""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found += sorted(
                f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
            )
        else:
            found.append(p)
    return found
