"""Does the text layer still hold words that the page hides? (PyMuPDF)

Two questions are asked of every word on a digital page:

  1. Does it render? The page is drawn to pixels and the word's box examined.
     A word whose box comes out as one flat colour cannot be read on the page,
     whatever did it: a black or white box, an annotation, a pasted image,
     white or invisible text. It is still in the file, so it is recoverable.
     White text on a dark banner keeps its contrast and is left alone, as is
     text on a tinted table cell.

  2. Is it under a mark that only looks like redaction? A dark see-through fill
     or highlight, a redaction annotation that was never applied, a thick dark
     ink stroke. The text may show through, so rendering cannot answer this;
     the mark itself does.

A properly applied redaction removes the words, so there is nothing to find.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pymupdf

from usefulredact.models import RECOVERABLE, Box, Finding, union
from usefulredact.pagetext import PageText, Token

RENDER_DPI = 110  # enough to tell flat colour from glyphs; the OCR path renders separately
UNIFORM_RANGE_MAX = 30  # grey levels between the 2nd and 98th percentile: below this, flat
MIN_WORD_CHARS = 3  # a full stop is a few pixels; short tokens cannot be judged by contrast
MIN_MARK_AREA = 30.0  # pt²: ignore rules, bullets and other specks
WORD_OVERLAP_MIN = 0.5  # share of a word's box a mark must cover
OPAQUE_MIN = 0.99
SEE_THROUGH_DARK_MAX = 0.6  # a see-through mark counts when the page under it goes this dark
INK_DARK_MAX = 0.35
INK_WIDTH_MIN = 4.0  # pt: thinner dark ink is an underline or a circle, not a cover

WHAT = {
    "drawn_shape": "a filled shape drawn over the text",
    "see_through_shape": "a see-through filled shape over the text",
    "annotation": "an annotation placed over the text; deleting it uncovers the text",
    "see_through_annotation": "a see-through annotation or highlight over the text",
    "ink_annotation": "a thick ink stroke over the text; deleting it uncovers the text",
    "unapplied_redaction": "a redaction annotation that was marked but never applied",
    "pasted_image": "an image placed over the text",
    "hidden_text": "text that is in the file but does not show on the page",
}


@dataclass
class Mark:
    rect: pymupdf.Rect
    label: str
    needs_render: bool  # True: only words that fail to render count as under it


def luminance(color) -> float:
    """Approximate luminance of a PyMuPDF colour (grey, RGB or CMYK, 0 to 1). None is white."""
    if not color:
        return 1.0
    c = [float(v) for v in color]
    if len(c) == 1:
        return c[0]
    if len(c) == 4:  # CMYK
        r, g, b = ((1 - v) * (1 - c[3]) for v in c[:3])
    else:
        r, g, b = c[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _see_through_is_dark(lum: float, opacity: float) -> bool:
    return 1.0 - opacity * (1.0 - lum) <= SEE_THROUGH_DARK_MAX


def collect_marks(page: pymupdf.Page) -> list[Mark]:
    marks: list[Mark] = []
    rot = page.rotation_matrix

    for annot in page.annots() or []:
        kind = annot.type[0]
        rect = annot.rect * rot
        if rect.get_area() < MIN_MARK_AREA:
            continue
        opacity = annot.opacity if annot.opacity is not None and annot.opacity >= 0 else 1.0
        colors = annot.colors or {}
        if kind == pymupdf.PDF_ANNOT_REDACT:
            marks.append(Mark(rect, "unapplied_redaction", needs_render=False))
        elif kind in (
            pymupdf.PDF_ANNOT_HIGHLIGHT,
            pymupdf.PDF_ANNOT_UNDERLINE,
            pymupdf.PDF_ANNOT_SQUIGGLY,
        ):
            if kind == pymupdf.PDF_ANNOT_HIGHLIGHT and _see_through_is_dark(
                luminance(colors.get("stroke")), opacity
            ):
                marks.append(Mark(rect, "see_through_annotation", needs_render=False))
            else:
                marks.append(Mark(rect, "annotation", needs_render=True))
        elif kind == pymupdf.PDF_ANNOT_INK:
            width = (annot.border or {}).get("width") or 0
            dark = luminance(colors.get("stroke")) <= INK_DARK_MAX
            marks.append(
                Mark(rect, "ink_annotation", needs_render=not (dark and width >= INK_WIDTH_MIN))
            )
        elif kind in (pymupdf.PDF_ANNOT_LINK, pymupdf.PDF_ANNOT_POPUP, pymupdf.PDF_ANNOT_WIDGET):
            continue
        else:  # square, circle, polygon, free text, stamp ...
            fill = colors.get("fill")
            if fill and opacity < OPAQUE_MIN and _see_through_is_dark(luminance(fill), opacity):
                marks.append(Mark(rect, "see_through_annotation", needs_render=False))
            else:
                marks.append(Mark(rect, "annotation", needs_render=True))

    for drawing in page.get_drawings():
        if drawing.get("fill") is None:
            continue
        rect = pymupdf.Rect(drawing["rect"]) * rot
        if rect.get_area() < MIN_MARK_AREA:
            continue
        opacity = drawing.get("fill_opacity")
        opacity = 1.0 if opacity is None else float(opacity)
        if opacity < OPAQUE_MIN:
            if _see_through_is_dark(luminance(drawing["fill"]), opacity):
                marks.append(Mark(rect, "see_through_shape", needs_render=False))
        else:
            marks.append(Mark(rect, "drawn_shape", needs_render=True))

    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"]) * rot
        if rect.get_area() >= MIN_MARK_AREA:
            marks.append(Mark(rect, "pasted_image", needs_render=True))
    return marks


class Render:
    """The page as grey pixels, to ask whether a box shows anything."""

    def __init__(self, page: pymupdf.Page):
        pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csGRAY, alpha=False)
        self.scale = RENDER_DPI / 72.0
        self.grey = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)

    def is_flat(self, box: Box, strict: bool = False) -> bool:
        """True when the box is one flat colour: nothing in it can be read.

        The spread is taken between the 2nd and 98th percentile, which forgives the
        speckle of a scanned or JPEG cover. `strict` takes the full range instead:
        a short token is a few pixels of ink, which percentiles would wave through."""
        x0, y0, x1, y1 = (v * self.scale for v in box)
        height, width = self.grey.shape
        c0, c1 = max(0, int(x0) + 1), min(width, int(x1))
        r0, r1 = max(0, int(y0) + 1), min(height, int(y1))
        if c1 - c0 < 2 or r1 - r0 < 2:
            return False
        region = self.grey[r0:r1, c0:c1]
        if strict:
            return int(region.max()) - int(region.min()) < UNIFORM_RANGE_MAX
        lo, hi = np.percentile(region, (2, 98))
        return float(hi - lo) < UNIFORM_RANGE_MAX


def _judgeable(token: Token) -> bool:
    return sum(ch.isalnum() for ch in token.text) >= MIN_WORD_CHARS


def _overlap_share(word: pymupdf.Rect, mark: pymupdf.Rect) -> float:
    area = word.get_area()
    if area <= 0:
        return 0.0
    inter = pymupdf.Rect(word)
    inter.intersect(mark)
    return 0.0 if inter.is_empty else inter.get_area() / area


def check_page(page: pymupdf.Page, page_text: PageText, page_number: int) -> list[Finding]:
    """Mark the tokens that sit under something (token.mark, and token.hidden when
    they do not render) and return one finding per run of neighbouring words."""
    if not page_text.tokens:
        return []
    marks = collect_marks(page)
    render = Render(page)
    labels: dict[int, str] = {}

    for index, token in enumerate(page_text.tokens):
        word = pymupdf.Rect(token.bbox)
        label = None
        for mark in marks:
            if _overlap_share(word, mark.rect) < WORD_OVERLAP_MIN:
                continue
            if not mark.needs_render:
                label = mark.label
                break
            under = pymupdf.Rect(word)
            under.intersect(mark.rect)
            if render.is_flat(tuple(under), strict=not _judgeable(token)):
                label = mark.label
                token.hidden = True
                break
        if label is None and _judgeable(token) and render.is_flat(token.bbox):
            label = "hidden_text"
            token.hidden = True
        if label:
            labels[index] = label
            token.mark = label

    # Short tokens between two hidden words ("J." in "Dr J. Citizen") go with them.
    for index, token in enumerate(page_text.tokens):
        if index not in labels and not _judgeable(token):
            before, after = labels.get(index - 1), labels.get(index + 1)
            if before and before == after and render.is_flat(token.bbox, strict=True):
                labels[index] = before
                token.hidden = True
                token.mark = before

    findings: list[Finding] = []
    run: list[int] = []
    for index in sorted(labels):
        if run and (index != run[-1] + 1 or labels[index] != labels[run[0]]):
            findings.append(_finding(page_text, run, labels[run[0]], page_number))
            run = []
        run.append(index)
    if run:
        findings.append(_finding(page_text, run, labels[run[0]], page_number))
    return findings


def _finding(page_text: PageText, run: list[int], label: str, page_number: int) -> Finding:
    tokens = [page_text.tokens[i] for i in run]
    start, end = tokens[0].start, tokens[-1].end
    boxes = page_text.boxes_for_span(start, end)
    return Finding(
        page=page_number,
        kind=RECOVERABLE,
        detector=label,
        text=page_text.text[start:end].replace("\n", " "),
        bbox=union(boxes),
        boxes=boxes,
        source=page_text.source,
        detail=WHAT[label],
    )
